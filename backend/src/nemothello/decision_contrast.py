from nemothello.board_features import capture_lines
from nemothello.reply_consequence import reply_consequence
from nemothello.rules import apply_move, legal_moves, opponent, square


def reply_opportunity(available, blocked, actor, root_moves, preferred):
    targets = set(legal_moves(available["board"], actor)) - set(legal_moves(blocked["board"], actor))
    witnesses = []
    for target in sorted(targets):
        for ray in capture_lines(available["board"], actor, target):
            changes = []
            for coordinate in ray:
                row, column = square(coordinate)
                before, after = available["board"][row][column], blocked["board"][row][column]
                if before != after:
                    changes.append({"coordinate": coordinate, "available": before, "blocked": after})
            witnesses.append({"actor": actor, "coordinate": target,
                              "available_after": available["move"], "blocked_after": blocked["move"],
                              "capture_line": ray, "changes": changes})
    return min(witnesses, key=lambda witness: (witness["coordinate"] in root_moves,
                                              witness["coordinate"] != preferred,
                                              len(witness["changes"]), witness["coordinate"])) if witnesses else None


def decision_contrast(item, choices):
    if len(choices) != 2 or any(choice["kind"] != "line" for choice in choices):
        return None
    actual = next((choice for choice in choices if choice["assessment"]["is_played"]), None)
    if actual is None or actual["assessment"]["status"] != "lower_rated":
        return None
    recommended = next(choice for choice in choices if choice is not actual)
    board, actor = tuple(item["analysis"]["board"]), item["actor"]
    states = [{"move": choice["coordinate"], "board": apply_move(board, actor, choice["coordinate"])}
              for choice in (actual, recommended)]
    root_moves = [state["move"] for state in states]
    candidates = {candidate["coordinate"]: candidate for candidate in item["analysis"]["candidates"]}

    def preferred(choice):
        pv = candidates[choice["coordinate"]]["principal_variation"]
        return pv[1] if len(pv) > 1 else None

    removed = reply_opportunity(states[0], states[1], opponent(actor), root_moves, preferred(actual))
    added = reply_opportunity(states[1], states[0], opponent(actor), root_moves, preferred(recommended))
    consequence = reply_consequence(item, actual["coordinate"], recommended["coordinate"])
    if removed is None and added is None and consequence is None:
        return None
    return {"actual_move": actual["coordinate"], "recommended_move": recommended["coordinate"],
            "replies_after_actual": list(legal_moves(states[0]["board"], opponent(actor))),
            "replies_after_recommended": list(legal_moves(states[1]["board"], opponent(actor))),
            "removed_reply": removed, "added_reply": added,
            **({"consequence": consequence} if consequence else {})}
