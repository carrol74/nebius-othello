import json
import random
from collections import Counter
from pathlib import Path

import numpy as np

from nemothello.errors import AppError
from nemothello.policy import GENERATION_MODE, create_policy
from nemothello.rules import Position, replay
from nemothello.training_recovery import atomic_json


def summarize_matches(report, interval):
    summary = {}
    for name in ("base", "trained"):
        for opponent in report.get("opponents", ("random", "edax")):
            rows = [r for r in report["records"] if r["policy"] == name and r["opponent"] == opponent]
            completed = [r for r in rows if r["status"] == "completed"]
            groups = [[r for r in completed if r["opening_id"] == o["opening_id"]]
                      for o in report["openings"]]
            pairs = [float(np.mean([r["score"] for r in g])) for g in groups if len(g) == 2]
            decisions = [d for r in rows for d in r["decisions"]]
            times = [d["elapsed_ms"] for d in decisions]
            summary[f"{name}_vs_{opponent}"] = {
                "attempted_games": len(rows), "completed_games": len(completed),
                "failed_games": len(rows) - len(completed),
                "failure_rate": (len(rows) - len(completed)) / len(rows) if rows else None,
                "failure_types": dict(Counter(r["failure"]["kind"] for r in rows if r["status"] == "failed")),
                "wins": sum(r["score"] == 1 for r in completed),
                "draws": sum(r["score"] == 0.5 for r in completed),
                "losses": sum(r["score"] == 0 for r in completed),
                "complete_color_pairs": len(pairs),
                "score_rate_complete_pairs": float(np.mean(pairs)) if pairs else None,
                "score_rate_ci95": interval(pairs, report["seed"]) if len(pairs) >= 2 else None,
                "decision_p50_ms": float(np.percentile(times, 50)) if times else None,
                "decision_p95_ms": float(np.percentile(times, 95)) if times else None,
                "successful_input_tokens": sum(d["input_tokens"] for d in decisions),
                "successful_output_tokens": sum(d.get("output_tokens", 0) for d in decisions),
            }
    for opponent in report.get("opponents", ("random", "edax")):
        differences = []
        for opening in report["openings"]:
            rows = [r for r in report["records"] if r["opening_id"] == opening["opening_id"]
                    and r["opponent"] == opponent and r["status"] == "completed"]
            if len(rows) == 4:
                scores = {n: np.mean([r["score"] for r in rows if r["policy"] == n])
                          for n in ("base", "trained")}
                differences.append(float(scores["trained"] - scores["base"]))
        summary[f"paired_improvement_vs_{opponent}"] = {
            "complete_opening_groups": len(differences),
            "excluded_opening_groups": len(report["openings"]) - len(differences),
            "score_rate_difference": float(np.mean(differences)) if differences else None,
            "ci95": interval(differences, report["seed"]) if len(differences) >= 2 else None,
        }
    report["summary"] = summary


def run_matches(api_key, base_model, model_path, openings, edax, output: Path, seed,
                interval, mode=GENERATION_MODE, pilot=False, resume=False,
                opponents=("random", "edax")):
    if (not opponents or len(set(opponents)) != len(opponents)
            or set(opponents) - {"random", "edax"}):
        raise ValueError("对手必须是不同的 random 或 edax")
    if ((len(openings) != 40 and not pilot) or (pilot and not 1 <= len(openings) <= 40)
            or len({o["opening_id"] for o in openings}) != len(openings)):
        raise ValueError("正式评测需要四十组开局；试验需显式 pilot 并使用不同开局")
    for opening in openings:
        position = replay(opening["moves"])
        if list(position.board) != opening["board"] or position.turn != opening["turn"]:
            raise ValueError("共享开局的棋盘与棋谱不一致")
    identity = {"base_model": base_model, "model_path": model_path, "policy_mode": mode,
                "seed": seed, "edax_level": edax.level, "openings": openings, "pilot": pilot,
                "protocol_version": "matches-v2", "opponents": list(opponents),
                "expected_games": len(openings) * 4 * len(opponents)}
    schedule = [(name, opponent, index, color) for name in ("base", "trained")
                for opponent in opponents for index in range(len(openings))
                for color in ("X", "O")]
    if output.exists():
        if not resume:
            raise ValueError("评测输出已存在，需显式 resume，不能覆盖证据")
        report = json.loads(output.read_text())
        report.setdefault("opponents", ["random", "edax"])
        if any(report.get(k) != v for k, v in identity.items()):
            raise ValueError("恢复配置与原对弈报告不一致")
        for i, row in enumerate(report["records"]):
            n, o, index, color = schedule[i]
            if (row["policy"], row["opponent"], row["opening_id"], row["color"]) != (
                n, o, openings[index]["opening_id"], color,
            ) or row["status"] not in ("completed", "failed"):
                raise ValueError("恢复记录不是已确认的连续对局")
        if report["status"] == "completed":
            return report
    else:
        if resume:
            raise ValueError("缺少可恢复的对弈报告")
        report = {**identity, "status": "running", "records": [], "active_match": None,
                  "summary": {}, "limits": "失败无胜负分；统计仅含完整对局／完整换色组，必须同时报告失败率。"
                  "试验不证明棋力；客户端耗时和成功响应 token 不是端到端延迟或完整账单。"}
    report["status"] = "running"
    atomic_json(output, report)
    policies = {"base": create_policy(api_key, base_model, None, mode),
                "trained": create_policy(api_key, base_model, model_path, mode)}
    for name, opponent, index, color in schedule[len(report["records"]):]:
        opening = openings[index]
        active = report.get("active_match")
        if active is None:
            position = Position(tuple(opening["board"]), opening["turn"])
            rng = random.Random(seed + index)
            active = {"policy": name, "opponent": opponent, "opening_id": opening["opening_id"],
                      "color": color, "moves": [], "decisions": [], "rng_state": rng.getstate(),
                      "board": list(position.board), "turn": position.turn}
        else:
            if (active["policy"], active["opponent"], active["opening_id"], active["color"]) != (
                name, opponent, opening["opening_id"], color,
            ):
                raise ValueError("活动对局与恢复进度不一致")
            position = replay(active["moves"], Position(tuple(opening["board"]), opening["turn"]))
            if list(position.board) != active["board"] or position.turn != active["turn"]:
                raise ValueError("活动棋谱回放不一致")
            state = active["rng_state"]
            rng = random.Random()
            rng.setstate((state[0], tuple(state[1]), state[2]))
        report["active_match"] = active
        atomic_json(output, report)
        failure = None
        stage = "rules"
        try:
            while position.turn:
                stage = "rules"
                if len(position.moves) == 1:
                    move = position.moves[0]
                elif position.turn == color:
                    stage = "policy"
                    decision = policies[name].score(position.board, position.turn)
                    move = decision["coordinate"]
                    if move not in position.moves:
                        raise AppError("POLICY_ILLEGAL_OUTPUT", "非法模型落点", 502)
                    active["decisions"].append(decision)
                elif opponent == "random":
                    move = rng.choice(position.moves)
                else:
                    stage = "engine"
                    move = edax.analyze(position.board, position.turn)["recommended_move"]
                position, _ = position.play(move)
                active["moves"].append(move)
                active.update(board=list(position.board), turn=position.turn, rng_state=rng.getstate())
                atomic_json(output, report)
        except Exception as error:
            invalid = isinstance(error, AppError) and error.code in (
                "POLICY_ILLEGAL_OUTPUT", "POLICY_OUTPUT_SHAPE",
            )
            failure = {"kind": "invalid_output" if invalid else "engine_error" if stage == "engine"
                       else "policy_error" if stage == "policy" else "rules_error",
                       "error_type": type(error).__name__, "error_code": getattr(error, "code", None),
                       "stage": stage}
            if not invalid:
                # Keep the active trajectory and stop; a fresh process can resume this move.
                active.setdefault("interruptions", []).append(failure)
                report["status"] = "interrupted"
                summarize_matches(report, interval)
                atomic_json(output, report)
                raise
        result = position.result() if failure is None else None
        score = (0.5 if result["winner"] == "draw" else float(result["winner"] == color)) if result else None
        active.pop("rng_state")
        active.update(status="failed" if failure else "completed", result=result, score=score)
        if failure:
            active["failure"] = failure
        report["records"].append(active)
        report["active_match"] = None
        summarize_matches(report, interval)
        atomic_json(output, report)
        print(f"对弈 {len(report['records'])}/{len(schedule)}：{name} vs {opponent} "
              f"{opening['opening_id']} {color} {active['status']} score={score}", flush=True)
    report["status"] = "completed"
    atomic_json(output, report)
    return report
