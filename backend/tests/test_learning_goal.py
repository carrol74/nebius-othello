import json
from copy import deepcopy
from pathlib import Path

import pytest

from nemothello.coaching import (
    DecisionExplanation,
    plan_schema,
    render_plan,
    review_context,
    validate_plan,
)
from nemothello.errors import AppError
from nemothello.learning_goal import explanation_text, learning_goal
from nemothello.rules import legal_moves, square

FIXTURES = Path(__file__).parent / "fixtures"


def context(language="en"):
    review = json.loads((FIXTURES / "review-native-positions.json").read_text())["review"]
    return review_context(review, None, 16, language)


def plan(explanation):
    return {"topic": "review", "selections": [{"revision": 16, "fact_ids": ["p16:corner_contrast"],
            "lesson_id": "corners", "explanation": explanation}]}


ENGLISH = {
    "changed_square": "b1",
    "next_time": "Before moving near an empty corner, which discs could connect the opponent's capture line?",
}
CHINESE = {
    "changed_square": "b1",
    "next_time": "靠近空角落子前，哪些棋子会替对手接上夹击线？",
}


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


@pytest.mark.parametrize("language,explanation", [("en", ENGLISH), ("zh", CHINESE)])
def test_contrast_explanations_render_once_without_internal_labels(language, explanation):
    evidence = context(language)
    validated = validate_plan(json.dumps(plan(explanation), ensure_ascii=False), evidence)
    rendered = render_plan(validated, evidence)
    text = rendered["coaching"][0]["text"]
    assert ("b1 留空" if language == "zh" else "b1 is empty") in text
    assert text.endswith(explanation["next_time"])
    assert rendered["coaching"][0]["facts"][-1]["id"] == "p16:corner_contrast"
    assert rendered["coaching"][0]["facts"][-1]["frames"][2]["coordinate"] == "e1"
    assert rendered["answer"] == ""
    properties = plan_schema(evidence)["properties"]["selections"]["items"]
    assert "explanation" in properties["required"] and "text" not in properties["properties"]


@pytest.mark.parametrize("mutation,match", [
    ("missing", "Use explanation.changed_square"),
    ("unverified", "select a verified square"),
    ("rewritten", "Extra inputs"),
    ("counts", "without coordinates or count placeholders"),
    ("assertion", "without a preceding assertion"),
])
def test_result_only_or_unrelated_teaching_is_returned_for_revision(mutation, match):
    candidate = plan(deepcopy(ENGLISH))
    selection = candidate["selections"][0]
    if mutation == "missing":
        del selection["explanation"]
        selection["text"] = "After b1, the opponent can take a1."
    elif mutation == "unverified":
        selection["explanation"]["changed_square"] = "h8"
    elif mutation == "rewritten":
        selection["explanation"]["instead"] = "After b3, b1 remains occupied by you."
    elif mutation == "counts":
        selection["explanation"]["next_time"] = "What can you learn from {p16.b1.replies}?"
    else:
        selection["explanation"]["next_time"] = "The corner is safe. Why?"
    with pytest.raises(AppError, match=match):
        validate_plan(json.dumps(candidate), context())


def test_a_tied_opening_does_not_require_an_invented_contrast():
    review = json.loads((FIXTURES / "review-native-positions.json").read_text())["review"]
    evidence = review_context(review, None, 0)
    assert evidence["positions"][0]["learning_goal"] is None
    assert "text" in plan_schema(evidence)["properties"]["selections"]["items"]["required"]


@pytest.mark.parametrize("language,expected", [
    ("English", "f2 holds your disc, so no disc can be placed there"),
    ("Simplified Chinese", "f2 是你的棋子，落点已被占据，无法再落子"),
])
def test_an_occupied_reply_is_explained_as_occupied_not_a_broken_line(language, expected):
    comparison = json.loads((FIXTURES / "occupied-reply-native.json").read_text())["comparison"]
    goal = learning_goal(comparison)
    explanation = DecisionExplanation(changed_square="f2", next_time="Which square could you occupy?")
    rendered = explanation_text(explanation, goal, language)
    assert expected in rendered
    assert "breaking" not in rendered and "不成立" not in rendered
