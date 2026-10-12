import importlib.metadata
import json
import math
import random
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
import pytrio as trio

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


def calibrate(
    api_key: str, base_model: str, data: Path, output: Path, name: str,
    model_path: str | None, limit: int = 12, tolerance: float = 1e-4,
) -> dict[str, Any]:
    samples = read_jsonl(data)
    if limit < 2 or len(samples) < limit:
        raise ValueError("评分核验至少需要两条样本，样本数量需达到指定 limit")
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("评分核验容差必须为有限的非负数")
    selected = sorted(samples, key=lambda s: len(s["candidates"]))
    indices = np.linspace(0, len(selected) - 1, limit, dtype=int)
    selected = [selected[i] for i in indices]
    report = {"status": "running", "base_model": base_model,
              "template_version": TEMPLATE_VERSION, "symbols": SYMBOLS,
              "scoring_mode": SCORING_MODE, "source_model_path": model_path,
              "artifact_kind": "calibration-only", "tolerance": tolerance,
              "samples": [], "data_path": str(data), "forward_samples": 0}
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
        print(f"校准初始评分：{len(before)}/{limit}", flush=True)
    saved = training.save_weights_for_sampler(name=name, ttl_seconds=None).result()
    report["model_path"] = saved.path
    write_json(output, report)
    reference = SamplingPolicy(api_key, base_model, saved.path)
    restored = PytrioPolicy(api_key, base_model, saved.path)
    rows = report["samples"]
    passed = True
    for sample, encoded, scores, metrics in before:
        reference_encoded = encode_position(reference.tokenizer, tuple(sample["board"]), sample["turn"])
        if reference_encoded.prefix != encoded.prefix or reference_encoded.symbol_tokens != encoded.symbol_tokens:
            raise ValueError("恢复采样器的 tokenizer 编码与原始评分不同")
        reference_scores = reference.score_encoded(encoded)
        recovered = restored.score(tuple(sample["board"]), sample["turn"])
        restored_scores = recovered["scores"]
        difference = max(abs(scores[m] - reference_scores[m]) for m in scores)
        recovery_difference = max(abs(scores[m] - restored_scores[m]) for m in scores)
        passed &= difference <= tolerance and recovery_difference <= tolerance
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
                     "reordered": reordered,
                     "order_changed_selection": max(scores, key=scores.get) != max(reordered, key=reordered.get),
                     "metrics": metrics, "restored_elapsed_ms": recovered["elapsed_ms"]})
        write_json(output, report)
        print(f"校准对照与恢复：{len(rows)}/{limit}，误差 {difference:.6g}/{recovery_difference:.6g}",
              flush=True)
    report["status"] = "passed" if passed else "failed"
    write_json(output, report)
    if not passed:
        raise ValueError(f"评分或恢复核验失败，记录见 {output}")
    return report


def validate_loss(training: Any, datums: list[Any], batch_size: int) -> float:
    total = 0.0
    for start in range(0, len(datums), batch_size):
        batch = datums[start:start + batch_size]
        output = training.forward(batch, loss_fn="cross_entropy", auto_shift=False).result()
        if len(output.loss_fn_outputs) != len(batch):
            raise ValueError("验证集评分数量与提交样本数量不同")
        for loss_output in output.loss_fn_outputs:
            values = np.asarray(loss_output["logprobs"].to_numpy())
            if values.ndim != 1 or not values.size:
                raise ValueError("验证集答案 logprob 形状不完整")
            value = float(values[-1])
            if not math.isfinite(value) or value > 1e-5:
                raise ValueError("验证集答案 logprob 无效")
            total -= value
    return total / len(datums)


def train(
    api_key: str, base_model: str, dataset: Path, output: Path, name: str,
    calibration: dict[str, Any], rank: int = 32, learning_rate: float = 1e-4,
    batch_size: int = 16, epochs: int = 2, seed: int = 42, resume: bool = False,
) -> dict[str, Any]:
    if (calibration["status"] != "passed" or calibration["base_model"] != base_model
            or calibration["template_version"] != TEMPLATE_VERSION
            or calibration.get("scoring_mode") != SCORING_MODE):
        raise ValueError("训练前需要当前基座与模板的真实评分核验记录")
    if (rank < 4 or rank > 64 or batch_size < 1 or epochs < 1
            or not math.isfinite(learning_rate) or learning_rate <= 0):
        raise ValueError("训练参数不在有效范围")
    examples = read_jsonl(dataset / "train.jsonl")
    validation = read_jsonl(dataset / "validation.jsonl")
    test = read_jsonl(dataset / "test.jsonl")
    for group in (examples, validation, test):
        for sample in group:
            validate_sample(sample)
    groups = [{item["game_id"] for item in group} for group in (examples, validation, test)]
    if not all(groups) or any(groups[a] & groups[b] for a, b in ((0, 1), (0, 2), (1, 2))):
        raise ValueError("训练、验证、测试集必须非空且没有共享对局")
    calibration_ids = {sample["game_id"] for sample in calibration["samples"]}
    if not calibration_ids <= groups[0]:
        raise ValueError("评分校准样本必须来自本次训练集")
    identity = {
        "base_model": base_model, "rank": rank, "learning_rate": learning_rate,
        "batch_size": batch_size, "seed": seed, "template_version": TEMPLATE_VERSION,
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
    if resume:
        config = json.loads((output / "training-config.json").read_text())
        if any(config.get(key) != value for key, value in identity.items()):
            raise ValueError("续训需要原来的基座、训练配置与整盘数据划分")
        if json.loads((output / "dataset-manifest.json").read_text()) != dataset_manifest:
            raise ValueError("训练局面、标签、候选或顺序已经变化，不能沿用原优化器续训")
        history = json.loads((output / "training-history.json").read_text())
        if not history or [entry["epoch"] for entry in history] != list(range(1, len(history) + 1)):
            raise ValueError("续训需要连续且已完成的训练轮次记录")
        if epochs <= len(history):
            raise ValueError("epochs 为计划总轮数，须大于已完成轮数")
        checkpoint_path = history[-1]["state_path"]
    elif output.exists() and any(output.iterdir()):
        raise ValueError("输出目录已有产物；续训使用 --resume，新实验使用新目录")
    service = trio.ServiceClient(api_key=api_key)
    training = service.create_lora_training_client(base_model=base_model, rank=rank, seed=seed)
    if checkpoint_path:
        training.load_state_with_optimizer(checkpoint_path).result()
    tokenizer = training.get_tokenizer()
    if resume and tokenizer.chat_template != config["chat_template"]:
        raise ValueError("tokenizer 的聊天模板已经变化，不能沿用原编码续训")

    def datum(item: dict[str, Any]):
        encoded = encode_position(tokenizer, tuple(item["board"]), item["turn"])
        if tuple(item["candidates"]) != encoded.coordinates:
            raise ValueError("样本候选排列与训练编码不同")
        return training_datum(encoded, item["target"]), len(encoded.prefix)

    encoded_training = [datum(item) for item in examples]
    validation_datums = [datum(item)[0] for item in validation]
    lengths = [length for _, length in encoded_training]
    best = min(history, key=lambda entry: entry["validation_answer_loss"]) if history else None
    best_loss = best["validation_answer_loss"] if best else math.inf
    best_path = best["sampler_path"] if best else None
    start_epoch = len(history)
    invocation_id = uuid4().hex[:12]
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "dataset-manifest.json", dataset_manifest)
    write_json(output / "training-config.json", {
        **identity, "epochs": epochs, "resumed_from": checkpoint_path,
        "token_lengths": {"min": min(lengths), "max": max(lengths),
                          "p50": float(np.percentile(lengths, 50)),
                          "p95": float(np.percentile(lengths, 95)), "total": sum(lengths)},
        "packages": {package: importlib.metadata.version(package)
                     for package in ("pytrio", "transformers", "modelscope")},
        "tokenizer_name": tokenizer.name_or_path, "chat_template": tokenizer.chat_template,
        "calibration_model_path": calibration["model_path"],
    })
    for epoch in range(start_epoch, epochs):
        order = list(range(len(encoded_training)))
        random.Random(seed + epoch).shuffle(order)
        updates = []
        for start in range(0, len(order), batch_size):
            batch = [encoded_training[index][0] for index in order[start:start + batch_size]]
            output_forward = training.forward_backward(
                batch, loss_fn="cross_entropy", auto_shift=False,
            ).result()
            training.optim_step(trio.AdamParams(learning_rate=learning_rate)).result()
            updates.append({"batch": start // batch_size, "metrics": output_forward.metrics})
            write_json(output / f"epoch-{epoch + 1}-updates.json", updates)
            print(f"训练轮次 {epoch + 1}/{epochs}，批次 {len(updates)}/"
                  f"{(len(order) + batch_size - 1) // batch_size}", flush=True)
        loss = validate_loss(training, validation_datums, batch_size)
        checkpoint = training.save_state(
            name=f"{name}-{invocation_id}-epoch-{epoch + 1}", ttl_seconds=None,
        ).result()
        sampler = training.save_weights_for_sampler(
            name=f"{name}-{invocation_id}-policy-epoch-{epoch + 1}", ttl_seconds=None,
        ).result()
        history.append({"epoch": epoch + 1, "validation_answer_loss": loss,
                        "state_path": checkpoint.path, "sampler_path": sampler.path})
        if loss < best_loss:
            best_loss, best_path = loss, sampler.path
        write_json(output / "training-history.json", history)
    result = {"status": "trained-not-strength-verified", "artifact_kind": "trained-policy",
              "base_model": base_model, "model_path": best_path, "validation_loss": best_loss,
              "template_version": TEMPLATE_VERSION, "history": history}
    write_json(output / "adapter-metadata.json", result)
    return result
