import json
from copy import deepcopy
from pathlib import Path

import pytest

from nemothello.coaching import (
    enrich_evidence,
    plan_schema,
    render_plan,
    review_context,
    select_key_moves,
    summary_facts,
    validate_plan,
)
from nemothello.errors import AppError
from nemothello.nemotron import Nemotron
from nemothello.rules import apply_move, legal_moves, opponent


@pytest.fixture
def native_review():
    path = Path(__file__).parent / "fixtures/review-native-positions.json"
    return json.loads(path.read_text())["review"]


def test_key_decisions_only_belong_to_human_and_tied_moves_are_not_losses(native_review):
    selected = select_key_moves(native_review["evidence"], native_review["human_color"])
    assert 1 <= len(selected) <= 3
    assert all(item["actor"] == native_review["human_color"] for item in selected)
    assert all(item["score_loss"] > 0 for item in selected)
    initial = next(item for item in native_review["evidence"] if item["revision"] == 0)
    assert initial["score_loss"] == 0
    tied_context = review_context({**native_review, "evidence": [initial]}, None)
    assert "equally highest-rated" in tied_context["positions"][0]["facts"][0]["text"]


@pytest.mark.parametrize("index", range(22))
def test_original_native_positions_have_rule_verified_features_and_variations(native_review, index):
    item = enrich_evidence(native_review["evidence"][index])
    original = item["analysis"]
    assert {entry["coordinate"] for entry in item["comparisons"]} == set(legal_moves(tuple(original["board"]), item["actor"]))
    for comparison in item["comparisons"]:
        after = apply_move(tuple(original["board"]), item["actor"], comparison["coordinate"])
        assert comparison["opponent_legal_moves"] == list(legal_moves(after, opponent(item["actor"])))
        assert comparison["opponent_moves"] == len(comparison["opponent_legal_moves"])
        assert comparison["frames"][1]["board"] == list(after)
        if comparison["frames"][-1]["turn"] is None:
            board = tuple(comparison["frames"][-1]["board"])
            assert not legal_moves(board, "X") and not legal_moves(board, "O")


def test_question_only_retrieves_requested_position_and_discards_old_prose(native_review):
    before = review_context(native_review, "For position revision 16: compare b1 and b3")
    native_review["explanation"] = "Old generated prose must not become evidence"
    after = review_context(native_review, "For position revision 16: compare b1 and b3")
    assert before == after
    assert [position["revision"] for position in after["positions"]] == [16]
    assert "history" not in after
    facts = {item["id"]: item["text"] for item in after["positions"][0]["facts"]}
    assert "Black played b1" in facts["p16:decision"]
    assert "b1 scores -30 and b3 scores -10" in facts["p16:score"]
    assert "9 legal replies; after b3, 10" in facts["p16:mobility"]


def test_displayed_hints_are_distinct_from_postgame_analysis(native_review):
    facts = summary_facts(native_review)
    texts = " ".join(item["text"] for item in facts)
    assert "1 of 2 turns" in texts
    assert "displayed hint was d3. You played d3 and followed it" in texts
    assert "displayed hint was e6. You played b6 and chose a different move" in texts
    assert "original result does not establish" in texts
    assert not any(item["revision"] == 11 for item in facts)


def test_coaching_plan_can_only_render_supplied_facts_and_supported_lessons(native_review):
    context = review_context(native_review, "For position 16: explain mobility. Does it guarantee a win?")
    raw = json.dumps({"topic": "comparison", "selections": [
        {"revision": 16, "fact_ids": ["p16:mobility"], "lesson_id": "mobility"},
    ]})
    response = render_plan(validate_plan(raw, context), context)
    assert "9 legal replies; after b3, 10" in response["text"]
    assert "does not guarantee a win" in response["text"]
    assert "At position 16, Black played b1" in response["text"]
    assert response["coaching"][0]["lesson_id"] == "mobility"


@pytest.mark.parametrize("mutation", ["unknown_position", "unknown_fact", "unsupported_lesson", "new_prose", "duplicate_fact"])
def test_invalid_plan_is_rejected_without_rendering_model_claims(native_review, mutation):
    context = review_context(native_review, "For position 16: explain")
    selection = {"revision": 16, "fact_ids": ["p16:mobility"], "lesson_id": "mobility"}
    plan = {"topic": "comparison", "selections": [selection]}
    if mutation == "unknown_position":
        selection["revision"] = 999
    elif mutation == "unknown_fact":
        selection["fact_ids"] = ["p16:guaranteed_win"]
    elif mutation == "unsupported_lesson":
        selection["lesson_id"] = "endgame"
    elif mutation == "new_prose":
        selection["text"] = "b3 was played and lost"
    else:
        selection["fact_ids"] *= 2
    with pytest.raises(AppError) as error:
        validate_plan(json.dumps(plan), context)
    assert error.value.code == "REVIEW_PLAN_INVALID"


def test_missing_position_fails_before_model_request(native_review):
    with pytest.raises(AppError) as error:
        review_context(native_review, "For revision 999: why?")
    assert error.value.code == "REVIEW_POSITION"


def test_question_about_recorded_pass_uses_rules_without_inventing_scores(native_review):
    event = next(item for item in native_review["history"] if item["kind"] == "pass")
    revision = event["revision"] - 1
    context = review_context(native_review, f"For position {revision}: why did I pass?")
    plan = {"topic": "strategy", "selections": [{"revision": revision,
            "fact_ids": [f"p{revision}:pass"], "lesson_id": "pass"}]}
    response = render_plan(validate_plan(json.dumps(plan), context), context)
    assert "had no legal move and passed" in response["text"]
    assert not any(item["id"].endswith(":score") for item in response["coaching"][0]["facts"])
    model = Nemotron("", "https://unused.invalid/v1", "")
    try:
        answer = model.explain(native_review, f"For position {revision}: why did I pass?")
        assert answer["model_id"] is None and answer["usage"] is None
        assert answer["text"].count("had no legal move and passed") == 1
    finally:
        model.close()


@pytest.mark.parametrize("question,topic", [
    ("局面30：为什么黑方必须跳过回合？", "strategy"),
    ("我采用过哪些提示？", "hints"),
    ("按照提示一定能赢吗？", "outcome"),
])
def test_chinese_factual_questions_need_no_model_call(native_review, question, topic):
    model = Nemotron("", "https://unused.invalid/v1", "")
    try:
        response = model.explain(native_review, question)
        assert response["model_id"] is None and response["usage"] is None
        assert response["topic"] == topic
        assert response["coaching"] or response["answer_facts"]
    finally:
        model.close()


def test_chinese_question_extracts_adjacent_move_coordinates(native_review):
    context = review_context(native_review, "局面16：为什么g4比b3差？")
    assert len(context["positions"]) == 1 and context["positions"][0]["revision"] == 16
    assert any(fact["id"] == "p16:g4" for fact in context["positions"][0]["facts"])


def test_full_review_must_cover_all_selected_human_decisions(native_review):
    context = review_context(native_review, None)
    selections = [{"revision": item["revision"], "fact_ids": [f"p{item['revision']}:score"],
                   "lesson_id": "comparison"} for item in context["positions"]]
    plan = {"topic": "review", "selections": selections}
    assert len(render_plan(validate_plan(json.dumps(plan), context), context)["coaching"]) == len(selections)
    incomplete = deepcopy(plan)
    incomplete["selections"].pop()
    with pytest.raises(AppError):
        validate_plan(json.dumps(incomplete), context)


def test_response_schema_limits_question_to_available_position_and_identifiers(native_review):
    context = review_context(native_review, "For position 16: compare b1 and b3")
    schema = plan_schema(context)
    assert "review" not in schema["properties"]["topic"]["enum"]
    assert schema["properties"]["selections"]["maxItems"] == 1
    properties = schema["$defs"]["Selection"]["properties"]
    assert properties["revision"]["enum"] == [16]
    assert set(properties["fact_ids"]["items"]["enum"]) == {item["id"] for item in context["positions"][0]["facts"]}
    plan = {"topic": "comparison", "selections": [
        {"revision": 16, "fact_ids": ["p16:score"], "lesson_id": "comparison"},
        {"revision": 16, "fact_ids": ["p16:mobility"], "lesson_id": "mobility"},
    ]}
    with pytest.raises(AppError, match="repeated position"):
        validate_plan(json.dumps(plan), context)


def test_opponent_questions_fail_before_model_requests(native_review):
    model = Nemotron("", "https://unused.invalid/v1", "")
    try:
        with pytest.raises(AppError) as error:
            model.explain(native_review, "For position 11: explain this move")
        assert error.value.code == "REVIEW_OPPONENT"
    finally:
        model.close()


def test_saved_hint_facts_need_no_credentials_or_model_request(native_review):
    model = Nemotron("", "https://unused.invalid/v1", "")
    try:
        response = model.explain(native_review, "Which displayed hints did I follow?")
        assert response["model_id"] is None and response["usage"] is None
        assert "played d3 and followed it" in response["text"]
        assert "played b6 and chose a different move" in response["text"]
    finally:
        model.close()
