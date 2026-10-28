import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from nemothello.coaching import CoachingPlan, Selection, render_plan, review_context
from nemothello.errors import AppError
from nemothello.lesson_view import resolve_lesson_view
from nemothello.schemas import PositionLessonRequest
from nemothello.teaching import compare_lesson


@pytest.fixture
def review():
    return json.loads((Path(__file__).parent / "fixtures/review-native-positions.json").read_text())["review"]


def test_every_displayed_line_prefix_resolves_to_its_native_board(review):
    for item in review["evidence"]:
        for choice in compare_lesson(review, item["revision"], item["actual_move"])["choices"]:
            frames = choice["frames"]
            for index, frame in enumerate(frames):
                view = {"selected_move": choice["coordinate"],
                        "line": [step["coordinate"] for step in frames[1:index + 1]]}
                resolved = resolve_lesson_view(item, view)
                assert resolved["board"] == frame["board"]
                assert resolved["turn"] == frame["turn"]
                assert resolved["flipped"] == frame["flipped"]
                assert resolved["line"] == view["line"]


def test_question_uses_alternative_root_and_the_selected_opponent_reply(review):
    item = next(item for item in review["evidence"] if item["revision"] == 16)
    choice = compare_lesson(review, 16, "b3")["choices"][0]
    view = resolve_lesson_view(item, {"selected_move": "b3", "line": [frame["coordinate"] for frame in choice["frames"][1:]]})
    context = review_context({**review, "teaching_view": view}, "Why this move?", 16)
    position = context["positions"][0]
    assert position["view"]["board"] == choice["frames"][-1]["board"]
    assert position["decision"]["is_played"] is False
    facts = {fact["id"]: fact for fact in position["facts"]}
    assert "comparing b3; the recorded move was b1" in facts["p16:decision"]["text"]
    assert "b3 line" in facts["p16:view"]["text"]
    assert "not this later board" in facts["p16:view"]["text"]
    plan = CoachingPlan(topic="comparison", selections=[Selection(
        revision=16, fact_ids=["p16:mobility"], lesson_id="mobility")])
    rendered = render_plan(plan, context)
    assert any(fact["id"] == "p16:view" for fact in rendered["coaching"][0]["facts"])


def test_unshown_or_mismatched_lines_fail_before_coaching(review):
    item = next(item for item in review["evidence"] if item["revision"] == 16)
    for view in ({"selected_move": "b3", "line": ["b1"]},
                 {"selected_move": "b1", "line": ["b1", "pass"]},
                 {"selected_move": "b1", "line": ["b1", "e1", "g6", "h8"]}):
        with pytest.raises(AppError) as error:
            resolve_lesson_view(item, view)
        assert error.value.code == "LESSON_VIEW"


def test_a_legal_practice_choice_can_become_a_question_view(review):
    item = next(item for item in review["evidence"] if item["revision"] == 0)
    alternative = next(candidate["coordinate"] for candidate in item["analysis"]["candidates"]
                       if candidate["coordinate"] != item["actual_move"])
    view = resolve_lesson_view(item, {"selected_move": alternative, "line": [alternative]})
    assert view['selected_move'] == alternative
    assert view['recorded_move'] == item['actual_move']
    assert view['assessment']['is_played'] is False
    from nemothello.rules import apply_move
    assert view['board'] == list(apply_move(tuple(item['analysis']['board']), item['actor'], alternative))


def test_a_practice_line_can_be_asked_about(review):
    item = next(item for item in review["evidence"] if item["revision"] == 16)
    view = resolve_lesson_view(item, {"selected_move": "b1", "line": ["b1", "e1", "g6", "a1"]})
    assert view["board"][0][0] == "O"
    assert view["line"][2] == "g6"
    assert view["actor"] == "O"


def test_view_request_rejects_extra_boards_and_nonquestion_context():
    payload = {"request_id": "native-view", "revision": 16,
               "view": {"selected_move": "b3", "line": ["b3"]}}
    with pytest.raises(ValidationError):
        PositionLessonRequest.model_validate(payload)
    with pytest.raises(ValidationError):
        PositionLessonRequest.model_validate({**payload, "question": "Why?",
                                            "view": {**payload["view"], "board": []}})


def test_question_lines_must_be_legal_from_the_position(review):
    item = next(item for item in review["evidence"] if item["revision"] == 16)
    with pytest.raises(AppError, match="legal line"):
        resolve_lesson_view(item, {"selected_move": "b1", "line": ["b1", "a1"]})
    with pytest.raises(AppError, match="start with the selected move"):
        resolve_lesson_view(item, {"selected_move": "b1", "line": ["b3"]})
