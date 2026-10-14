import json

import pytest

from nemothello import match_evaluation
from nemothello.errors import AppError
from nemothello.evaluation import interval
from nemothello.rules import Position


class Engine:
    level = 2

    def analyze(self, board, turn):
        return {"recommended_move": Position(board, turn).moves[0]}


class Policy:
    def __init__(self, error=None):
        self.error = error

    def score(self, board, turn):
        if self.error:
            raise self.error
        return {"coordinate": Position(board, turn).moves[0], "elapsed_ms": 1,
                "input_tokens": 1, "output_tokens": 1}


def openings():
    # Real rules with deterministic test opponents verify bookkeeping, not model strength.
    p = Position()
    return [{"opening_id": "test", "moves": [], "board": list(p.board), "turn": p.turn}]


def test_invalid_generation_is_not_a_loss(tmp_path, monkeypatch):
    monkeypatch.setattr(match_evaluation, "create_policy", lambda *args: Policy(
        AppError("POLICY_ILLEGAL_OUTPUT", "invalid", 502)))
    report = match_evaluation.run_matches("", "base", "adapter", openings(), Engine(),
                                          tmp_path / "out.json", 42, interval, pilot=True)
    assert len(report["records"]) == 8
    assert all(r["status"] == "failed" and r["score"] is None and r["result"] is None
               for r in report["records"])
    assert report["summary"]["base_vs_random"]["losses"] == 0
    assert report["summary"]["base_vs_random"]["failure_rate"] == 1
    assert report["summary"]["paired_improvement_vs_random"]["score_rate_difference"] is None


def test_resume_keeps_completed_game_and_active_random_state(tmp_path, monkeypatch):
    output = tmp_path / "out.json"
    interrupted = False

    class InterruptOnce(Policy):
        def score(self, board, turn):
            nonlocal interrupted
            report = json.loads(output.read_text())
            if len(report["records"]) == 1 and not interrupted:
                interrupted = True
                raise RuntimeError("transport")
            return super().score(board, turn)

    monkeypatch.setattr(match_evaluation, "create_policy", lambda *args: InterruptOnce())
    with pytest.raises(RuntimeError, match="transport"):
        match_evaluation.run_matches("", "base", "adapter", openings(), Engine(),
                                     output, 42, interval, pilot=True)
    interrupted_report = json.loads(output.read_text())
    first = interrupted_report["records"][0]
    assert interrupted_report["status"] == "interrupted"
    assert interrupted_report["active_match"]["moves"]  # Opponent has played before failure.
    monkeypatch.setattr(match_evaluation, "create_policy", lambda *args: Policy())
    resumed = match_evaluation.run_matches("", "base", "adapter", openings(), Engine(),
                                          output, 42, interval, pilot=True, resume=True)
    fresh = match_evaluation.run_matches("", "base", "adapter", openings(), Engine(),
                                        tmp_path / "fresh.json", 42, interval, pilot=True)
    assert resumed["records"][0] == first
    assert len(resumed["records"]) == 8
    assert [r["moves"] for r in resumed["records"]] == [r["moves"] for r in fresh["records"]]
    assert resumed["summary"] == fresh["summary"]


def test_resume_rejects_changed_configuration_before_paid_calls(tmp_path, monkeypatch):
    output = tmp_path / "out.json"
    monkeypatch.setattr(match_evaluation, "create_policy", lambda *args: Policy())
    match_evaluation.run_matches("", "base", "adapter", openings(), Engine(),
                                 output, 42, interval, pilot=True)
    monkeypatch.setattr(match_evaluation, "create_policy", lambda *args: pytest.fail("paid call"))
    with pytest.raises(ValueError, match="恢复配置"):
        match_evaluation.run_matches("", "base", "other", openings(), Engine(),
                                     output, 42, interval, pilot=True, resume=True)
    with pytest.raises(ValueError, match="输出已存在"):
        match_evaluation.run_matches("", "base", "adapter", openings(), Engine(),
                                     output, 42, interval, pilot=True)


def test_selected_opponent_does_not_repeat_other_games(tmp_path, monkeypatch):
    monkeypatch.setattr(match_evaluation, "create_policy", lambda *args: Policy())
    output = tmp_path / "edax.json"
    engine = Engine()
    engine.level = 1
    report = match_evaluation.run_matches("", "base", "adapter", openings(), engine,
                                          output, 42, interval, pilot=True, opponents=("edax",))
    assert report["expected_games"] == 4
    assert len(report["records"]) == 4
    assert all(r["opponent"] == "edax" for r in report["records"])
    assert all("random" not in key for key in report["summary"])
    monkeypatch.setattr(match_evaluation, "create_policy", lambda *args: pytest.fail("paid call"))
    with pytest.raises(ValueError, match="恢复配置"):
        match_evaluation.run_matches("", "base", "adapter", openings(), Engine(),
                                     output, 42, interval, pilot=True, resume=True, opponents=("edax",))
    with pytest.raises(ValueError, match="恢复配置"):
        match_evaluation.run_matches("", "base", "adapter", openings(), engine,
                                     output, 42, interval, pilot=True, resume=True)
