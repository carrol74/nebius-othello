from nemothello.rules import DIRECTIONS, apply_move, legal_moves, opponent, square

CORNERS = ("a1", "h1", "a8", "h8")


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
