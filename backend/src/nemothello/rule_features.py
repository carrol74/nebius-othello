"""Exact rule-derived candidate inputs for a calibrated generation policy."""

from nemothello.board_features import candidate_features
from nemothello.policy import SYMBOLS, EncodedPosition

FEATURE_SYSTEM = (
    "Choose the best Othello move. Return one candidate symbol. "
    "Candidate columns after square: corner, danger, opponent_moves, own_moves, frontier_delta, disc_delta. "
    "Move counts are legal moves on the resulting board for each player. "
    "Deltas mean your count minus the opponent count after the move. "
    "Frontier discs touch an empty square. Danger is 1 for an edge neighbor or 2 for a diagonal neighbor of an empty corner, otherwise 0."
)


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
