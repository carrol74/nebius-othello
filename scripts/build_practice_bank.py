import json
import random
from pathlib import Path

from nemothello.edax import Edax
from nemothello.practice import answer_lines, position_key, practice_position
from nemothello.rules import Position


ROOT = Path(__file__).resolve().parents[1]
SEEDS = (631, 1189, 2027, 3613)


def main():
    engine = Edax(ROOT / "deploy/edax/edax", ROOT / "deploy/edax/eval.dat", "4.6", 1)
    bank = {"rubric_version": "capture-lines-v1", "source": {
        "engine": "Edax 4.6", "level": 1, "random_opening_plies": 8, "seeds": list(SEEDS),
        "selection": "First distinct qualifying position per objective per completed game, plies 12–44",
        "criterion": "A legal capture meeting the stated goal and its matching anchor; prose is retained for human review",
    }, "games": [], "cases": []}
    seen = set()
    try:
        for index, seed in enumerate(SEEDS):
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
        output = ROOT / "backend/src/nemothello/practice-bank.json"
        output.write_text(json.dumps(bank, indent=2) + "\n")
        print(f"Saved {len(bank['cases'])} exercises from {len(bank['games'])} completed games")
    finally:
        engine.close()


if __name__ == "__main__":
    main()
