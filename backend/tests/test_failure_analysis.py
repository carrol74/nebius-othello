import json
from pathlib import Path

import pytest

from nemothello.failure_analysis import analyze_failures, decision_positions
from nemothello.rules import Position


def losing_report():
    # Deterministic rule trajectories test mapping and quarantine, not learned-model quality.
    position = Position()
    moves, before = [], []
    while position.turn:
        before.append((position.turn, position.moves))
        move = position.moves[0]
        moves.append(move)
        position, _ = position.play(move)
    color = "O" if position.result()["winner"] == "X" else "X"
    decisions = [{"coordinate": moves[i], "candidate_count": len(legal)}
                 for i, (turn, legal) in enumerate(before) if turn == color and len(legal) > 1]
    initial = Position()
    return {"status": "completed", "edax_level": 1,
            "openings": [{"opening_id": "test", "moves": [], "board": list(initial.board), "turn": "X"}],
            "records": [{"policy": "trained", "opponent": "edax", "status": "completed",
                         "score": 0, "color": color, "opening_id": "test", "moves": moves,
                         "decisions": decisions, "board": list(position.board), "result": position.result()}]}


def test_decisions_map_to_correct_pre_move_positions():
    report = losing_report()
    rows = list(decision_positions(report))
    game = report["records"][0]
    assert len(rows) == len(game["decisions"])
    for row in rows:
        position = Position(tuple(row["board"]), row["turn"])
        assert row["selected"] == game["moves"][row["ply"]]
        assert list(position.moves) == row["candidates"]
        assert row["turn"] == game["color"]


def test_mismatched_saved_decision_is_rejected():
    report = losing_report()
    report["records"][0]["decisions"][0]["coordinate"] = "h8"
    with pytest.raises(ValueError, match="calls differ from the game history"):
        list(decision_positions(report))


def test_interruption_preserves_real_teacher_evidence_and_quarantine(tmp_path):
    report = losing_report()
    source = tmp_path / "matches.json"
    source.write_text(json.dumps(report))
    dataset = tmp_path / "data"
    dataset.mkdir()
    for name in ("train", "validation", "test"):
        (dataset / f"{name}.jsonl").write_text("")
    fixture = Path(__file__).parent / "fixtures/edax-4.6-macos-adapter-check.json"
    measured = json.loads(fixture.read_text())["cases"][0]["analysis"]
    first = next(decision_positions(report))
    assert first["board"] == measured["board"]

    class Engine:
        level = 8
        calls = 0

        def analyze(self, board, turn):
            self.calls += 1
            if self.calls > 1:
                raise RuntimeError("engine stopped")
            return measured

    output = tmp_path / "analysis.json"
    with pytest.raises(RuntimeError, match="engine stopped"):
        analyze_failures([source], dataset, Engine(), output)
    saved = json.loads(output.read_text())
    assert saved["status"] == "interrupted"
    assert len(saved["records"]) == 1
    assert saved["records"][0]["analysis"]["candidates"] == measured["candidates"]
    assert saved["records"][0]["teacher_score_loss"] == 0
    assert saved["quarantined_for_training"] is True
    with pytest.raises(ValueError, match="output already exists"):
        analyze_failures([source], dataset, Engine(), output)
    (dataset / "train.jsonl").write_text('{"board":[],"turn":"X"}\n')
    with pytest.raises(ValueError, match="source or engine settings"):
        analyze_failures([source], dataset, Engine(), output, resume=True)
