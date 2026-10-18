import json
import os
from pathlib import Path

import pytest

from nemothello.coaching import REVIEW_VERSION
from nemothello.edax import Edax
from nemothello.games import Games, advance
from nemothello.nemotron import Nemotron
from nemothello.opponents import EdaxOpponent
from nemothello.schemas import Review, Task
from nemothello.storage import Store
from nemothello.tasks import Tasks


@pytest.mark.parametrize("human_color", ["X", "O"])
def test_real_analysis_survives_coaching_failure_and_retry_reuses_saved_engine_evidence(tmp_path, human_color):
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
        failed = Task.model_validate(store.get("task", first["task_id"], owner))
        assert failed.status == "failed" and failed.error["code"] == "REVIEW_NOT_CONFIGURED"
        saved = games.review(owner, game["game_id"])
        review = Review.model_validate(saved)
        assert review.format_version == REVIEW_VERSION and review.coaching_status == "failed"
        assert len(review.evidence) == sum(event["kind"] == "move" and event["actor"] == game["human_color"]
                                           for event in source["history"])
        assert all(item.actor == game["human_color"] for item in review.evidence)
        assert all(item.actor == human_color for item in review.key_moves)
        assert all(item["turn"] == human_color for item in engine.cache.values())
        assert len(review.key_moves) <= 3 and review.summary_facts
        assert all(item.comparisons for item in review.evidence)
        engine.close()
        second = games.create_review_task(owner, game["game_id"], "retry")
        assert second["task_id"] != first["task_id"]
        tasks.process(owner, second)
        assert engine.process is None
        assert games.review(owner, game["game_id"])["evidence"] == saved["evidence"]
        with store.transaction() as db:
            saved["coaching_status"] = "pending"
            second["status"] = "running"
            store.save(db, "review", game["game_id"], owner, saved)
            store.save(db, "task", second["task_id"], owner, second)
        store.recover_tasks()
        assert games.review(owner, game["game_id"])["coaching_status"] == "failed"
        assert store.get("task", second["task_id"], owner)["error"]["code"] == "SERVICE_RESTARTED"
    finally:
        engine.close()
        model.close()
