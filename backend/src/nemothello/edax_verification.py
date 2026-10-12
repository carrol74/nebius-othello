from pathlib import Path
from typing import Any

from nemothello.data import write_json
from nemothello.edax import Edax
from nemothello.rules import Position


def verify_edax(edax: Edax, output: Path) -> dict[str, Any]:
    initial = Position()
    white, _ = initial.play("d3")
    endgame = Position((
        ".OXXXXXX", "XXXXXXXX", "XXXXXXXX", "XXXXXXXX",
        "XXXXXXXX", "XXXXXXXX", "XXXXXXXX", "XX.OXXXX",
    ), "X")
    after_pass, passed = endgame.play("a1")
    if passed != "O" or after_pass.turn != "X":
        raise ValueError("验证残局应在 a1 后由白方跳过、黑方继续行动")
    cases = (
        ("initial_black", initial), ("after_d3_white", white),
        ("forced_pass_endgame", endgame), ("after_forced_pass", after_pass),
    )
    report: dict[str, Any] = {
        "status": "running", "source": "live-edax-pipe",
        "executable": str(edax.executable), "eval_file": str(edax.eval_file),
        "engine_version": edax.version, "level": edax.level, "cases": [],
        "limits": "检查本地适配器与有限局面；不代表批量生成稳定性或棋力评测。",
    }
    try:
        write_json(output, report)
        process_id = None
        for name, position in cases:
            analysis = edax.analyze(position.board, position.turn)
            report["cases"].append({"name": name, "analysis": analysis})
            write_json(output, report)
            if process_id is None:
                process_id = edax.process.pid
                report["process_id"] = process_id
            if edax.process.pid != process_id:
                raise ValueError("连续分析应复用同一个 Edax 进程")
            if (analysis["board"] != list(position.board)
                    or analysis["turn"] != position.turn
                    or analysis["score_perspective"] != position.turn
                    or [item["coordinate"] for item in analysis["candidates"]]
                    != list(position.moves)):
                raise ValueError(f"{name} 的分析与规则引擎局面不一致")
            if name in ("forced_pass_endgame", "after_forced_pass"):
                for candidate in analysis["candidates"]:
                    terminal = position
                    while terminal.turn is not None:
                        move = (candidate["coordinate"] if terminal == position
                                else terminal.moves[0])
                        terminal, _ = terminal.play(move)
                    result = terminal.result()
                    score = result["black_count"] - result["white_count"]
                    if candidate["score_kind"] != "exact" or candidate["score"] != score:
                        raise ValueError(f"{name} 的残局精确分数与实际终局子差不一致")
        report["status"] = "passed"
        return report
    except Exception as exc:
        report.update(status="failed", error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        edax.close()
        write_json(output, report)
