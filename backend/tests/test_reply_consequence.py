import json
from copy import deepcopy
from pathlib import Path

import pytest

from nemothello.coaching import TEXT_LIMITS, verified_teaching_facts
from nemothello.learning_goal import learning_goal, mechanism_text
from nemothello.rules import apply_move, coordinate, legal_moves, opponent, square
from nemothello.schemas import TeachingComparison
from nemothello.teaching import compare_lesson

FIXTURE = json.loads((Path(__file__).parent / "fixtures/reply-consequence-native.json").read_text())


def test_shared_searched_reply_explains_a_consequence_beyond_reply_legality():
    item = FIXTURE["evidence"]
    comparison = compare_lesson({"evidence": [item]}, item["revision"], item["actual_move"])
    assert comparison == FIXTURE["comparison"]
    TeachingComparison.model_validate(comparison)
    contrast = comparison["decision_contrast"]
    assert contrast["removed_reply"]["coordinate"] == "c3"
    assert comparison["reason"]["kind"] == "reply_consequence"
    consequence = contrast["consequence"]
    assert consequence["reply"] == "f4"
    searched_replies = FIXTURE["reply_search"][0]["replies"]
    assert max(searched_replies, key=lambda reply: reply["score"])["coordinate"] == "f4"
    assert consequence["actual_moves"] == ["g2", "g3", "g4", "g5", "g6", "g7"]
    for choice in comparison["choices"]:
        move = choice["coordinate"]
        assert choice["target"] == ("e3" if move == "c5" else None)
        assert [frame["coordinate"] for frame in choice["frames"]] == [None, move, "f4"]
        native = FIXTURE["native_after_reply"][move]
        assert choice["frames"][2]["board"] == native["board"]
        actual_moves = set(legal_moves(tuple(native["board"]), item["actor"]))
        assert actual_moves == {candidate["coordinate"] for candidate in native["candidates"]}
    goal = learning_goal(comparison)
    assert goal["actor"] == "you" and goal["after_same_moves"] == ["f4"]
    assert goal["changes"] == [{"square": "d4", "available": "opponent's", "alternative": "yours"}]
    assert goal["reply"] == "e3" and goal["anchor"] == "c5"
    assert comparison["reason"]["frame"] == 2
    assert comparison["reason"]["marks"]["d3"] == consequence["actual_moves"]
    assert comparison["reason"]["marks"]["c5"] == ["e3", "d4", "c5"]
    alternative = tuple(FIXTURE["native_after_reply"]["c5"]["board"])
    played = tuple(FIXTURE["native_after_reply"]["d3"]["board"])
    assert "e3" in legal_moves(alternative, "X") and "e3" not in legal_moves(played, "X")
    after = apply_move(alternative, "X", "e3")
    assert alternative[3][3] == "O" and after[3][3] == "X"
    assert compare_lesson({"evidence": [item]}, item["revision"], "c5")["decision_contrast"] == contrast


@pytest.mark.parametrize("swap_colors", [False, True])
@pytest.mark.parametrize("transpose", [False, True])
def test_consequence_is_invariant_under_color_and_board_symmetry(swap_colors, transpose):
    item = deepcopy(FIXTURE["evidence"])

    def move(value):
        return coordinate(*reversed(square(value))) if transpose and value != "pass" else value

    board = item["analysis"]["board"]
    if transpose:
        board = ["".join(row) for row in zip(*board)]
    if swap_colors:
        board = [row.translate(str.maketrans("XO", "OX")) for row in board]
        item["actor"] = opponent(item["actor"])
    item["analysis"].update(board=board, turn=item["actor"])
    for field in ("actual_move", "recommended_move"):
        item[field] = move(item[field])
    for candidate in item["analysis"]["candidates"]:
        candidate["coordinate"] = move(candidate["coordinate"])
        candidate["principal_variation"] = [move(step) for step in candidate["principal_variation"]]
    item["opponent_replies"] = {move(key): move(value) for key, value in item["opponent_replies"].items()}
    comparison = compare_lesson({"evidence": [item]}, item["revision"], item["actual_move"])
    effect = comparison["decision_contrast"]["consequence"]
    assert effect["reply"] == move("f4")
    assert effect["axis"] == ("rank" if transpose else "file")
    assert effect["axis_value"] == ("7" if transpose else "g")
    assert set(effect["actual_moves"]) == {move(value) for value in FIXTURE["comparison"]["decision_contrast"]["consequence"]["actual_moves"]}
    assert learning_goal(comparison)["actor"] == "you"


@pytest.mark.parametrize("language", ["Simplified Chinese", "English"])
def test_explanation_connects_the_reply_to_own_choices_and_a_preserved_capture(language):
    comparison = FIXTURE["comparison"]
    goal = learning_goal(comparison)
    text = mechanism_text("d4", goal, language)
    assert all(move in text for move in ("d3", "f4", "c5", "e3", "d4"))
    assert "c3" not in text
    assert len(text) <= TEXT_LIMITS[language]
    facts = verified_teaching_facts(comparison, comparison["revision"], comparison["actor"])
    fact = next(fact for fact in facts if fact["id"] == comparison["reason"]["fact"])
    assert "g2, g3, g4, g5, g6, g7" in fact["text"]
    assert "preserves the opponent disc on d4" in fact["text"]
