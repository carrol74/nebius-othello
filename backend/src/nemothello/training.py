import importlib.metadata
import json
import math
import random
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
import pytrio as trio

from nemothello.calibration import calibration_passed
from nemothello.data import read_jsonl, validate_sample, write_json
from nemothello.policy import (
    SCORING_MODE,
    SYMBOLS,
    TEMPLATE_VERSION,
    PytrioPolicy,
    SamplingPolicy,
    complete_scores,
    encode_position,
    scoring_datums,
    training_datum,
)
from nemothello.pytrio_transport import RETRIED_SUBMIT_TYPES, enable_training_event_retries
from nemothello.training_recovery import atomic_json, recoverable_error, validate_progress
from nemothello.validation_cache import validate_cache, validation_signature


def calibrate(
    api_key: str, base_model: str, data: Path, output: Path, name: str,
    model_path: str | None, limit: int = 12, tolerance: float = 1e-4,
) -> dict[str, Any]:
    samples = read_jsonl(data)
    if limit < 2 or len(samples) < limit:
        raise ValueError("Scoring verification requires at least two samples and enough samples for the requested limit")
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("Scoring tolerance must be finite and nonnegative")
    selected = sorted(samples, key=lambda s: len(s["candidates"]))
    indices = np.linspace(0, len(selected) - 1, limit, dtype=int)
    selected = [selected[i] for i in indices]
    report = {"status": "running", "base_model": base_model,
              "template_version": TEMPLATE_VERSION, "symbols": SYMBOLS,
              "scoring_mode": SCORING_MODE, "source_model_path": model_path,
              "artifact_kind": "calibration-only", "tolerance": tolerance,
              "samples": [], "data_path": str(data), "forward_samples": 0,
              "batch_order_checked": False}
    write_json(output, report)
    service = trio.ServiceClient(api_key=api_key)
    training = (
        service.create_training_client_from_state(model_path) if model_path
        else service.create_lora_training_client(base_model=base_model, rank=32, seed=42)
    )
    tokenizer = training.get_tokenizer()
    before = []
    for sample in selected:
        encoded = encode_position(tokenizer, tuple(sample["board"]), sample["turn"])
        result = training.forward(
            scoring_datums(encoded), loss_fn="cross_entropy", auto_shift=False,
        ).result()
        before.append((sample, encoded, complete_scores(result, encoded), result.metrics))
        report["forward_samples"] = len(before)
        write_json(output, report)
        print(f"Calibration initial scores: {len(before)}/{limit}", flush=True)
    saved = training.save_state(name=f"{name}-train", ttl_seconds=None).result()
    sampler_saved = training.save_weights_for_sampler(
        name=f"{name}-sampler", ttl_seconds=None,
    ).result()
    report["model_path"] = saved.path
    report["sampler_path"] = sampler_saved.path
    write_json(output, report)
    reference = SamplingPolicy(api_key, base_model, sampler_saved.path)
    restored = PytrioPolicy(api_key, base_model, saved.path)
    rows = report["samples"]
    passed = True
    for sample, encoded, scores, metrics in before:
        reference_encoded = encode_position(reference.tokenizer, tuple(sample["board"]), sample["turn"])
        if reference_encoded.prefix != encoded.prefix or reference_encoded.symbol_tokens != encoded.symbol_tokens:
            raise ValueError("Restored sampler tokenization differs from the original scoring input")
        reference_scores = reference.score_encoded(encoded)
        recovered = restored.score(tuple(sample["board"]), sample["turn"])
        restored_scores = recovered["scores"]
        difference = max(abs(scores[m] - reference_scores[m]) for m in scores)
        recovery_difference = max(abs(scores[m] - restored_scores[m]) for m in scores)
        # Reverse only the batch rows. The prompt and symbol mapping are unchanged.
        reverse_rows = replace(encoded, coordinates=encoded.coordinates[::-1],
                               symbols=encoded.symbols[::-1],
                               symbol_tokens=encoded.symbol_tokens[::-1])
        reversed_result = training.forward(
            scoring_datums(encoded)[::-1], loss_fn="cross_entropy", auto_shift=False,
        ).result()
        reversed_scores = complete_scores(reversed_result, reverse_rows)
        batch_order_difference = max(abs(scores[m] - reversed_scores[m]) for m in scores)
        passed &= (difference <= tolerance and recovery_difference <= tolerance
                   and batch_order_difference <= tolerance)
        reverse = encode_position(tokenizer, tuple(sample["board"]), sample["turn"],
                                  tuple(reversed(encoded.coordinates)))
        reverse_output = training.forward(
            scoring_datums(reverse), loss_fn="cross_entropy", auto_shift=False,
        ).result()
        reordered = complete_scores(reverse_output, reverse)
        rows.append({"game_id": sample["game_id"], "ply": sample["ply"],
                     "input_tokens": len(encoded.prefix) * len(scores),
                     "logical_input_tokens": len(encoded.prefix), "candidate_count": len(scores),
                     "batched_forward": scores, "reference": reference_scores,
                     "restored": restored_scores,
                     "max_reference_difference": difference, "max_restore_difference": recovery_difference,
                     "reversed_batch": reversed_scores,
                     "max_batch_order_difference": batch_order_difference,
                     "reordered": reordered,
                     "order_changed_selection": max(scores, key=scores.get) != max(reordered, key=reordered.get),
                     "metrics": metrics, "restored_elapsed_ms": recovered["elapsed_ms"]})
        write_json(output, report)
        print(f"Calibration comparison and restoration: {len(rows)}/{limit}, error {difference:.6g}/{recovery_difference:.6g}, "
              f"batch order error {batch_order_difference:.6g}",
              flush=True)
    report["batch_order_checked"] = True
    report["status"] = "passed" if passed else "failed"
    write_json(output, report)
    if not passed:
        raise ValueError(f"Scoring or restoration verification failed; see {output}")
    return report


def validate_loss(
    training: Any, datums: list[Any], batch_size: int,
    cache_path: Path | None = None, state_path: str | None = None,
) -> float:
    record: dict[str, Any] = {"batches": []}
    if cache_path is not None:
        signature = validation_signature(datums, batch_size, state_path or "", training.model_id)
        if cache_path.exists():
            record = json.loads(cache_path.read_text())
            validate_cache(record, signature, len(datums), batch_size)
        else:
            record.update(version=1, signature=signature, state_path=state_path)
            atomic_json(cache_path, record)
    completed = record["batches"]
    total = sum(batch["answer_loss_sum"] for batch in completed)
    batches = (len(datums) + batch_size - 1) // batch_size
    if completed:
        print(f"Reusing saved validation batches: {len(completed)}/{batches}", flush=True)
    for start in range(len(completed) * batch_size, len(datums), batch_size):
        batch = datums[start:start + batch_size]
        output = training.forward(batch, loss_fn="cross_entropy", auto_shift=False).result()
        validate_training_output(output, [datum.loss_fn_inputs["target_tokens"].shape[0]
                                          for datum in batch])
        loss = sum(-float(item["logprobs"].to_numpy()[-1]) for item in output.loss_fn_outputs)
        completed.append({"batch": start // batch_size, "positions": len(batch),
                          "answer_loss_sum": loss})
        if cache_path is not None:
            atomic_json(cache_path, record)
        total += loss
        print(f"Validation batches completed: {len(completed)}/{batches}", flush=True)
    return total / len(datums)


def validate_training_output(output: Any, lengths: list[int]) -> None:
    if len(output.loss_fn_outputs) != len(lengths):
        raise ValueError("Training returned an incomplete answer count; stopping optimizer update")
    for item, length in zip(output.loss_fn_outputs, lengths, strict=True):
        values = np.asarray(item["logprobs"].to_numpy())
        if (values.shape != (length,) or not np.isfinite(values).all()
                or values[-1] > 1e-5):
            raise ValueError("Training answer shape or values are invalid; stopping optimizer update")
    if any(not math.isfinite(value) for value in output.metrics.values()):
        raise ValueError("Training returned nonfinite metrics; stopping optimizer update")


def train(
    api_key: str, base_model: str, dataset: Path, output: Path, name: str,
    calibration: dict[str, Any], rank: int = 32, learning_rate: float = 1e-4,
    batch_size: int = 16, epochs: int = 2, seed: int = 42, resume: bool = False,
    checkpoint_every: int = 25,
) -> dict[str, Any]:
    policy_mode = calibration.get("scoring_mode", "")
    if not calibration_passed(calibration, base_model, policy_mode):
        raise ValueError("Training requires live scoring verification for the current base model and template")
    if (rank < 4 or rank > 64 or batch_size < 1 or epochs < 1 or checkpoint_every < 1
            or not math.isfinite(learning_rate) or learning_rate <= 0):
        raise ValueError("Training parameters are outside valid ranges")
    examples = read_jsonl(dataset / "train.jsonl")
    validation = read_jsonl(dataset / "validation.jsonl")
    test = read_jsonl(dataset / "test.jsonl")
    for group in (examples, validation, test):
        for sample in group:
            validate_sample(sample)
    groups = [{item["game_id"] for item in group} for group in (examples, validation, test)]
    if not all(groups) or any(groups[a] & groups[b] for a, b in ((0, 1), (0, 2), (1, 2))):
        raise ValueError("Training, validation, and test splits must be nonempty with no shared games")
    calibration_ids = {sample["game_id"] for sample in calibration["samples"]}
    if not calibration_ids <= groups[0]:
        raise ValueError("Scoring calibration samples must come from the current training split")
    identity = {
        "base_model": base_model, "rank": rank, "learning_rate": learning_rate,
        "batch_size": batch_size, "seed": seed, "template_version": TEMPLATE_VERSION,
        "policy_mode": policy_mode,
        "symbols": SYMBOLS, "dataset": str(dataset.resolve()),
        "dataset_groups": {name: {"game_ids": sorted(group), "positions": len(rows)}
                           for name, group, rows in zip(
                               ("train", "validation", "test"), groups,
                               (examples, validation, test), strict=True)},
    }
    dataset_manifest = {
        name: [{key: row[key] for key in ("game_id", "ply", "board", "turn", "target", "candidates")}
               for row in rows]
        for name, rows in zip(("train", "validation", "test"),
                              (examples, validation, test), strict=True)
    }
    history = []
    checkpoint_path = None
    progress = None
    batches = (len(examples) + batch_size - 1) // batch_size
    if resume:
        config = json.loads((output / "training-config.json").read_text())
        if any(config.get(key) != value for key, value in identity.items()):
            raise ValueError("Resuming requires the original base model, training configuration, and game-level data splits")
        if json.loads((output / "dataset-manifest.json").read_text()) != dataset_manifest:
            raise ValueError("Training positions, labels, candidates, or order changed; cannot resume the original optimizer")
        if (output / "training-progress.json").exists():
            progress = json.loads((output / "training-progress.json").read_text())
        elif (output / "training-history.json").exists():
            history = json.loads((output / "training-history.json").read_text())
            if not history:
                raise ValueError("Resuming requires a saved training checkpoint")
            progress = {"version": 1, "next_epoch": len(history), "next_batch": 0,
                        "state_path": history[-1]["state_path"], "history": history, "updates": []}
        else:
            raise ValueError("The original task has no saved checkpoint; local loss records cannot resume training")
        validate_progress(progress, batches, epochs)
        history = progress["history"]
        checkpoint_path = progress["state_path"]
    elif output.exists() and any(output.iterdir()):
        raise ValueError("Output directory contains artifacts. Use --resume to continue or a new directory for a new experiment")
    # A failed POST may already have mutated gradients. Recover from a checkpoint
    # in another process rather than retrying an uncertain event on this run.
    trio.configure(training_retry_timeout_seconds=0, training_event_max_in_flight=1,
                   training_event_queue_capacity=1, request_timeout_seconds=90,
                   actor_event_submit_timeout_seconds=90, actor_event_polling_timeout_seconds=90,
                   control_retry_timeout_seconds=30, actor_capacity_wait_timeout_seconds=90)
    enable_training_event_retries()
    service = trio.ServiceClient(api_key=api_key)
    training = service.create_lora_training_client(base_model=base_model, rank=rank, seed=seed)
    if checkpoint_path:
        training.load_state_with_optimizer(checkpoint_path).result()
    tokenizer = training.get_tokenizer()
    if resume and tokenizer.chat_template != config["chat_template"]:
        raise ValueError("Tokenizer chat template changed; cannot resume with the original encoding")

    def datum(item: dict[str, Any]):
        encoded = encode_position(tokenizer, tuple(item["board"]), item["turn"])
        if tuple(item["candidates"]) != encoded.coordinates:
            raise ValueError("Sample candidate order differs from training encoding")
        return training_datum(encoded, item["target"]), len(encoded.prefix)

    encoded_training = [datum(item) for item in examples]
    validation_datums = [datum(item)[0] for item in validation]
    lengths = [length for _, length in encoded_training]
    best = min(history, key=lambda entry: entry["validation_answer_loss"]) if history else None
    best_loss = best["validation_answer_loss"] if best else math.inf
    best_path = best["state_path"] if best else None
    best_sampler_path = best["sampler_path"] if best else None
    start_epoch = progress["next_epoch"] if progress else 0
    invocation_id = uuid4().hex[:12]
    output.mkdir(parents=True, exist_ok=True)
    atomic_json(output / "dataset-manifest.json", dataset_manifest)
    atomic_json(output / "training-config.json", {
        **identity, "epochs": epochs, "resumed_from": checkpoint_path,
        "checkpoint_every": checkpoint_every, "batch_checkpoint_ttl_seconds": 604800,
        "training_event_retry_timeout_seconds": 0,
        "event_get_max_attempts": 3,
        "event_submit_max_attempts": 3,
        "event_submit_retry_types": sorted(kind.value for kind in RETRIED_SUBMIT_TYPES),
        "token_lengths": {"min": min(lengths), "max": max(lengths),
                          "p50": float(np.percentile(lengths, 50)),
                          "p95": float(np.percentile(lengths, 95)), "total": sum(lengths)},
        "packages": {package: importlib.metadata.version(package)
                     for package in ("pytrio", "transformers", "modelscope")},
        "tokenizer_name": tokenizer.name_or_path, "chat_template": tokenizer.chat_template,
        "calibration_model_path": calibration["model_path"],
        "training_run_id": training.training_run_cuid,
    })

    def commit_progress(epoch: int, batch: int, updates: list[Any], state_path: str) -> None:
        nonlocal progress
        record = {"version": 1, "next_epoch": epoch, "next_batch": batch,
                  "state_path": state_path, "history": list(history), "updates": list(updates)}
        validate_progress(record, batches, epochs)
        atomic_json(output / "training-progress.json", record)
        progress = record
        atomic_json(output / "training-history.json", history)

    def snapshot(epoch: int, batch: int, updates: list[Any]) -> None:
        saved = training.save_state(
            name=f"{name}-{invocation_id}-e{epoch + 1}-b{batch}", ttl_seconds=604800,
        ).result()
        commit_progress(epoch, batch, updates, saved.path)
        print(f"Training checkpoint saved: epoch {epoch + 1}, completed batches {batch}", flush=True)

    epoch, updates = start_epoch, []
    try:
        atomic_json(output / "training-status.json", {
            "status": "running", "invocation_id": invocation_id,
            "training_run_id": training.training_run_cuid,
        })
        if progress is None:
            snapshot(0, 0, [])
        for epoch in range(start_epoch, epochs):
            order = list(range(len(encoded_training)))
            random.Random(seed + epoch).shuffle(order)
            resume_batch = progress["next_batch"] if epoch == progress["next_epoch"] else 0
            updates = list(progress["updates"]) if resume_batch else []
            atomic_json(output / f"epoch-{epoch + 1}-updates.json", updates)
            for batch_index in range(resume_batch, batches):
                start = batch_index * batch_size
                batch = [encoded_training[index][0] for index in order[start:start + batch_size]]
                output_forward = training.forward_backward(
                    batch, loss_fn="cross_entropy", auto_shift=False,
                ).result()
                validate_training_output(output_forward,
                                         [encoded_training[index][1]
                                          for index in order[start:start + batch_size]])
                training.optim_step(trio.AdamParams(learning_rate=learning_rate)).result()
                updates.append({"batch": batch_index, "metrics": output_forward.metrics})
                atomic_json(output / f"epoch-{epoch + 1}-updates.json", updates)
                if len(updates) % checkpoint_every == 0 or len(updates) == batches:
                    snapshot(epoch, len(updates), updates)
                print(f"Training epoch {epoch + 1}/{epochs}, batch {len(updates)}/{batches}", flush=True)
            loss = validate_loss(training, validation_datums, batch_size,
                                 output / f"epoch-{epoch + 1}-validation.json", progress["state_path"])
            checkpoint = training.save_state(
                name=f"{name}-{invocation_id}-epoch-{epoch + 1}", ttl_seconds=None,
            ).result()
            sampler = training.save_weights_for_sampler(
                name=f"{name}-{invocation_id}-policy-epoch-{epoch + 1}", ttl_seconds=None,
            ).result()
            history.append({"epoch": epoch + 1, "validation_answer_loss": loss,
                            "state_path": checkpoint.path, "sampler_path": sampler.path})
            if loss < best_loss:
                best_loss, best_path, best_sampler_path = loss, checkpoint.path, sampler.path
            commit_progress(epoch + 1, 0, [], checkpoint.path)
    except (Exception, KeyboardInterrupt) as error:
        atomic_json(output / "training-status.json", {
            "status": "interrupted", "invocation_id": invocation_id,
            "training_run_id": training.training_run_cuid,
            "error_type": type(error).__name__, "error_code": getattr(error, "code", ""),
            "http_status": getattr(error, "status_code", 0),
            "recoverable": progress is not None and recoverable_error(error),
            "confirmed_epoch": epoch + 1, "confirmed_batches": len(updates),
            "checkpoint": progress,
        })
        raise
    result = {"status": "trained-not-strength-verified", "artifact_kind": "trained-policy",
              "policy_mode": policy_mode,
              "base_model": base_model, "model_path": best_path,
              "sampler_path": best_sampler_path, "validation_loss": best_loss,
              "template_version": TEMPLATE_VERSION, "history": history}
    atomic_json(output / "adapter-metadata.json", result)
    atomic_json(output / "training-status.json", {
        "status": "completed", "invocation_id": invocation_id,
        "training_run_id": training.training_run_cuid,
    })
    return result
