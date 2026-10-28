from nemothello.board_features import capture_lines
from nemothello.rules import apply_move, legal_moves, opponent, square


def reply_consequence(item, actual, recommended):
    board, actor = tuple(item["analysis"]["board"]), item["actor"]
    candidate = next(c for c in item["analysis"]["candidates"] if c["coordinate"] == actual)
    line = candidate["principal_variation"]
    if len(line) < 2:
        return None
    reply = line[1]
    roots = {move: apply_move(board, actor, move) for move in (actual, recommended)}
    other = opponent(actor)
    if any(reply not in legal_moves(state, other) for state in roots.values()):
        return None
    states = {move: apply_move(state, other, reply) for move, state in roots.items()}
    moves = {move: list(legal_moves(state, actor)) for move, state in states.items()}
    if len(moves[actual]) < 2:
        return None
    axis = next((index for index in (0, 1) if len({move[index] for move in moves[actual]}) == 1), None)
    if axis is None:
        return None
    value = moves[actual][0][axis]
    targets = [move for move in moves[recommended] if move[axis] != value and move not in roots]
    witnesses = []
    for target in targets:
        for ray in capture_lines(states[recommended], actor, target):
            retained = [cell for cell in ray[1:-1] if
                        board[square(cell)[0]][square(cell)[1]] == other
                        and roots[recommended][square(cell)[0]][square(cell)[1]] == other
                        and roots[actual][square(cell)[0]][square(cell)[1]] == actor
                        and states[actual][square(cell)[0]][square(cell)[1]] == actor]
            if not retained:
                continue
            changes = []
            for cell in ray:
                row, column = square(cell)
                available, blocked = states[recommended][row][column], states[actual][row][column]
                if available != blocked:
                    changes.append({"coordinate": cell, "available": available, "blocked": blocked})
            witnesses.append({"actor": actor, "coordinate": target, "available_after": recommended,
                              "blocked_after": actual, "capture_line": ray, "changes": changes,
                              "retained_disc": retained[0]})
    if not witnesses:
        return None
    witness = min(witnesses, key=lambda entry: (len(entry["capture_line"]), entry["coordinate"]))
    retained = witness.pop("retained_disc")
    return {"reply": reply, "axis": "file" if axis == 0 else "rank", "axis_value": value,
            "actual_moves": moves[actual], "alternative_moves": moves[recommended],
            "retained_disc": retained, "opportunity": witness}
