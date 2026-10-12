import pytest

from nemothello.rules import INITIAL_BOARD, Position, apply_move, legal_moves, replay


def test_initial_moves_and_capture():
    assert legal_moves(INITIAL_BOARD, "X") == ("d3", "c4", "f5", "e6")
    board = apply_move(INITIAL_BOARD, "X", "c4")
    assert board[3] == "..XXX..."
    assert sum(row.count("X") for row in board) == 4
    assert sum(row.count("O") for row in board) == 1


def test_all_eight_directions():
    board = (
        "........", ".X.X.X..", "..OOO...", ".XO.OX..",
        "..OOO...", ".X.X.X..", "........", "........",
    )
    after = apply_move(board, "X", "d4")
    assert sum(row.count("O") for row in after) == 0
    assert sum(row.count("X") for row in after) == 17


def test_edge_does_not_wrap():
    board = (".......O", "X.......", *(["........"] * 6))
    assert legal_moves(board, "X") == ()


def test_mandatory_pass():
    board = (".OXXXXXX", "XXXXXXXX", "XXXXXXXX", "XXXXXXXX",
             "XXXXXXXX", "XXXXXXXX", "XXXXXXXX", "XX.OXXXX")
    after, passed = Position(board, "X").play("a1")
    assert passed == "O"
    assert after.turn == "X"
    assert after.moves == ("c8",)


def test_finished_with_empty_squares():
    board = (".OXXXXXX", *(["XXXXXXXX"] * 6), "XXXXXXX.")
    after, _ = Position(board, "X").play("a1")
    assert after.turn is None
    assert after.result() == {"black_count": 63, "white_count": 0, "winner": "X"}


def test_draw_and_invalid_moves():
    assert Position(("XXXXXXXX", "OOOOOOOO") * 4, None).result()["winner"] == "draw"
    for move in ("d4", "a1", "a9"):
        with pytest.raises(ValueError):
            Position().play(move)


def test_replay_and_complete_game():
    position = Position()
    moves = []
    while position.turn:
        move = position.moves[0]
        moves.append(move)
        position, _ = position.play(move)
    assert replay(moves) == position
    assert len(moves) <= 60
    assert not legal_moves(position.board, "X")
    assert not legal_moves(position.board, "O")
