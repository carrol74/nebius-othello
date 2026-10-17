import math
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytrio as trio

from nemothello.calibration import GENERATION_CALIBRATION
from nemothello.data import read_jsonl, validate_sample, write_json
from nemothello.errors import AppError
from nemothello.policy import (
    GENERATION_MODE,
    GENERATION_SETTINGS,
    SYMBOLS,
    TEMPLATE_VERSION,
    GenerationPolicy,
    encode_position,
    position_encoder,
    training_datum,
)


def calibrate_generation(
    api_key: str, base_model: str, data: Path, output: Path, name: str,
    model_path: str | None, sampler_path: str | None,
    limit: int = 12, tolerance: float = 1e-4, repeats: int = 3,
    template_version: str | None = None,
) -> dict[str, Any]:
    """Check generation independently of the legacy cross-engine score comparison."""
    if output.exists():
        raise ValueError("Calibration output already exists. Use a new file to preserve original evidence")
    if (limit < 2 or repeats < 3 or not math.isfinite(tolerance) or tolerance < 0
            or bool(model_path) != bool(sampler_path)):
        raise ValueError("At least two samples and three repeats are required; restoration requires paired Train and Sampler paths")
    encoder = encode_position if template_version is None else position_encoder(template_version)
    active_template = TEMPLATE_VERSION if template_version is None else template_version
    policy_options = {} if template_version is None else {"template_version": template_version}
    samples = read_jsonl(data)
    if len(samples) < limit:
        raise ValueError("Not enough samples")
    selected = sorted(samples, key=lambda sample: len(sample["candidates"]))
    selected = [selected[index] for index in np.linspace(0, len(selected) - 1, limit, dtype=int)]
    for sample in selected:
        validate_sample(sample)
    report: dict[str, Any] = {
        "status": "running", "artifact_kind": "calibration-only", "base_model": base_model,
        "template_version": active_template, "symbols": SYMBOLS,
        "scoring_mode": GENERATION_MODE, "calibration_kind": GENERATION_CALIBRATION,
        "generation_settings": dict(GENERATION_SETTINGS), "repeat_count": repeats,
        "source_model_path": model_path, "source_sampler_path": sampler_path,
        "tolerance": tolerance, "data_path": str(data), "samples": [], "checks": {},
        "scope": "Encoding, Train save/restore, and single-request move legality and stability; does not establish strength.",
    }
    write_json(output, report)
    trio.configure(request_timeout_seconds=90, control_retry_timeout_seconds=30,
                   actor_capacity_wait_timeout_seconds=90, actor_event_submit_timeout_seconds=90,
                   actor_event_polling_timeout_seconds=90)
    service = trio.ServiceClient(api_key=api_key)
    training = (service.create_training_client_from_state(model_path) if model_path else
                service.create_lora_training_client(base_model=base_model, rank=32, seed=42))
    if training.model_id != base_model:
        raise ValueError("Train checkpoint differs from the base model")
    tokenizer = training.get_tokenizer()
    before_forward = []
    for sample in selected:
        encoded = encoder(tokenizer, tuple(sample["board"]), sample["turn"])
        if list(encoded.coordinates) != sample["candidates"]:
            raise ValueError("Candidate order differs from training labels")
        datum = training_datum(encoded, sample["target"])
        result = training.forward([datum], loss_fn="cross_entropy", auto_shift=False).result()
        before_forward.append((sample, encoded, datum, answer_logprob(result, len(encoded.prefix))))
        print(f"Generation calibration encoding and supervision: {len(before_forward)}/{limit}", flush=True)
    saved = training.save_state(name=f"{name}-train", ttl_seconds=None).result()
    sampler_saved = training.save_weights_for_sampler(name=f"{name}-sampler", ttl_seconds=None).result()
    report.update(model_path=saved.path, sampler_path=sampler_saved.path,
                  source_sampler_path=sampler_path or sampler_saved.path)
    write_json(output, report)
    original = GenerationPolicy(api_key, base_model, report["source_sampler_path"], **policy_options)
    restored = GenerationPolicy(api_key, base_model, sampler_saved.path, **policy_options)
    started = time.monotonic()
    original.connect()
    restored.connect()
    report["sampling_clients_creation_ms"] = (time.monotonic() - started) * 1000
    recovered_training = service.create_training_client_from_state(saved.path)
    checks = {"encoding": True, "train_restore": True, "legal_outputs": True,
              "repeat_selection": True, "sampler_restore_selection": True}
    for sample, encoded, datum, score in before_forward:
        for policy in (original, restored):
            recovered_encoded = encoder(policy.tokenizer, tuple(sample["board"]), sample["turn"])
            if (recovered_encoded.prefix != encoded.prefix
                    or recovered_encoded.symbol_tokens != encoded.symbol_tokens):
                raise ValueError("Sampler encoding differs from training encoding")
        recovered = recovered_training.forward([datum], loss_fn="cross_entropy", auto_shift=False).result()
        difference = abs(score - answer_logprob(recovered, len(encoded.prefix)))
        row = {"game_id": sample["game_id"], "ply": sample["ply"],
               "candidate_count": len(encoded.coordinates), "logical_input_tokens": len(encoded.prefix),
               "max_restore_difference": difference, "before": [], "after": []}
        for key, policy in (("before", original), ("after", restored)):
            for _ in range(repeats):
                try:
                    decision = policy.score_encoded(encoded)
                    row[key].append({"legal": True, **decision})
                except AppError as error:
                    if error.code not in ("POLICY_ILLEGAL_OUTPUT", "POLICY_OUTPUT_SHAPE"):
                        raise
                    row[key].append({"legal": False, "error_code": error.code})
        outputs = row["before"] + row["after"]
        legal = all(item["legal"] for item in outputs)
        stable = legal and all(len({item["coordinate"] for item in row[key]}) == 1
                               for key in ("before", "after"))
        matched = legal and len({item["coordinate"] for item in outputs}) == 1
        checks["train_restore"] &= difference <= tolerance
        checks["legal_outputs"] &= legal
        checks["repeat_selection"] &= stable
        checks["sampler_restore_selection"] &= matched
        report["samples"].append(row)
        write_json(output, report)
        print(f"Generation calibration comparison: {len(report['samples'])}/{limit}, legal {legal}, "
              f"repeat stability {stable}, restored move agreement {matched}, weight restoration error {difference:.6g}", flush=True)
    report["checks"] = checks
    decisions = [item for row in report["samples"] for key in ("before", "after")
                 for item in row[key]]
    valid = [item for item in decisions if item["legal"]]
    first_calls = [row["before"][0]["elapsed_ms"] for row in report["samples"]
                   if row["before"][0]["legal"]]
    report["summary"] = {
        "generation_calls": len(decisions), "legal_rate": len(valid) / len(decisions),
        "elapsed_p50_ms": float(np.percentile([item["elapsed_ms"] for item in valid], 50)) if valid else None,
        "elapsed_p95_ms": float(np.percentile([item["elapsed_ms"] for item in valid], 95)) if valid else None,
        "first_position_call_p50_ms": float(np.percentile(first_calls, 50)) if first_calls else None,
        "first_position_call_p95_ms": float(np.percentile(first_calls, 95)) if first_calls else None,
        "input_tokens": sum(item["input_tokens"] for item in valid),
        "output_tokens": sum(item["output_tokens"] for item in valid),
    }
    report["status"] = "passed" if all(checks.values()) else "failed"
    write_json(output, report)
    if report["status"] != "passed":
        raise ValueError(f"Single-token generation calibration failed; see {output}")
    return report


def answer_logprob(output: Any, length: int) -> float:
    if len(output.loss_fn_outputs) != 1:
        raise ValueError("Supervised score count is incomplete")
    values = output.loss_fn_outputs[0]["logprobs"].to_numpy()
    if values.shape != (length,) or not np.isfinite(values).all() or values[-1] > 1e-5:
        raise ValueError("Supervised score shape or values are invalid")
    return float(values[-1])
