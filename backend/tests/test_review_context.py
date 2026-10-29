import json
from copy import deepcopy
from pathlib import Path

import pytest

from nemothello.coaching import (
    COORDINATE,
    enrich_evidence,
    known_coordinates,
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


def test_key_moves_are_the_largest_human_losses_of_at_least_four_discs(native_review):
    selected = select_key_moves(native_review["evidence"], native_review["human_color"])
    assert 1 <= len(selected) <= 3
    assert [item["revision"] for item in selected] == sorted(item["revision"] for item in selected)
    assert all(item["actor"] == native_review["human_color"] and item["score_loss"] >= 4 for item in selected)
    others = [item for item in native_review["evidence"] if item not in selected
              and item["actor"] == native_review["human_color"]]
    assert all(item["score_loss"] <= min(chosen["score_loss"] for chosen in selected) for item in others)
    small = [{**item, "score_loss": min(item["score_loss"], 3)} for item in native_review["evidence"]]
    assert select_key_moves(small, native_review["human_color"]) == []
    initial = next(item for item in native_review["evidence"] if item["revision"] == 0)
    assert initial["score_loss"] == 0
    tied_context = review_context({**native_review, "evidence": [initial]}, None, 0)
    assert "equally good move" in tied_context["positions"][0]["facts"][0]["text"]


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
    before = review_context(native_review, "For position revision 16: compare b1 and b3", 16)
    native_review["explanation"] = "Old generated prose must not become evidence"
    after = review_context(native_review, "For position revision 16: compare b1 and b3", 16)
    assert before == after
    assert [position["revision"] for position in after["positions"]] == [16]
    assert "history" not in after
    facts = {item["id"]: item["text"] for item in after["positions"][0]["facts"]}
    assert "you played b1" in facts["p16:decision"]
    assert "Edax recommends b3 instead" in facts["p16:decision"] and "p16:score" not in facts
    assert not any(key.endswith((".score", ".behind_best", ".frontier", ".discs")) for key in after["positions"][0]["values"])
    assert "After b1, the opponent has 9 legal replies" in facts["p16:mobility"]
    assert "After b3, the opponent has 10 legal replies" in facts["p16:mobility"]


def test_displayed_hints_are_distinct_from_postgame_analysis(native_review):
    facts = summary_facts(native_review)
    texts = " ".join(item["text"] for item in facts)
    assert "1 of 2 turns" in texts
    assert "displayed hint was d3. You played d3 and followed it" in texts
    assert "displayed hint was e6. You played b6 and chose a different move" in texts
    assert "original result does not establish" in texts
    assert not any(item["revision"] == 11 for item in facts)


def question_plan(text, fact_ids, selections=()):
    return json.dumps({"topic": "comparison", "answer": {"text": text, "fact_ids": fact_ids},
                       "selections": list(selections)})


def test_coach_text_is_filled_from_cited_evidence_values(native_review):
    context = review_context(native_review, "For position 16: explain mobility. Does it guarantee a win?", 16)
    raw = question_plan(
        "{p16.b1.replies}. {p16.b3.replies}. "
        "Following the recommendation still does not guarantee a win.", ["p16:mobility", "outcome_limit"],
        [{"revision": 16, "fact_ids": ["p16:mobility"], "lesson_id": "mobility",
          "text": "{p16.b1.replies}."}])
    response = render_plan(validate_plan(raw, context), context)
    assert response["answer"] == ("After b1, the opponent has 9 legal replies. After b3, the opponent has 10 legal replies. "
                                  "Following the recommendation still does not guarantee a win.")
    assert response["coaching"][0]["text"] == "After b1, the opponent has 9 legal replies."
    assert response["text"].startswith(response["answer"])
    assert response["coaching"][0]["lesson_id"] == "mobility"
    assert "At position 16, you played b1" in response["coaching"][0]["facts"][0]["text"]
    assert {item["id"] for item in response["answer_facts"]} == {"p16:mobility", "outcome_limit"}


def test_dotted_inline_citations_are_recognized(native_review):
    context = review_context(native_review, "局面16：b1 好吗？", 16, language="zh")
    raw = question_plan("{p16.b1.replies}（p16.mobility）。", [])
    response = render_plan(validate_plan(raw, context), context)
    assert response["answer"] == "下 b1 后，对手有 9 个合法落点。"
    assert [item["id"] for item in response["answer_facts"]] == ["p16:mobility"]


def test_chinese_text_may_use_ordinary_words_that_contain_numerals_or_corner_characters(native_review):
    context = review_context(native_review, "局面16：b1 好吗？", 16, language="zh")
    raw = question_plan("从你的视角看，可以观察这一步。{p16.b1.replies}。", ["p16:mobility"])
    assert render_plan(validate_plan(raw, context), context)["answer"] == "从你的视角看，可以观察这一步。下 b1 后，对手有 9 个合法落点。"


def test_values_from_other_moves_add_their_source_fact(native_review):
    context = review_context(native_review, "For position 16: what about g4?", 16)
    raw = question_plan("{p16.g4.replies}.", ["p16:mobility"])
    facts = render_plan(validate_plan(raw, context), context)["answer_facts"]
    assert any(item["id"] == "p16:g4" and "g4 is legal" in item["text"] for item in facts)


@pytest.mark.parametrize("text,fact_ids", [
    ("b1 leaves 9 replies.", ["p16:mobility"]),
    ("b1 leaves nine replies.", ["p16:mobility"]),
    ("b1 之后对手有九种应对。", ["p16:mobility"]),
    ("b1 leaves {p16.b1.missing} replies.", ["p16:mobility"]),
    ("{p16.b1.replies}.", ["adoption"]),
    ("You ignored the hint here.", ["p16:mobility"]),
    ("b1 gives away a corner.", ["p16:mobility"]),
    ("按这个走法你一定能赢。", ["p16:mobility"]),
    ("b1 的评分更低。", ["p16:mobility"]),
    ("b3 is rated higher than b1.", ["p16:mobility"]),
    ("After b1 White has more replies.", ["p16:mobility"]),
    ("b1 之后白方的应对更多。", ["p16:mobility"]),
    ("b1 之后白棋的应对更多。", ["p16:mobility"]),
    ("玩家想用 b1 限制对手。", ["p16:mobility"]),
    ("你的想法（review_recollection）没有实现。", ["p16:mobility"]),
    ("Within three plies nothing changes.", ["p16:mobility"]),
])
def test_uncited_values_and_claims_are_rejected(native_review, text, fact_ids):
    context = review_context(native_review, "For position 16: explain", 16)
    with pytest.raises(AppError) as error:
        validate_plan(question_plan(text, fact_ids), context)
    assert error.value.code == "COACH_UNGROUNDED"


def test_long_square_lists_and_long_text_are_returned_for_rewriting(native_review):
    context = review_context(native_review, "局面16：b1 好吗？", 16, language="zh")
    squares = "、".join(sorted(known_coordinates(context))[:4])
    with pytest.raises(AppError, match="lists too many squares"):
        validate_plan(question_plan(f"对手可以下 {squares}。", ["p16:mobility"]), context)
    validate_plan(question_plan("对手可以下 b1、e1 或 a1。", ["p16:mobility"]), context)
    with pytest.raises(AppError, match="keep it under 160"):
        validate_plan(question_plan("这一步之后对手的应对更多。" * 14, ["p16:mobility"]), context)


def test_coordinates_outside_the_evidence_are_rejected(native_review):
    context = review_context(native_review, "For position 16: explain", 16)
    known = known_coordinates(context)
    absent = next(f"{column}{row}" for column in "abcdefgh" for row in "12345678" if f"{column}{row}" not in known)
    assert COORDINATE.fullmatch(absent)
    with pytest.raises(AppError, match=absent):
        validate_plan(question_plan(f"{absent} would be better.", ["p16:mobility"]), context)


@pytest.mark.parametrize("mutation", ["unknown_position", "unknown_fact", "unsupported_lesson", "extra_key", "empty_answer"])
def test_invalid_plan_is_rejected_without_rendering_model_claims(native_review, mutation):
    context = review_context(native_review, "For position 16: explain", 16)
    selection = {"revision": 16, "fact_ids": ["p16:mobility"], "lesson_id": "mobility",
                 "text": "{p16.b1.replies}."}
    plan = {"topic": "comparison", "answer": {"text": "Compare the replies.", "fact_ids": ["p16:mobility"]},
            "selections": [selection]}
    if mutation == "unknown_position":
        selection["revision"] = 999
    elif mutation == "unknown_fact":
        selection["fact_ids"] = ["p16:guaranteed_win"]
    elif mutation == "unsupported_lesson":
        selection["lesson_id"] = "endgame"
    elif mutation == "extra_key":
        selection["claim"] = "b3 was played and lost"
    else:
        plan["answer"]["text"] = " "
    with pytest.raises(AppError) as error:
        validate_plan(json.dumps(plan), context)
    assert error.value.code == "REVIEW_PLAN_INVALID"


def test_missing_position_fails_before_model_request(native_review):
    with pytest.raises(AppError) as error:
        review_context(native_review, "For revision 999: why?", 999)
    assert error.value.code == "REVIEW_POSITION"


@pytest.mark.parametrize("question", ["局面30：为什么黑方必须跳过回合？", "我采用过哪些提示？", "按照提示一定能赢吗？"])
def test_every_question_requires_a_configured_model_before_any_request(native_review, question):
    model = Nemotron("", "https://unused.invalid/v1", "")
    try:
        with pytest.raises(AppError) as error:
            model.explain(native_review, question, revision=16)
        assert error.value.code == "REVIEW_NOT_CONFIGURED"
    finally:
        model.close()


def test_full_review_must_cover_all_selected_human_decisions(native_review):
    context = review_context(native_review, None, 16)
    selections = []
    for item in context["positions"]:
        first = next(entry for entry in item["facts"] if entry["id"] == item["focus"][0])
        selections.append({"revision": item["revision"], "fact_ids": [first["id"]],
                           "lesson_id": first["topic"], "explanation": {
                               "changed_square": "b1"}})
    plan = {"topic": "review", "answer": {"text": "", "fact_ids": []}, "selections": selections}
    assert len(render_plan(validate_plan(json.dumps(plan), context), context)["coaching"]) == len(selections)
    incomplete = deepcopy(plan)
    incomplete["selections"].pop()
    with pytest.raises(AppError):
        validate_plan(json.dumps(incomplete), context)
    silent = deepcopy(plan)
    del silent["selections"][0]["explanation"]
    silent["selections"][0]["text"] = ""
    with pytest.raises(AppError, match="no explanation"):
        validate_plan(json.dumps(silent), context)


def test_response_schema_limits_question_to_available_position_and_identifiers(native_review):
    context = review_context(native_review, "For position 16: compare b1 and b3", 16)
    schema = plan_schema(context)
    assert "review" not in schema["properties"]["topic"]["enum"]
    selections = schema["properties"]["selections"]
    assert selections["maxItems"] == 1
    properties = selections["items"]["properties"]
    assert properties["revision"]["enum"] == [16]
    expected = {item["id"] for item in [*context["summary_facts"], *context["positions"][0]["facts"]]}
    assert set(properties["fact_ids"]["items"]["enum"]) == expected
    assert set(schema["properties"]["answer"]["properties"]["fact_ids"]["items"]["enum"]) == expected
    plan = {"topic": "comparison", "answer": {"text": "Compare them.", "fact_ids": ["p16:decision"]}, "selections": [
        {"revision": 16, "fact_ids": ["p16:decision"], "lesson_id": "comparison", "text": "Look at both moves."},
        {"revision": 16, "fact_ids": ["p16:mobility"], "lesson_id": "mobility", "text": "Replies differ."},
    ]}
    with pytest.raises(AppError, match="repeated position"):
        validate_plan(json.dumps(plan), context)


def test_opponent_questions_fail_before_model_requests(native_review):
    with pytest.raises(AppError) as error:
        review_context(native_review, "For position 11: explain this move", 11)
    assert error.value.code == "REVIEW_OPPONENT"


def test_one_rejection_lists_every_problem_with_its_text(native_review):
    context = review_context(native_review, "For position 16: explain", 16)
    raw = question_plan("At position 16, b1 leaves 9 replies and {t9.text}.", ["p16:mobility"])
    with pytest.raises(AppError) as error:
        validate_plan(raw, context)
    message = error.value.message
    assert "unknown placeholder {t9.text}" in message
    assert "writes 16 directly in 'At position 16, b1 leaves'" in message
    assert "writes 9 directly" in message
