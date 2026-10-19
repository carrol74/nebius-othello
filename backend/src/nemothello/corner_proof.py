from nemothello.rules import apply_move, legal_moves, opponent


def prove_corner(board, defender, target, preferred_reply=None):
    attacker = opponent(defender)
    attacks = legal_moves(board, attacker)
    proof = {"target": target, "attacker": attacker, "max_plies": 3, "forced": False,
             "attack": None, "defenses": [], "refutations": []}
    if target in attacks:
        return {**proof, "forced": True, "attack": target}
    if not attacks and not legal_moves(board, defender):
        return proof
    ordered = ([preferred_reply] if preferred_reply in attacks else [])
    ordered += [move for move in attacks if move != preferred_reply]
    for attack in ordered or ["pass"]:
        after = board if attack == "pass" else apply_move(board, attacker, attack)
        defenses = legal_moves(after, defender)
        if not defenses and not legal_moves(after, attacker):
            proof["refutations"].append({"attack": attack, "defense": None})
            continue
        for defense in defenses or ("pass",):
            defended = after if defense == "pass" else apply_move(after, defender, defense)
            if target not in legal_moves(defended, attacker):
                proof["refutations"].append({"attack": attack, "defense": defense})
                break
        else:
            return {**proof, "forced": True, "attack": attack,
                    "defenses": list(defenses) or ["pass"], "refutations": []}
    return proof
