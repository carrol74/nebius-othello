import json
from pathlib import Path

import pytest

from nemothello.coach_agent import CoachTools
from nemothello.coaching import check_text, review_context, validate_plan
from nemothello.concepts import concept_profile, empty_regions, names, stable_discs
from nemothello.errors import AppError
from nemothello.position_lessons import lesson_context
from nemothello.rules import Position, apply_move, legal_moves, opponent


def native_review():
    return json.loads((Path(__file__).parent / "fixtures/review-native-positions.json").read_text())["review"]


def board(*rows):
    return tuple(row.ljust(8, ".") for row in rows) + ("........",) * (8 - len(rows))


def test_stable_discs_grow_from_a_corner_along_both_edges():
    position = board("XXX", "XX", "X")
    assert names(stable_discs(position, "X")) == ["a1", "a2", "a3", "b1", "b2", "c1"]
    assert names(stable_discs(board("", ".X"), "X")) == []


def test_empty_regions_split_on_filled_squares():
    filled = "XXXXXXXX"
    position = (".XXXXXX.", filled, filled, filled, filled, filled, "XXXXXX..", "XXXXXX..")
    assert sorted(len(region) for region in empty_regions(position)) == [1, 1, 4]


def test_profile_reports_flipped_discs_next_to_empty_squares():
    start = Position()
    profile = concept_profile(start.board, start.turn, "d3")
    assert profile["exposed"] == ["d4"]
    assert profile["inner_flips"] == 1
    assert profile["safe_replies"] == list(legal_moves(apply_move(start.board, "X", "d3"), "O"))
    assert profile["region"] is None


def test_unsafe_replies_are_checked_against_the_rules_engine():
    item = next(entry for entry in native_review()["evidence"] if entry["revision"] == 16)
    position, actor = tuple(item["analysis"]["board"]), item["actor"]
    after = apply_move(position, actor, "b3")
    profile = concept_profile(position, actor, "b3")
    corners = {"a1", "h1", "a8", "h8"}
    before = set(legal_moves(after, actor)) & corners
    for reply in profile["unsafe_replies"]:
        assert set(legal_moves(apply_move(after, opponent(actor), reply), actor)) & corners - before
    assert profile["unsafe_replies"] == ["b1", "g1"]


def test_questions_and_lessons_share_the_ranked_focus():
    position = review_context(native_review(), "For position revision 24: compare g3 and b5", 24)["positions"][0]
    assert position["focus"] == review_context(lesson_input(24), None, 24)["positions"][0]["focus"]
    facts = {fact["id"]: fact["text"] for fact in position["facts"]}
    assert "g3 flips discs that then touch an empty square: b3, c3, f3" in facts["p24:quiet"]
    assert {"quiet_move", "mobility"} <= set(position["allowed_lessons"])
    assert position["values"]["p24.g3.exposed"] == 3


def test_play_line_marks_quiet_steps_and_opened_corners():
    review = native_review()
    context = review_context(review, "For position revision 24: compare g3 and b5", 24)
    tools = CoachTools(review, context)
    result = tools.run("play_line", json.dumps({"revision": 24, "moves": ["g3"]}))
    assert "b3, c3, f3 now next to an empty square" in result["text"]
    assert result["values"]["t1.s1.exposed"] == 3


def test_a_corner_both_moves_give_away_is_not_the_focus():
    position = review_context(native_review(), "For position revision 20: compare a4 and g4", 20)["positions"][0]
    assert "p20:corners" in {fact["id"] for fact in position["facts"]}
    assert "p20:corners" not in position["focus"]


def lesson_input(revision):
    review = {"game_id": "fixture", **native_review()}
    item = next(entry for entry in review["evidence"] if entry["revision"] == revision)
    return lesson_context(review, item, [])


def test_a_corner_proof_shared_by_both_moves_is_not_the_focus():
    position = review_context(lesson_input(20), None, 20)["positions"][0]
    assert {"p20:proof_a4", "p20:proof_g4"} <= {fact["id"] for fact in position["facts"]}
    assert not any(key.startswith("p20:proof_") for key in position["focus"])


def test_lesson_positions_rank_verified_board_reasons():
    focus = {revision: review_context(lesson_input(revision), None, revision)["positions"][0]["focus"]
             for revision in (2, 16, 24, 26)}
    # The replies contrasted at 2, 24 and 26 are not the opponent's strongest, so they do not lead
    assert focus[2] == []
    assert focus[16][0] == "p16:corner_contrast"
    assert focus[24] == ["p24:continuation_g3", "p24:quiet", "p24:mobility"]
    assert focus[26] == []


def test_coaching_must_build_on_the_first_focus_fact():
    context = review_context(lesson_input(24), None, 24)
    plan = {"topic": "review", "answer": {"text": "", "fact_ids": []}, "selections": [
        {"revision": 24, "fact_ids": ["p24:quiet"], "lesson_id": "quiet_move",
         "text": "g3 翻过来的 b3、c3、f3 挨着空格。"}]}
    with pytest.raises(AppError, match="first focus fact p24:continuation_g3"):
        validate_plan(json.dumps(plan, ensure_ascii=False), context)


def test_equal_values_cannot_be_the_reason_one_move_is_better():
    context = review_context(lesson_input(22), None, 22)
    values = context["positions"][0]["values"]
    assert values["p22.a3.safe_replies"] == values["p22.g6.safe_replies"]
    problems = check_text("{p22.a3.safe_replies}。{p22.g6.safe_replies}。所以 g6 更好。",
                          context["positions"][0]["facts"], values, {"a3", "g6"}, "answer")
    assert problems == [("answer compares safe_replies for a3 and g6, but the values are equal, so they are not a "
                         "reason; leave them out")]


@pytest.mark.parametrize(("text", "problems"), [
    ("b6 和 e6 两步都给对手留下夹击线。", 0),
    ("The capture runs along row 3 from a3.", 0),
    ("对手两步之后能翻回 b6。", 1),
    ("Edax rates e6 higher.", 1),
    ("下一步走棋前，先观察对手在此 move 后的可走点。", 1),
    ("对手跳过回合后，你可以再下 e6。", 1),  # only the missing pass fact
    ("e6 让对手多了 a3 这个回合。", 1),
    ("这是导致大比分失利的关键。", 1),
    ("Edax 推荐 e6。", 0),
])
def test_board_words_are_not_mistaken_for_counts_or_scores(text, problems):
    assert len(check_text(text, [], {}, {"a3", "b6", "e6"}, "answer")) == problems


def test_the_coach_uses_glossary_terms():
    assert check_text("g5 暴露了 f4。", [], {}, {"g5", "f4"}, "answer") == ["answer writes 暴露; write 挨着空格的棋子 instead"]

