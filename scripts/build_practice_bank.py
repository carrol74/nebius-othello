import json
import random
from pathlib import Path

from nemothello.board_features import CORNERS
from nemothello.edax import Edax
from nemothello.practice import answer_lines, position_key, practice_position
from nemothello.reply_practice import reply_options
from nemothello.rules import Position

ROOT = Path(__file__).resolve().parents[1]
SEEDS = (631, 1189, 2027, 3613)


def add_reply_cases(bank):
    seen = {position_key(practice_position(bank["games"][case["game_index"]]["moves"], case["ply"])[0].board)
            for case in bank["cases"]}
    for index, game in enumerate(bank["games"]):
        for ply in range(12, min(45, len(game["moves"]))):
            position, _ = practice_position(game["moves"], ply)
            key = position_key(position.board)
            if len(position.moves) < 3 or key in seen:
                continue
            options = reply_options(position.board, position.turn)
            targets = sorted(set().union(*(set(replies) for replies in options.values()))
                             - set(options) - set(CORNERS))
            target = next((target for target in targets
                           if any(target not in replies for replies in options.values())), None)
            if target is None:
                continue
            seen.add(key)
            bank["cases"].append({"id": f"reply-access-{index + 1}", "objective": "reply_access",
                                  "game_index": index, "ply": ply, "target": target})
            break
        else:
            raise ValueError(f"No reply comparison for game {index + 1}")
    bank["source"]["reply_selection"] = "First distinct qualifying reply comparison per completed game, plies 12–44; target is not a root legal move or corner"
    bank["source"]["reply_criterion"] = "Select one legal root move denying the target reply and another allowing it; check complete immediate reply sets; written reasons await human review"


def build_bank(seeds, engine):
    bank = {"rubric_version": "capture-lines-v1", "source": {
        "engine": f"Edax {engine.version}", "level": engine.level, "random_opening_plies": 8, "seeds": list(seeds),
        "selection": "First distinct qualifying position per objective per completed game, plies 12–44",
        "criterion": "A legal capture meeting the stated goal and its matching anchor; prose is retained for human review",
    }, "games": [], "cases": []}
    seen = set()
    for index, seed in enumerate(seeds):
        position, moves = Position(), []
        rng = random.Random(seed)
        while position.turn:
            if len(moves) < 8:
                move = rng.choice(position.moves)
            else:
                analysis = engine.analyze(position.board, position.turn)
                move = analysis["recommended_move"]
            moves.append(move)
            position, _ = position.play(move)
        bank["games"].append({"moves": moves, "result": position.result()})
        for objective in ("anchor", "recapture", "reply"):
            for ply in range(12, min(45, len(moves))):
                candidate, history = practice_position(moves, ply)
                context = history[-2:] if objective == "anchor" else history[-1:]
                key = position_key(candidate.board)
                lines = answer_lines(candidate, context, objective)
                if len(candidate.moves) < 3 or not lines or key in seen:
                    continue
                if objective != "reply" and len({line[0] for line in lines}) == len(candidate.moves):
                    continue
                seen.add(key)
                bank["cases"].append({"id": f"{objective}-{index + 1}", "objective": objective,
                                      "game_index": index, "ply": ply})
                break
            else:
                raise ValueError(f"No exercise for {objective} in game {index + 1}")
    add_reply_cases(bank)
    return bank


def main():
    engine = Edax(ROOT / "deploy/edax/edax", ROOT / "deploy/edax/eval.dat", "4.6", 1)
    try:
        bank = build_bank(SEEDS, engine)
        output = ROOT / "backend/src/nemothello/practice-bank.json"
        output.write_text(json.dumps(bank, indent=2) + "\n")
        print(f"Saved {len(bank['cases'])} exercises from {len(bank['games'])} completed games")
    finally:
        engine.close()


if __name__ == "__main__":
    main()
