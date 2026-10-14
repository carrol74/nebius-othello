import random
from pathlib import Path
from typing import Any

import numpy as np

from nemothello.data import read_jsonl, write_json
from nemothello.edax import Edax
from nemothello.errors import AppError
from nemothello.policy import GENERATION_MODE, SCORING_MODE, create_policy
from nemothello.rules import Position


def interval(groups: list[float], seed: int) -> list[float]:
    rng = np.random.default_rng(seed)
    samples = rng.choice(groups, size=(10000, len(groups)), replace=True).mean(axis=1)
    return [float(np.percentile(samples, 2.5)), float(np.percentile(samples, 97.5))]


def evaluate_positions(
    api_key: str, base_model: str, model_path: str, dataset: Path,
    output: Path, seed: int, limit: int = 200, equivalent_margin: float = 1,
    mode: str = GENERATION_MODE,
) -> dict[str, Any]:
    if output.exists():
        raise ValueError("评测输出已存在，请使用新文件保留原始证据")
    if limit < 1 or not np.isfinite(equivalent_margin) or equivalent_margin < 0:
        raise ValueError("评测数量须为正，近似等价容差不能为负")
    splits = {name: read_jsonl(dataset / f"{name}.jsonl")
              for name in ("train", "validation", "test")}
    ids = {name: {r["game_id"] for r in rows} for name, rows in splits.items()}
    if any(not rows for rows in splits.values()) or any(
        ids[a] & ids[b] for a, b in (("train", "validation"), ("train", "test"),
                                    ("validation", "test"))
    ):
        raise ValueError("评测需要非空且整盘互斥的三组数据")
    samples = list(splits["test"])
    random.Random(seed).shuffle(samples)
    samples = samples[:limit]
    # Validate all evidence before starting paid model requests.
    for sample in samples:
        position = Position(tuple(sample["board"]), sample["turn"])
        analysis = sample["analysis"]
        candidates = analysis["candidates"]
        coordinates = [c["coordinate"] for c in candidates]
        if (len(position.moves) < 2 or sample["candidates"] != list(position.moves)
                or set(coordinates) != set(position.moves) or len(coordinates) != len(position.moves)
                or analysis["board"] != sample["board"] or analysis["turn"] != position.turn
                or analysis["score_perspective"] != position.turn):
            raise ValueError("测试局面或完整老师评分与合法点不一致")
        scores = {c["coordinate"]: float(c["score"]) for c in candidates}
        if any(not np.isfinite(v) for v in scores.values()) or scores[sample["target"]] != max(scores.values()):
            raise ValueError("老师目标与实际候选分数不一致")
    policies = {"base": create_policy(api_key, base_model, None, mode),
                "trained": create_policy(api_key, base_model, model_path, mode)}
    records: list[dict[str, Any]] = []
    report = {"status": "running", "dataset": str(dataset.resolve()), "seed": seed,
              "base_model": base_model, "model_path": model_path,
              "policy_mode": mode,
              "available_test_positions": len(splits["test"]), "requested_limit": limit,
              "equivalent_margin": equivalent_margin, "records": records, "summary": {}}
    write_json(output, report)
    for sample_index, sample in enumerate(samples):
        scores = {c["coordinate"]: float(c["score"]) for c in sample["analysis"]["candidates"]}
        best = max(scores.values())
        empties = sum(row.count(".") for row in sample["board"])
        stage = "opening" if empties >= 44 else "middle" if empties >= 20 else "end"
        for name, policy in policies.items():
            try:
                decision = policy.score(tuple(sample["board"]), sample["turn"])
                move = decision["coordinate"]
                if (move not in scores or (mode == SCORING_MODE
                                          and set(decision["scores"]) != set(scores))):
                    raise ValueError("模型落子或候选评分不合法")
            except AppError as error:
                if mode != GENERATION_MODE or error.code not in (
                    "POLICY_ILLEGAL_OUTPUT", "POLICY_OUTPUT_SHAPE",
                ):
                    report.update(status="failed", error_type=type(error).__name__)
                    write_json(output, report)
                    raise
                # Invalid generation is evidence, not a replacement move or invented score.
                decision, move = {"error_code": error.code}, None
            except Exception as error:
                report.update(status="failed", error_type=type(error).__name__)
                write_json(output, report)
                raise
            legal = move is not None
            regret = best - scores[move] if legal else None
            records.append({"policy": name, "game_id": sample["game_id"], "ply": sample["ply"],
                            "stage": stage, "candidate_count": len(scores),
                            "legal": legal,
                            "target": sample["target"], "selected": move,
                            "target_agreement": move == sample["target"],
                            "best_score_agreement": regret == 0,
                            "approximately_equivalent": legal and regret <= equivalent_margin,
                            "teacher_score_loss": regret, "decision": decision,
                            "analysis_settings": sample["analysis"]["settings"]})
            write_json(output, report)
        print(f"局面对照：{sample_index + 1}/{len(samples)}", flush=True)
    for name in policies:
        group = [r for r in records if r["policy"] == name]
        buckets = {"all": group}
        buckets.update({f"stage_{stage}": [r for r in group if r["stage"] == stage]
                        for stage in ("opening", "middle", "end")})
        buckets.update({f"candidates_{count}": [r for r in group if r["candidate_count"] == count]
                        for count in sorted({r["candidate_count"] for r in group})})
        for key, rows in buckets.items():
            if not rows:
                continue
            report["summary"][f"{name}_{key}"] = {
                "positions": len(rows), "games": len({r["game_id"] for r in rows}),
                "legal_rate": float(np.mean([r["legal"] for r in rows])),
                "valid_score_positions": sum(r["legal"] for r in rows),
                "target_agreement_rate": float(np.mean([r["target_agreement"] for r in rows])),
                "best_score_agreement_rate": float(np.mean([r["best_score_agreement"] for r in rows])),
                "approximately_equivalent_rate": float(np.mean([r["approximately_equivalent"] for r in rows])),
                "mean_teacher_score_loss": float(np.mean([
                    r["teacher_score_loss"] for r in rows if r["legal"]
                ])) if any(r["legal"] for r in rows) else None,
            }
    paired = {}
    for row in records:
        paired.setdefault((row["game_id"], row["ply"]), {})[row["policy"]] = row
    comparable = [pair for pair in paired.values() if all(pair[name]["legal"] for name in policies)]
    game_ids = sorted({pair["base"]["game_id"] for pair in comparable})
    differences = [
        np.mean([pair["trained"]["teacher_score_loss"] - pair["base"]["teacher_score_loss"]
                 for pair in comparable if pair["base"]["game_id"] == game_id])
        for game_id in game_ids
    ]
    report["paired_teacher_score_loss"] = {
        "trained_minus_base": float(np.mean(differences)) if differences else None,
        "ci95_by_game": interval(differences, seed) if differences else None,
        "game_groups": len(game_ids), "paired_valid_positions": len(comparable),
        "excluded_positions": len(paired) - len(comparable),
    }
    report["status"] = "completed"
    report["limits"] = ("仅衡量固定老师设置的选点一致性与评分损失；棋力需独立对弈评测。"
                        "近似等价不表示真实等价或必胜。平均损失只含合法输出，配对差异只含双方均合法的局面；"
                        "非法输出单列合法率，不补造分数。")
    write_json(output, report)
    return report


def evaluate(
    api_key: str, base_model: str, model_path: str, openings: list[dict[str, Any]],
    edax: Edax, output: Path, seed: int, mode: str = GENERATION_MODE,
    pilot: bool = False, resume: bool = False,
    opponents: tuple[str, ...] = ("random", "edax"),
    baseline_model_path: str | None = None,
) -> dict[str, Any]:
    from nemothello.match_evaluation import run_matches

    return run_matches(api_key, base_model, model_path, openings, edax, output,
                       seed, interval, mode, pilot, resume, opponents, baseline_model_path)
