from dataclasses import dataclass
from typing import Literal

Color = Literal["X", "O"]
Board = tuple[str, ...]
INITIAL_BOARD: Board = (
    "........", "........", "........", "...OX...",
    "...XO...", "........", "........", "........",
)
DIRECTIONS = tuple(
    (row, col) for row in (-1, 0, 1) for col in (-1, 0, 1) if (row, col) != (0, 0)
)


def opponent(color: Color) -> Color:
    if color not in ("X", "O"):
        raise ValueError("Player to move must be X or O")
    return "O" if color == "X" else "X"


def validate_board(board: Board) -> None:
    if len(board) != 8 or any(len(row) != 8 or set(row) - set(".XO") for row in board):
        raise ValueError("Board must have eight rows of eight characters, using only ., X, and O")


def square(coordinate: str) -> tuple[int, int]:
    if len(coordinate) != 2 or coordinate[0] not in "abcdefgh" or coordinate[1] not in "12345678":
        raise ValueError("Coordinate must be between a1 and h8")
    return int(coordinate[1]) - 1, ord(coordinate[0]) - ord("a")


def coordinate(row: int, col: int) -> str:
    return f"{chr(ord('a') + col)}{row + 1}"


def flips(board: Board, color: Color, move: str) -> tuple[tuple[int, int], ...]:
    row, col = square(move)
    if board[row][col] != ".":
        return ()
    other = opponent(color)
    captured = []
    for dr, dc in DIRECTIONS:
        r, c = row + dr, col + dc
        ray = []
        while 0 <= r < 8 and 0 <= c < 8 and board[r][c] == other:
            ray.append((r, c))
            r, c = r + dr, c + dc
        if ray and 0 <= r < 8 and 0 <= c < 8 and board[r][c] == color:
            captured.extend(ray)
    return tuple(captured)


def legal_moves(board: Board, color: Color) -> tuple[str, ...]:
    validate_board(board)
    opponent(color)
    return tuple(
        coordinate(r, c) for r in range(8) for c in range(8)
        if board[r][c] == "." and flips(board, color, coordinate(r, c))
    )


def apply_move(board: Board, color: Color, move: str) -> Board:
    validate_board(board)
    captured = flips(board, color, move)
    if not captured:
        raise ValueError("This square is not a legal move")
    cells = [list(row) for row in board]
    row, col = square(move)
    cells[row][col] = color
    for row, col in captured:
        cells[row][col] = color
    return tuple("".join(row) for row in cells)


@dataclass(frozen=True)
class Position:
    board: Board = INITIAL_BOARD
    turn: Color | None = "X"

    @property
    def moves(self) -> tuple[str, ...]:
        return legal_moves(self.board, self.turn) if self.turn else ()

    def play(self, move: str) -> tuple["Position", Color | None]:
        if self.turn is None:
            raise ValueError("Game has finished")
        board = apply_move(self.board, self.turn, move)
        next_turn = opponent(self.turn)
        if legal_moves(board, next_turn):
            return Position(board, next_turn), None
        if legal_moves(board, self.turn):
            return Position(board, self.turn), next_turn
        return Position(board, None), None

    def result(self) -> dict[str, int | str] | None:
        if self.turn is not None:
            return None
        black = sum(row.count("X") for row in self.board)
        white = sum(row.count("O") for row in self.board)
        return {
            "black_count": black, "white_count": white,
            "winner": "X" if black > white else "O" if white > black else "draw",
        }


def replay(moves: list[str], initial: Position | None = None) -> Position:
    position = Position() if initial is None else initial
    for move in moves:
        position, _ = position.play(move)
    return position
