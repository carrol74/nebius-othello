import json
import os
from pathlib import Path

import pytest

from nemothello.coaching import REVIEW_VERSION
from nemothello.edax import Edax
from nemothello.game_summary import SUMMARY_VERSION
from nemothello.games import Games, advance
from nemothello.nemotron import Nemotron
from nemothello.opponents import EdaxOpponent
from nemothello.rules import apply_move, legal_moves, opponent
from nemothello.schemas import GameSummary, ReviewSummary, Task
from nemothello.storage import Store
from nemothello.tasks import Tasks
from nemothello.teaching import compare_lesson


@pytest.mark.parametrize("human_color", ["X", "O"])
def test_engine_review_needs_no_model_and_retry_reuses_saved_evidence(tmp_path, human_color):
    root = Path(__file__).resolve().parents[2]
    executable = Path(os.environ.get("TEST_EDAX_EXECUTABLE", root / "deploy/edax/edax"))
    weights = Path(os.environ.get("TEST_EDAX_EVAL_FILE", root / "deploy/edax/eval.dat"))
    if not executable.is_file() or not weights.is_file():
        pytest.skip("Native Edax and eval.dat are required")
    engine = Edax(executable, weights, "4.6", 4)
    model = Nemotron("", "https://unused.invalid/v1", "")
    store = Store(tmp_path / "games.sqlite3")
    games = Games(store, EdaxOpponent(engine), engine, 3)
    tasks = Tasks(store, games, model)
    source = json.loads((Path(__file__).parent / "fixtures/review-native-positions.json").read_text())["review"]
    owner = "native-review-test"
    try:
        game = games.new_game(human_color)
        for event in source["history"]:
            if event["kind"] == "move":
                game = advance(game, event["coordinate"])
        assert game["result"] == source["result"]
        with store.transaction() as db:
            store.save(db, "game", game["game_id"], owner, game)
        first = games.create_review_task(owner, game["game_id"], "first")
        assert games.create_review_task(owner, game["game_id"], "same-running")["task_id"] == first["task_id"]
        tasks.process(owner, first)
        done = Task.model_validate(store.get("task", first["task_id"], owner))
        assert done.status == "succeeded"
        summary = ReviewSummary.model_validate(games.review(owner, game["game_id"]))
        assert summary.model_dump() == done.result.model_dump()
        stored = store.get("review", game["game_id"], owner)
        assert stored["format_version"] == REVIEW_VERSION
        assert len(stored["evidence"]) == sum(event["kind"] == "move" and event["actor"] == game["human_color"]
                                              for event in source["history"])
        assert all(item["actor"] == human_color for item in stored["evidence"])
        for item in stored["evidence"]:
            board, actor = tuple(item["analysis"]["board"]), item["actor"]
            answered = {move for move in legal_moves(board, actor)
                        if legal_moves(apply_move(board, actor, move), opponent(actor))}
            assert set(item["opponent_replies"]) == answered
            assert all(reply in legal_moves(apply_move(board, actor, move), opponent(actor))
                       for move, reply in item["opponent_replies"].items())
        assert len(summary.key_moves) <= 3
        evidence = {item["revision"]: item for item in stored["evidence"]}
        assert all(evidence[move.revision]["actual_move"] == move.actual_move
                   and evidence[move.revision]["score_loss"] >= 4 for move in summary.key_moves)
        assert all(item["comparisons"] for item in stored["evidence"])
        assert games.create_review_task(owner, game["game_id"], "again")["task_id"] == first["task_id"]
        revision = max(stored["evidence"], key=lambda item: item["score_loss"])["revision"]
        lesson = games.position_lesson(owner, game["game_id"], revision)
        assert lesson["coaching_status"] == "not_requested" and lesson["comparison"]["choices"]
        assert lesson["evidence"] == evidence[revision]
        assert not store.list_records("lesson", owner)
        for move in summary.key_moves:
            item = evidence[move.revision]
            reason = compare_lesson({"evidence": [item]}, move.revision, move.actual_move)["reason"]
            assert (move.reason.model_dump() if move.reason else None) == reason
        assert games.summary(owner, game["game_id"], "zh") == {"task": None}
        queued = games.create_summary_task(owner, game["game_id"], "summary-first", "zh")
        assert games.create_summary_task(owner, game["game_id"], "summary-again", "zh")["task_id"] == queued["task_id"]
        tasks.process(owner, store.get("task", queued["task_id"], owner))
        failed = Task.model_validate(store.get("task", queued["task_id"], owner))
        assert failed.status == "failed" and failed.error["code"] == "REVIEW_NOT_CONFIGURED"
        saved = GameSummary.model_validate(games.summary(owner, game["game_id"], "zh"))
        assert (saved.status, saved.error_code, saved.text) == ("failed", "REVIEW_NOT_CONFIGURED", None)
        assert games.summary(owner, game["game_id"], "en") == {"task": None}
        with store.transaction() as db:
            legacy = store.get("summary", f"{game['game_id']}:zh", owner, db)
            legacy.pop("format_version")
            store.save(db, "summary", f"{game['game_id']}:zh", owner, legacy)
        assert games.summary(owner, game["game_id"], "zh") == {"task": None}
        assert games.saved_review(owner, game["game_id"]) == stored
        retry = games.create_summary_task(owner, game["game_id"], "summary-retry", "zh")
        assert retry["task_id"] != queued["task_id"]
        with store.transaction() as db:
            interrupted = store.get("task", retry["task_id"], owner, db)
            interrupted["status"] = "running"
            store.save(db, "task", retry["task_id"], owner, interrupted)
            document = saved.model_dump()
            document.update(task_id=retry["task_id"], status="pending", error=None, error_code=None,
                            format_version=SUMMARY_VERSION)
            store.save(db, "summary", f"{game['game_id']}:zh", owner, document)
        store.recover_tasks()
        recovered = GameSummary.model_validate(games.summary(owner, game["game_id"], "zh"))
        assert recovered.status == "failed" and recovered.error_code == "SERVICE_RESTARTED"
        resumed = games.create_summary_task(owner, game["game_id"], "summary-after-restart", "zh")
        assert resumed["task_id"] != retry["task_id"] and resumed["status"] == "queued"
    finally:
        engine.close()
        model.close()
