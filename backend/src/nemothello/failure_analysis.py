import hashlib
import json
from pathlib import Path

import numpy as np

from nemothello.data import read_jsonl
from nemothello.rules import Position
from nemothello.training_recovery import atomic_json


def decision_positions(report):
    """Map saved model calls to real pre-move positions, including implicit passes."""
    openings = {o["opening_id"]: o for o in report["openings"]}
    for game in report["records"]:
        if game["policy"] != "trained" or game["status"] != "completed" or game["score"] != 0:
            continue
        opening = openings[game["opening_id"]]
        position = Position(tuple(opening["board"]), opening["turn"])
        decision_index = 0
        for offset, move in enumerate(game["moves"]):
            if position.turn == game["color"] and len(position.moves) > 1:
                decision = game["decisions"][decision_index]
                if (decision["coordinate"] != move
                        or decision["candidate_count"] != len(position.moves)):
                    raise ValueError("Saved model calls differ from the game history")
                yield {"opening_id": game["opening_id"], "color": game["color"],
                       "opponent": game["opponent"], "opponent_level": report["edax_level"],
                       "ply": len(opening["moves"]) + offset, "board": list(position.board),
                       "turn": position.turn, "candidates": list(position.moves),
                       "selected": move, "decision_index": decision_index}
                decision_index += 1
            position, _ = position.play(move)
        if (decision_index != len(game["decisions"]) or position.result() != game["result"]
                or list(position.board) != game["board"]):
            raise ValueError("Loss replay or call count is inconsistent")


def analyze_failures(sources: list[Path], dataset: Path, edax, output: Path, resume=False):
    identity = {"source_files": [{"path": str(p.resolve()),
                                  "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in sources],
                "dataset": str(dataset.resolve()), "teacher_level": edax.level,
                "dataset_hashes": {name: hashlib.sha256((dataset / f"{name}.jsonl").read_bytes()).hexdigest()
                                   for name in ("train", "validation", "test")},
                "scope": "Saved evaluation games remain quarantined; diagnostic evidence is not training data."}
    positions = []
    for path in sources:
        report = json.loads(path.read_text())
        if report["status"] != "completed":
            raise ValueError("Diagnosis requires a complete match report")
        positions.extend({"source": str(path.resolve()), **row} for row in decision_positions(report))
    if not positions:
        raise ValueError("Report has no fine-tuned model decisions from lost games to analyze")
    known = {name: {(tuple(row["board"]), row["turn"])
                    for row in read_jsonl(dataset / f"{name}.jsonl")}
             for name in ("train", "validation", "test")}
    if output.exists():
        if not resume:
            raise ValueError("Diagnosis output already exists. Resume explicitly; do not overwrite evidence")
        report = json.loads(output.read_text())
        if any(report.get(k) != v for k, v in identity.items()):
            raise ValueError("Diagnosis source or engine settings changed; cannot resume")
        for expected, recorded in zip(positions, report["records"], strict=False):
            if any(recorded.get(k) != v for k, v in expected.items()):
                raise ValueError("Saved diagnosis does not match the history position")
        if len(report["records"]) > len(positions):
            raise ValueError("Diagnosis record count exceeds the source count")
    else:
        if resume:
            raise ValueError("No diagnosis is available to resume")
        report = {**identity, "status": "running", "expected_positions": len(positions),
                  "records": [], "summary": {}, "quarantined_for_training": True}
    atomic_json(output, report)
    try:
        for row in positions[len(report["records"]):]:
            analysis = edax.analyze(tuple(row["board"]), row["turn"])
            candidates = analysis["candidates"]
            if ({c["coordinate"] for c in candidates} != set(row["candidates"])
                    or len(candidates) != len(row["candidates"])
                    or analysis["score_perspective"] != row["turn"]):
                raise ValueError("Teacher scores differ from the position's legal candidates")
            scores = {c["coordinate"]: c for c in candidates}
            selected = scores[row["selected"]]
            best = max(candidates, key=lambda c: c["score"])
            if not all(np.isfinite(c["score"]) for c in candidates):
                raise ValueError("Teacher scores must be complete and finite")
            empty = sum(r.count(".") for r in row["board"])
            key = (tuple(row["board"]), row["turn"])
            record = {**row, "stage": "opening" if empty >= 44 else "middle" if empty >= 20 else "end",
                      "best_move": best["coordinate"], "best_score": best["score"],
                      "selected_score": selected["score"], "teacher_score_loss": best["score"] - selected["score"],
                      "exact": best["score_kind"] == selected["score_kind"] == "exact",
                      "seen_in_splits": [name for name, keys in known.items() if key in keys],
                      "analysis": {k: v for k, v in analysis.items() if k != "raw_output"}}
            record["exact_win_to_loss"] = record["exact"] and best["score"] > 0 > selected["score"]
            report["records"].append(record)
            atomic_json(output, report)
            if len(report["records"]) % 20 == 0 or len(report["records"]) == len(positions):
                print(f"Loss labeling: {len(report['records'])}/{len(positions)}", flush=True)
    except Exception as error:
        report.update(status="interrupted", error_type=type(error).__name__)
        atomic_json(output, report)
        raise
    buckets = {"all": report["records"]}
    for stage in ("opening", "middle", "end"):
        buckets[stage] = [r for r in report["records"] if r["stage"] == stage]
    for level in sorted({r["opponent_level"] for r in report["records"]}):
        buckets[f"opponent_level_{level}"] = [r for r in report["records"] if r["opponent_level"] == level]
    for name, rows in buckets.items():
        if rows:
            report["summary"][name] = {
                "positions": len(rows), "best_score_agreement": sum(r["teacher_score_loss"] == 0 for r in rows) / len(rows),
                "mean_teacher_score_loss": float(np.mean([r["teacher_score_loss"] for r in rows])),
                "loss_at_least_4": sum(r["teacher_score_loss"] >= 4 for r in rows),
                "loss_at_least_8": sum(r["teacher_score_loss"] >= 8 for r in rows),
                "exact_positions": sum(r["exact"] for r in rows),
                "exact_win_to_loss": sum(r["exact_win_to_loss"] for r in rows),
                "seen_in_train": sum("train" in r["seen_in_splits"] for r in rows),
            }
    report["top_errors"] = sorted(report["records"], key=lambda r: r["teacher_score_loss"], reverse=True)[:20]
    report["status"] = "completed"
    report["limits"] = ("Only losing trajectories are included; no causal attribution to data distribution. "
                        "Unseen boards are normal in generalization and do not alone prove insufficient data. "
                        "Estimated and exact teacher scores are flagged separately; thresholds 4 and 8 are diagnostic buckets. "
                        "Evaluation positions must not enter training while these games remain a held-out benchmark.")
    atomic_json(output, report)
    return report
