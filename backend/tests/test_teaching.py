import json
from pathlib import Path

import pytest

from nemothello.board_features import capture_lines
from nemothello.coaching import review_context
from nemothello.errors import AppError
from nemothello.rules import apply_move, legal_moves, opponent
from nemothello.schemas import CornerPractice, TeachingComparison, TeachingMove
from nemothello.teaching import compare_lesson, corner_practice, teach_move


@pytest.fixture
def review():
    return json.loads((Path(__file__).parent / "fixtures/review-native-positions.json").read_text())["review"]


def test_concrete_corner_trap_checks_every_defense(review):
    lesson = TeachingComparison.model_validate(compare_lesson(review, 16, "b1"))
    bad, better = lesson.choices
    assert bad.kind == "corner_forced" and bad.target == "a1" and bad.opponent_reply == "e1"
    assert len(bad.checked_defenses) == 9
    assert [frame.coordinate for frame in bad.frames] == [None, "b1", "e1", "b2", "a1"]
    assert bad.frames[1].flipped == ["c1"] and bad.frames[2].flipped == ["e2"]
    assert bad.capture_lines == [["a1", "b1", "c1", "d1", "e1"], ["a1", "b2", "c3", "d4"]]
    board = tuple(bad.frames[2].board)
    assert tuple(bad.checked_defenses) == legal_moves(board, "X")
    for move in bad.checked_defenses:
        assert "a1" in legal_moves(apply_move(board, "X", move), "O")
    assert bad.frames[-1].board[0][0] == "O"
    assert better.coordinate == "b3" and better.kind == "corner_defense"
    assert [frame.coordinate for frame in better.frames] == [None, "b3", "e1", "b1"]
    assert "a1" not in legal_moves(tuple(better.frames[3].board), "O")
    assert lesson.insight.kind == "corner_defense"
    assert len(lesson.insight.proof.refutations) == 10


def test_all_native_lessons_use_legal_steps_and_exact_flip_highlights(review):
    for item in review["evidence"]:
        for candidate in item["analysis"]["candidates"]:
            choice = TeachingMove.model_validate(teach_move(item, candidate["coordinate"]))
            for before, after in zip(choice.frames, choice.frames[1:]):
                assert after.actor == before.turn
                if after.coordinate == "pass":
                    assert not legal_moves(tuple(before.board), before.turn)
                    assert after.flipped == [] and before.board == after.board
                else:
                    assert list(apply_move(tuple(before.board), before.turn, after.coordinate)) == after.board
                    changed = [f"{chr(97+c)}{r+1}" for r in range(8) for c in range(8)
                               if before.board[r][c] != after.board[r][c] and before.board[r][c] != "."]
                    assert sorted(changed) == sorted(after.flipped)
                if after.turn:
                    assert after.turn == opponent(before.turn)


@pytest.mark.parametrize("revision,move,code", [(999,"b1","REVIEW_POSITION"), (16,"a1","ILLEGAL_MOVE")])
def test_unsupported_lesson_fails_without_a_model_call(review, revision, move, code):
    with pytest.raises(AppError) as error:
        compare_lesson(review, revision, move)
    assert error.value.code == code


def test_corner_practice_marks_every_first_move_that_stops_the_forced_corner(review):
    item = next(entry for entry in review["evidence"] if entry["revision"] == 16)
    practice = CornerPractice.model_validate(corner_practice(item, "a1"))
    options = {option.coordinate: option for option in practice.options}
    assert set(options) == set(legal_moves(tuple(item["analysis"]["board"]), item["actor"]))
    assert not options["b1"].safe and options["b1"].attack == "e1" and options["b1"].replies == 9
    assert options["b3"].safe and options["b3"].recommended
    for option in practice.options:
        if option.safe:
            assert [frame.coordinate for frame in option.frames[1:]] == [option.coordinate]
        else:
            assert option.frames[-1].coordinate == "a1" and option.frames[-1].board[0][0] == "O"
            assert {square for ray in option.capture_lines for square in ray[1:-1]} <= set(option.frames[-1].flipped)
    snapshot = json.loads((Path(__file__).parent / "fixtures/corner-practice-native.json").read_text())
    assert snapshot["practice"] == corner_practice(item, "a1")


def test_a_corner_already_lost_before_the_move_is_not_offered_as_practice(review):
    lost = compare_lesson(review, 22, "a3")
    assert [(choice["kind"], choice["defendable"]) for choice in lost["choices"]] == [("corner_given", False)] * 2
    item = next(entry for entry in review["evidence"] if entry["revision"] == 22)
    assert not any(option["safe"] for option in corner_practice(item, "a1")["options"])
    assert compare_lesson(review, 16, "b1")["choices"][0]["defendable"] is True


def test_lost_corner_snapshot_matches_the_current_lesson():
    case = json.loads((Path(__file__).parent / "fixtures/lost-corner-native.json").read_text())
    comparison = compare_lesson({"evidence": [case["evidence"]]}, 24, "f2")
    assert comparison == case["comparison"]
    assert [(choice["kind"], choice["target"], choice["defendable"]) for choice in comparison["choices"]] == [
        ("corner_given", "a8", False)]



def test_the_primary_reason_leads_the_coach_focus_and_shows_on_its_line():
    cases = json.loads((Path(__file__).parent / "fixtures/teaching-native-cases.json").read_text())
    shown = set()
    for comparison in cases.values():
        reason = TeachingComparison.model_validate(comparison).reason
        if reason is None:
            continue
        shown.add(reason.kind)
        assert comparison["focus"][0] == reason.fact
        choices = {choice["coordinate"]: choice for choice in comparison["choices"]}
        frames = choices[reason.move]["frames"]
        assert 1 <= reason.frame < len(frames)
        if reason.kind in ("corner_contrast", "reply_contrast"):
            line = reason.marks[reason.move]
            board = tuple(frames[reason.frame]["board"])
            assert line in capture_lines(board, reason.actor, reason.target)
            blocked = next(move for move in reason.marks if move != reason.move)
            assert reason.target not in legal_moves(tuple(choices[blocked]["frames"][reason.frame]["board"]), reason.actor)
    assert shown == {"corner_contrast", "reply_contrast", "recapture"}


def test_corners_that_do_not_separate_the_moves_are_stated_as_such(review):
    context = review_context({"game_id": "fixture", **review}, None, 22)
    position = context["positions"][0]
    facts = {fact["id"]: fact["text"] for fact in position["facts"]}
    assert position["focus"] == ["p22:shared_corner"]
    assert facts["p22:shared_corner"].startswith("Both a3 and g6 let the opponent force a1")
    assert "No legal move at this position keeps a1" in facts["p22:proof_a3"]


def test_occupied_reply_snapshot_matches_the_current_lesson():
    case = json.loads((Path(__file__).parent / "fixtures/occupied-reply-native.json").read_text())
    comparison = compare_lesson({"evidence": [case["evidence"]]}, 46, "g2")
    assert comparison == case["comparison"]
    # f2 is legal only after g2, but it is not the opponent's strongest reply, so it is not the reason
    assert comparison["decision_contrast"]["removed_reply"]["coordinate"] == "f2"
    scores = case["evidence"]["reply_scores"]
    assert scores["f2"] < max(scores.values())
    assert comparison["reason"] is None
    assert comparison["recommended_move"] == "f2"
