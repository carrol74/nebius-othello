import json
from copy import deepcopy
from pathlib import Path

import pytest

from nemothello.coaching import (
    plan_schema,
    render_plan,
    review_context,
    validate_plan,
)
from nemothello.errors import AppError
from nemothello.learning_goal import learning_goal, mechanism_text
from nemothello.rules import legal_moves, square

FIXTURES = Path(__file__).parent / "fixtures"


def context(language="en"):
    review = json.loads((FIXTURES / "review-native-positions.json").read_text())["review"]
    return review_context(review, None, 16, language)


def plan(explanation):
    return {"topic": "review", "selections": [{"revision": 16, "fact_ids": ["p16:corner_contrast"],
            "lesson_id": "corners", "explanation": explanation}]}


EXPLANATION = {"changed_square": "b1"}


def test_goals_match_the_native_boards_for_each_verified_contrast():
    cases = json.loads((FIXTURES / "teaching-native-cases.json").read_text())
    cases["occupied"] = json.loads((FIXTURES / "occupied-reply-native.json").read_text())["comparison"]
    checked = set()
    for comparison in cases.values():
        goal = learning_goal(comparison)
        if goal is None:
            continue
        choices = {choice["coordinate"]: choice for choice in comparison["choices"]}
        frame = len(goal["after_same_moves"]) + 1
        available = tuple(choices[goal["available_move"]]["frames"][frame]["board"])
        blocked = tuple(choices[goal["alternative_move"]]["frames"][frame]["board"])
        actor = comparison["reason"]["actor"]
        assert goal["reply"] in legal_moves(available, actor)
        assert goal["reply"] not in legal_moves(blocked, actor)
        row, column = square(goal["anchor"])
        assert available[row][column] == actor
        owners = {".": "empty", comparison["actor"]: "yours",
                  "O" if comparison["actor"] == "X" else "X": "opponent's"}
        for change in goal["changes"]:
            row, column = square(change["square"])
            assert owners[available[row][column]] == change["available"]
            assert owners[blocked[row][column]] == change["alternative"]
            assert available[row][column] != blocked[row][column]
        checked.add(comparison["reason"]["kind"])
    assert checked == {"corner_contrast", "reply_contrast"}


@pytest.mark.parametrize("language", ["en", "zh"])
def test_contrast_explanations_render_once_without_internal_labels(language):
    evidence = context(language)
    validated = validate_plan(json.dumps(plan(EXPLANATION)), evidence)
    rendered = render_plan(validated, evidence)
    text = rendered["coaching"][0]["text"]
    goal = evidence["positions"][0]["learning_goal"]
    assert text == mechanism_text("b1", goal, {"en": "English", "zh": "Simplified Chinese"}[language])
    assert "?" not in text and "？" not in text
    assert rendered["coaching"][0]["facts"][-1]["id"] == "p16:corner_contrast"
    assert rendered["coaching"][0]["facts"][-1]["frames"][2]["coordinate"] == "e1"
    assert rendered["answer"] == ""
    properties = plan_schema(evidence)["properties"]["selections"]["items"]
    assert "explanation" in properties["required"] and "text" not in properties["properties"]


@pytest.mark.parametrize("mutation,match", [
    ("missing", "Use explanation.changed_square"),
    ("unverified", "select a verified square"),
    ("rewritten", "Extra inputs"),
])
def test_result_only_or_unrelated_teaching_is_returned_for_revision(mutation, match):
    candidate = plan(deepcopy(EXPLANATION))
    selection = candidate["selections"][0]
    if mutation == "missing":
        del selection["explanation"]
        selection["text"] = "After b1, the opponent can take a1."
    elif mutation == "unverified":
        selection["explanation"]["changed_square"] = "h8"
    else:
        selection["explanation"]["instead"] = "After b3, b1 remains occupied by you."
    with pytest.raises(AppError, match=match):
        validate_plan(json.dumps(candidate), context())


def test_a_tied_opening_does_not_require_an_invented_contrast():
    review = json.loads((FIXTURES / "review-native-positions.json").read_text())["review"]
    evidence = review_context(review, None, 0)
    assert evidence["positions"][0]["learning_goal"] is None
    assert "text" in plan_schema(evidence)["properties"]["selections"]["items"]["required"]


@pytest.mark.parametrize("language,expected", [
    ("English", "If you play f2 instead, you take that square first."),
    ("Simplified Chinese", "如果改下 f2，就先占住了这个格子，对手不能再下这里。"),
])
def test_an_occupied_reply_is_explained_as_occupied_not_a_broken_line(language, expected):
    comparison = json.loads((FIXTURES / "occupied-reply-native.json").read_text())["comparison"]
    # This real contrast is not the lesson reason here; it still exercises the occupied-square wording
    goal = learning_goal({**comparison, "reason": {"kind": "reply_contrast", "fact": "p46:decision_contrast"}})
    rendered = mechanism_text("f2", goal, language)
    assert expected in rendered
    assert "not possible" not in rendered and "夹不成" not in rendered
