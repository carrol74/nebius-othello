from nemothello.errors import AppError
from nemothello.rules import apply_move, legal_moves, opponent
from nemothello.teaching import compare_lesson, teaching_frames


def resolve_lesson_view(item, view):
    selected = view["selected_move"] if view else item["actual_move"]
    line = view["line"] if view else []
    selected_item = {**item, 'actual_move': selected, 'is_played': selected == item['actual_move']}
    comparison = compare_lesson({"evidence": [selected_item]}, item["revision"], selected)
    choice = comparison["choices"][0]
    # Any legal line from this position can be asked about, including practice attempts
    if line and line[0] != selected:
        raise AppError("LESSON_VIEW", "The line must start with the selected move", 422)
    board, turn = tuple(item["analysis"]["board"]), item["actor"]
    for move in line:
        legal = legal_moves(board, turn) if turn else None
        if legal is None or (move == "pass" and legal) or (move != "pass" and move not in legal):
            raise AppError("LESSON_VIEW", "The question must use a legal line from this position", 422)
        board = board if move == "pass" else apply_move(board, turn, move)
        turn = opponent(turn)
        if not legal_moves(board, turn) and not legal_moves(board, opponent(turn)):
            turn = None
    frame = teaching_frames(tuple(item["analysis"]["board"]), item["actor"], line)[-1]
    return {
        "selected_move": selected, "line": line, "board": frame["board"],
        "turn": frame["turn"], "actor": frame["actor"], "flipped": frame["flipped"],
        "legal_moves": list(legal_moves(tuple(frame["board"]), frame["turn"])) if frame["turn"] else [],
        "recorded_move": item["actual_move"],
        "assessment": choice["assessment"], "insight": comparison["insight"],
        "teaching": comparison,
    }
