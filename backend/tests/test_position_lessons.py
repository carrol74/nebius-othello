import json
from pathlib import Path

import pytest

from nemothello.coaching import review_context
from nemothello.edax import Edax
from nemothello.errors import AppError
from nemothello.games import Games, advance
from nemothello.opponents import EdaxOpponent
from nemothello.nemotron import Nemotron
from nemothello.position_lessons import check_teachable, lesson_context, position_at, previous_decision_revision
from nemothello.storage import Store
from nemothello.tasks import Tasks


@pytest.fixture
def saved_game():
    review = json.loads((Path(__file__).parent / "fixtures/review-native-positions.json").read_text())["review"]
    game = {"game_id": "native-game", "initial_board": review["initial_board"],
            "initial_turn": review["initial_turn"], "board": review["initial_board"],
            "turn": review["initial_turn"], "human_color": review["human_color"],
            "revision": 0, "history": [], "result": None}
    for event in review["history"]:
        if event["kind"] == "move":
            advance(game, event["coordinate"])
    assert game["result"] == review["result"]
    return game, review


def test_every_saved_position_can_be_revisited_including_passes(saved_game):
    game, _ = saved_game
    assert list(position_at(game, 0).board) == game["initial_board"]
    for event in game["history"]:
        position = position_at(game, event["revision"])
        assert list(position.board) == event["board"]
        assert position.turn == event["turn"]
        if event["kind"] == "pass":
            assert not position_at(game, event["revision"] - 1).moves
            assert position.moves


@pytest.mark.parametrize("human_color", ["X", "O"])
def test_teaching_only_accepts_own_decisions_including_after_passes(saved_game, human_color):
    source, _ = saved_game
    game = {**source, "human_color": human_color}
    for revision in range(game["revision"] + 1):
        position = position_at(game, revision)
        expected = ("REVIEW_TERMINAL" if position.turn is None else
                    "REVIEW_PASS" if not position.moves else
                    "REVIEW_OPPONENT" if position.turn != human_color else None)
        if expected:
            with pytest.raises(AppError) as error:
                check_teachable(game, revision)
            assert error.value.code == expected
        else:
            assert check_teachable(game, revision) == position


def test_requested_opponent_position_is_rejected_even_with_saved_evidence(saved_game):
    game, review = saved_game
    evidence = next(item for item in review["evidence"] if item["revision"] == 11)
    assert evidence["actor"] != game["human_color"]
    with pytest.raises(AppError) as error:
        review_context(lesson_context(game, evidence, []), None, revision=11)
    assert error.value.code == "REVIEW_OPPONENT"


def test_any_own_decision_can_be_taught_and_question_stays_on_that_position(saved_game):
    game, review = saved_game
    evidence = next(item for item in review["evidence"] if item["revision"] == 16)
    context = review_context(lesson_context(game, evidence, []), None, revision=16)
    assert [item["revision"] for item in context["positions"]] == [16]
    assert context["positions"][0]["human"]
    with pytest.raises(AppError) as error:
        review_context(lesson_context(game, evidence, []), "Explain position 11", revision=16)
    assert error.value.code == "REVIEW_POSITION"


def test_active_game_and_unplayed_choice_do_not_claim_an_outcome_or_recorded_move(saved_game):
    game, review = saved_game
    evidence = next(item for item in review["evidence"] if item["revision"] == 16)
    evidence = {**evidence, "is_played": False}
    context = review_context(lesson_context({**game, "result": None}, evidence, []), None, revision=16)
    assert not any(item["id"] == "result" for item in context["summary_facts"])
    decision = next(item for item in context["positions"][0]["facts"] if item["id"].endswith(":decision"))
    assert "no move has been recorded yet" in decision["text"]


@pytest.mark.parametrize("human_color", ["X", "O"])
def test_opponent_lesson_lookup_and_tasks_are_rejected_without_starting_analysis(saved_game, tmp_path, human_color):
    root = Path(__file__).resolve().parents[2]
    executable, weights = root / "deploy/edax/edax", root / "deploy/edax/eval.dat"
    if not executable.is_file() or not weights.is_file():
        pytest.skip("Native Edax and eval.dat are required")
    engine = Edax(executable, weights, "4.6", 4)
    store = Store(tmp_path / "games.sqlite3")
    games = Games(store, EdaxOpponent(engine), engine, 3)
    source, _ = saved_game
    game = {**source, "human_color": human_color}
    revision = next(event["revision"] - 1 for event in game["history"]
                    if event["kind"] == "move" and event["actor"] != human_color)
    with store.transaction() as db:
        store.save(db, "game", game["game_id"], "owner", game)
    with pytest.raises(AppError) as error:
        games.position_lesson("owner", game["game_id"], revision)
    assert error.value.code == "REVIEW_OPPONENT"
    for index, question in enumerate([None, "Why this move?"]):
        with pytest.raises(AppError) as error:
            games.create_position_lesson_task("owner", game["game_id"], f"request-{index}", revision, question)
        assert error.value.code == "REVIEW_OPPONENT"
    assert store.list_records("task", "owner") == []
    assert engine.process is None


@pytest.fixture
def forced_case():
    return json.loads((Path(__file__).parent / "fixtures/forced-move-native.json").read_text())


def test_native_forced_position_leads_back_to_last_real_choice(forced_case):
    game = forced_case["game"]
    assert position_at(game, 58).moves == ("d8",)
    assert previous_decision_revision(game, 58) == 42
    assert position_at(game, 42).moves == ("b3", "a4")
    replayed = {**game, "board": game["initial_board"], "turn": game["initial_turn"],
                "revision": 0, "history": [], "result": None}
    for event in game["history"]:
        if event["kind"] == "move":
            advance(replayed, event["coordinate"])
    assert replayed["board"] == game["board"] and replayed["result"] == game["result"]
    for event in game["history"]:
        before = event["revision"] - 1
        if 42 < before <= 58 and event["kind"] == "move" and event["actor"] == game["human_color"]:
            assert len(position_at(game, before).moves) == 1


def test_forced_lesson_is_factual_and_needs_no_model_credentials(forced_case):
    context = lesson_context(forced_case["game"], forced_case["evidence"], [])
    model = Nemotron("", "https://unused.invalid/v1", "")
    try:
        response = model.explain(context, revision=58)
        assert response["model_id"] is None and response["usage"] is None
        assert response["coaching"][0]["lesson_id"] == "forced_move"
        assert "only legal move" in response["text"] and "h8" in response["text"]
        assert "recommendation" not in response["text"]
    finally:
        model.close()


def test_real_forced_lesson_task_succeeds_without_model_and_returns_previous_choice(forced_case, tmp_path):
    root = Path(__file__).resolve().parents[2]
    executable, weights = root / "deploy/edax/edax", root / "deploy/edax/eval.dat"
    if not executable.is_file() or not weights.is_file():
        pytest.skip("Native Edax and eval.dat are required")
    engine = Edax(executable, weights, "4.6", 4)
    model = Nemotron("", "https://unused.invalid/v1", "")
    store = Store(tmp_path / "games.sqlite3")
    games = Games(store, EdaxOpponent(engine), engine, 3)
    tasks = Tasks(store, games, model)
    try:
        game = games.new_game("X")
        for event in forced_case["game"]["history"]:
            if event["kind"] == "move":
                advance(game, event["coordinate"])
        with store.transaction() as db:
            store.save(db, "game", game["game_id"], "owner", game)
        task = games.create_position_lesson_task("owner", game["game_id"], "forced-lesson", 58)
        tasks.process("owner", store.get("task", task["task_id"], "owner"))
        result = store.get("task", task["task_id"], "owner")
        assert result["status"] == "succeeded", result["error"]
        assert result["result"]["model_id"] is None and result["result"]["usage"] is None
        assert result["result"]["previous_decision_revision"] == 42
        assert games.position_lesson("owner", game["game_id"], 58)["previous_decision_revision"] == 42
        cached = store.get("lesson", f"{game['game_id']}:58", "owner")
        cached["comparison"].pop("insight")
        cached["comparison"].pop("reference_move")
        for choice in cached["comparison"]["choices"]:
            choice.pop("assessment")
        with store.transaction() as db:
            store.save(db, "lesson", f"{game['game_id']}:58", "owner", cached)
        engine.close()
        restored = games.position_lesson("owner", game["game_id"], 58)
        assert restored["comparison"]["choices"][0]["assessment"]["status"] == "forced"
        assert restored["comparison"]["insight"]["kind"] == "forced"
        assert engine.process is None
    finally:
        engine.close()
        model.close()
