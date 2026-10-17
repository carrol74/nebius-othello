import json
from pathlib import Path

import pytest

from nemothello.errors import AppError
from nemothello.rules import apply_move, legal_moves, opponent
from nemothello.schemas import TeachingComparison
from nemothello.teaching import compare_lesson


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
    assert bad.capture_lines == [["a1", "b1", "c1", "d1", "e1"]]
    board = tuple(bad.frames[2].board)
    assert tuple(bad.checked_defenses) == legal_moves(board, "X")
    for move in bad.checked_defenses:
        assert "a1" in legal_moves(apply_move(board, "X", move), "O")
    assert {line.coordinate for line in bad.defense_lines} == set(bad.checked_defenses)
    for line in bad.defense_lines:
        assert line.frames[3].coordinate == line.coordinate
        assert line.frames[4].board[0][0] == "O"
    assert bad.frames[-1].board[0][0] == "O"
    assert better.coordinate == "b3" and better.kind == "line"
    assert "a1" not in legal_moves(tuple(better.frames[2].board), "O")


def test_all_native_lessons_use_legal_steps_and_exact_flip_highlights(review):
    for item in review["evidence"]:
        for candidate in item["analysis"]["candidates"]:
            lesson = TeachingComparison.model_validate(compare_lesson(review, item["revision"], candidate["coordinate"]))
            for choice in lesson.choices:
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
