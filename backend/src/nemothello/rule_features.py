"""Exact rule-derived candidate inputs for a calibrated generation policy."""

from nemothello.policy import SYMBOLS, EncodedPosition
from nemothello.rules import DIRECTIONS, apply_move, legal_moves, opponent, square

FEATURE_SYSTEM = (
    "Choose the best Othello move. Return one candidate symbol. "
    "Candidate columns after square: corner, danger, opponent_moves, own_moves, frontier_delta, disc_delta. "
    "Move counts are legal moves on the resulting board for each player. "
    "Deltas mean your count minus the opponent count after the move. "
    "Frontier discs touch an empty square. Danger is 1 for an edge neighbor or 2 for a diagonal neighbor of an empty corner, otherwise 0."
)


def candidate_features(board, turn):
    other = opponent(turn)
    result = []
    corners = ((0, 0), (0, 7), (7, 0), (7, 7))
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
        result.append(
            {
                "coordinate": move,
                "corner": int((row, col) in corners),
                "empty_corner_neighbor": danger,
                "opponent_moves": len(legal_moves(after, other)),
                "own_moves": len(legal_moves(after, turn)),
                "frontier_difference": frontier[turn] - frontier[other],
                "disc_difference": sum(r.count(turn) - r.count(other) for r in after),
            }
        )
    return result


def encode_feature_position(tokenizer, board, turn):
    features = candidate_features(board, turn)
    if not features or len(features) > len(SYMBOLS):
        raise ValueError("Feature input must contain a supported nonempty candidate set")
    symbols = tuple(SYMBOLS[: len(features)])
    coordinates = tuple(f["coordinate"] for f in features)
    message = (
        "Board:\n"
        + "\n".join(board)
        + f"\nTurn: {turn}\nEmpties: {sum(r.count('.') for r in board)}\nCandidates:\n"
    )
    columns = (
        "corner",
        "empty_corner_neighbor",
        "opponent_moves",
        "own_moves",
        "frontier_difference",
        "disc_difference",
    )
    message += "\n".join(
        symbol + "=" + f["coordinate"] + " " + " ".join(str(f[k]) for k in columns)
        for symbol, f in zip(symbols, features, strict=True)
    )
    rendered = tokenizer.apply_chat_template(
        [{"role": "system", "content": FEATURE_SYSTEM}, {"role": "user", "content": message}],
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False,
    )
    prefix = tokenizer.encode(rendered, add_special_tokens=False)
    tokens = []
    for symbol in symbols:
        token = tokenizer.encode(symbol, add_special_tokens=False)
        if (
            len(token) != 1
            or tokenizer.encode(rendered + symbol, add_special_tokens=False) != prefix + token
        ):
            raise ValueError("Candidate is not an independent single token at the answer position")
        tokens.append(token[0])
    if len(set(tokens)) != len(tokens):
        raise ValueError("Candidate symbols share token IDs")
    return EncodedPosition(prefix, coordinates, symbols, tuple(tokens), rendered)
