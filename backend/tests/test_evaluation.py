import json
from copy import deepcopy
from pathlib import Path

import pytest

from nemothello import evaluation
from nemothello.data import write_jsonl
from nemothello.errors import AppError
from nemothello.rules import Position


def dataset(tmp_path):
    # Recorded engine scores; policy stubs below test failure accounting, not chess strength.
    fixture = Path(__file__).parent / "fixtures/edax-4.6-macos-adapter-check.json"
    analysis = json.loads(fixture.read_text())["cases"][0]["analysis"]
    root = tmp_path / "dataset"
    root.mkdir()
    for split in ("train", "validation", "test"):
        sample = {
            "game_id": split, "board": analysis["board"], "turn": analysis["turn"],
            "candidates": list(Position(tuple(analysis["board"]), analysis["turn"]).moves),
            "target": analysis["recommended_move"], "analysis": analysis,
        }
        write_jsonl(root / f"{split}.jsonl", [
            {**deepcopy(sample), "ply": ply} for ply in range(3 if split == "test" else 1)
        ])
    return root


class Decisions:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)

    def score(self, board, turn):
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return {"coordinate": outcome}


def test_illegal_generations_have_no_score_and_no_unmatched_pair(tmp_path, monkeypatch):
    root = dataset(tmp_path)
    illegal = AppError("POLICY_ILLEGAL_OUTPUT", "invalid symbol", 502, True)
    policies = {
        None: Decisions(["d3", illegal, illegal]),
        "adapter": Decisions([illegal, "d3", "d3"]),
    }
    monkeypatch.setattr(evaluation, "create_policy", lambda key, base, path, mode: policies[path])
    report = evaluation.evaluate_positions("", "base", "adapter", root, tmp_path / "out.json", 42)
    invalid = [row for row in report["records"] if not row["legal"]]
    assert len(invalid) == 3
    assert all(row["selected"] is None and row["teacher_score_loss"] is None for row in invalid)
    assert report["summary"]["base_all"]["legal_rate"] == pytest.approx(1 / 3)
    assert report["summary"]["trained_all"]["legal_rate"] == pytest.approx(2 / 3)
    assert report["summary"]["base_all"]["valid_score_positions"] == 1
    assert report["paired_teacher_score_loss"] == {
        "trained_minus_base": None, "ci95_by_game": None, "game_groups": 0,
        "paired_valid_positions": 0, "excluded_positions": 3,
    }
    assert report["status"] == "completed"


def test_transport_failure_preserves_confirmed_results(tmp_path, monkeypatch):
    root = dataset(tmp_path)
    policies = {None: Decisions(["d3"]), "adapter": Decisions([RuntimeError("transport")])}
    monkeypatch.setattr(evaluation, "create_policy", lambda key, base, path, mode: policies[path])
    output = tmp_path / "out.json"
    with pytest.raises(RuntimeError, match="transport"):
        evaluation.evaluate_positions("", "base", "adapter", root, output, 42)
    report = json.loads(output.read_text())
    assert report["status"] == "failed"
    assert report["error_type"] == "RuntimeError"
    assert len(report["records"]) == 1
    assert report["records"][0]["policy"] == "base"


def test_existing_evidence_cannot_be_overwritten(tmp_path, monkeypatch):
    output = tmp_path / "out.json"
    output.write_text("original evidence")

    def forbidden(*args):
        pytest.fail("No paid client may be created when evidence already exists")

    monkeypatch.setattr(evaluation, "create_policy", forbidden)
    with pytest.raises(ValueError, match="Evaluation output already exists"):
        evaluation.evaluate_positions("", "base", "adapter", tmp_path / "missing", output, 42)
    assert output.read_text() == "original evidence"
