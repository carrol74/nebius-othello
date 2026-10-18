import json
from pathlib import Path

import pytest

from nemothello.coaching import review_context
from nemothello.errors import AppError
from nemothello.games import advance
from nemothello.position_lessons import check_teachable, lesson_context, position_at


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
            with pytest.raises(AppError) as error:
                check_teachable(game, event["revision"] - 1)
            assert error.value.code == "REVIEW_PASS"
            assert check_teachable(game, event["revision"]).moves
    with pytest.raises(AppError) as error:
        check_teachable(game, game["revision"])
    assert error.value.code == "REVIEW_TERMINAL"


def test_requested_opponent_position_is_not_filtered_to_three_human_decisions(saved_game):
    game, review = saved_game
    evidence = next(item for item in review["evidence"] if item["revision"] == 11)
    assert evidence["actor"] != game["human_color"]
    context = review_context(lesson_context(game, evidence, []), None, revision=11)
    assert [item["revision"] for item in context["positions"]] == [11]
    assert not context["positions"][0]["human"]
    with pytest.raises(AppError) as error:
        review_context(lesson_context(game, evidence, []), "Explain position 16", revision=11)
    assert error.value.code == "REVIEW_POSITION"


def test_active_game_and_unplayed_choice_do_not_claim_an_outcome_or_recorded_move(saved_game):
    game, review = saved_game
    evidence = next(item for item in review["evidence"] if item["revision"] == 16)
    evidence = {**evidence, "is_played": False}
    context = review_context(lesson_context({**game, "result": None}, evidence, []), None, revision=16)
    assert not any(item["id"] == "result" for item in context["summary_facts"])
    decision = next(item for item in context["positions"][0]["facts"] if item["id"].endswith(":decision"))
    assert "no move has been recorded yet" in decision["text"]
