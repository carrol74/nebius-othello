from nemothello.rules import (
    DIRECTIONS,
    apply_move,
    coordinate,
    flips,
    legal_moves,
    opponent,
    square,
)

CORNERS = ("a1", "h1", "a8", "h8")


def capture_lines(board, actor, move):
    captured = set(flips(board, actor, move))
    row, col = square(move)
    lines = []
    for dr, dc in DIRECTIONS:
        r, c = row + dr, col + dc
        ray = []
        while (r, c) in captured:
            ray.append(coordinate(r, c))
            r, c = r + dr, c + dc
        if ray:
            lines.append([move, *ray, coordinate(r, c)])
    return lines


def candidate_features(board, turn):
    other = opponent(turn)
    result = []
    corners = tuple(square(move) for move in CORNERS)
    for move in legal_moves(board, turn):
        row, col = square(move)
        after = apply_move(board, turn, move)
        danger = 0
        for r, c in corners:
            if board[r][c] == "." and max(abs(r - row), abs(c - col)) == 1:
                danger = max(danger, 2 if r != row and c != col else 1)
        frontier = {turn: 0, other: 0}
        for r in range(8):
            for c in range(8):
                if after[r][c] in frontier and any(
                    0 <= r + dr < 8 and 0 <= c + dc < 8 and after[r + dr][c + dc] == "."
                    for dr, dc in DIRECTIONS
                ):
                    frontier[after[r][c]] += 1
        result.append({
            "coordinate": move, "corner": int((row, col) in corners),
            "empty_corner_neighbor": danger,
            "opponent_moves": len(legal_moves(after, other)),
            "own_moves": len(legal_moves(after, turn)),
            "frontier_difference": frontier[turn] - frontier[other],
            "disc_difference": sum(r.count(turn) - r.count(other) for r in after),
        })
    return result
