from nemothello.board_features import CORNERS, capture_lines
from nemothello.rules import apply_move, legal_moves, opponent, square


def teaching_method(item, goal):
    if (not goal or goal["actor"] != "opponent" or goal["after_same_moves"]
            or goal["available_move"] != item["actual_move"]):
        return None
    board, actor = tuple(item["analysis"]["board"]), item["actor"]
    after = apply_move(board, actor, goal["available_move"])
    alternative = apply_move(board, actor, goal["alternative_move"])
    other, target = opponent(actor), goal["reply"]
    if target not in legal_moves(after, other) or target in legal_moves(alternative, other):
        return None
    lines = [line for line in capture_lines(after, other, target) if line[-1] == goal["anchor"]]
    if not lines:
        return None
    line = lines[0]

    def cell(state, position):
        row, col = square(position)
        return state[row][col]

    if cell(alternative, goal["anchor"]) == actor:
        method, changed = "flip_anchor", goal["anchor"]
    elif cell(alternative, target) == actor:
        method, changed = "occupy_target", target
    elif any(cell(alternative, position) == "." for position in line[1:-1]):
        method = "leave_gap"
        changed = next(position for position in line[1:-1] if cell(alternative, position) == ".")
    elif cell(alternative, line[1]) == other:
        method, changed = "keep_opponent_neighbor", line[1]
    else:
        return None
    return {"operation": method, "corner": target in CORNERS, "changed_square": changed,
            "target": target, "line": line, "available_after": goal["available_move"],
            "blocked_after": goal["alternative_move"], "scope": "Immediate reply only; all directions checked."}
