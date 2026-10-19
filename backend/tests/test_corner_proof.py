import json
from pathlib import Path

import pytest

from nemothello.board_features import CORNERS
from nemothello.coaching import verified_teaching_facts
from nemothello.corner_proof import prove_corner
from nemothello.edax import Edax, PV_MOVE, RESULT_LINE
from nemothello.rules import apply_move, legal_moves, opponent
from nemothello.schemas import CornerProof
from nemothello.teaching import compare_lesson


def advance(board, actor, move):
    if move == "pass":
        assert not legal_moves(board, actor)
        return board
    assert move in legal_moves(board, actor)
    return apply_move(board, actor, move)


def test_native_corner_certificates_cover_attacks_or_exhibit_every_defense():
    review = json.loads((Path(__file__).parent / "fixtures/review-native-positions.json").read_text())["review"]
    positive, negative, passes, terminals = 0, 0, 0, 0
    for item in review["evidence"]:
        defender = item["actor"]
        attacker = opponent(defender)
        for candidate in item["analysis"]["candidates"]:
            board = apply_move(tuple(item["analysis"]["board"]), defender, candidate["coordinate"])
            for target in CORNERS:
                proof = CornerProof.model_validate(prove_corner(board, defender, target))
                if proof.forced:
                    positive += 1
                    after = advance(board, attacker, proof.attack)
                    if proof.attack == target:
                        assert after[int(target[1]) - 1][ord(target[0]) - 97] == attacker
                        continue
                    defenses = legal_moves(after, defender)
                    assert set(proof.defenses) == set(defenses or ("pass",))
                    for defense in proof.defenses:
                        defended = advance(after, defender, defense)
                        assert target in legal_moves(defended, attacker)
                else:
                    negative += 1
                    attacks = legal_moves(board, attacker)
                    if not attacks and not legal_moves(board, defender):
                        terminals += 1
                        assert not proof.refutations
                        continue
                    assert target not in attacks
                    assert {entry.attack for entry in proof.refutations} == set(attacks or ("pass",))
                    for entry in proof.refutations:
                        after = advance(board, attacker, entry.attack)
                        if entry.defense is None:
                            terminals += 1
                            assert not legal_moves(after, defender) and not legal_moves(after, attacker)
                        else:
                            passes += entry.defense == "pass" or entry.attack == "pass"
                            defended = advance(after, defender, entry.defense)
                            assert target not in legal_moves(defended, attacker)
    assert positive and negative and passes and terminals


def test_contrast_uses_the_same_attack_and_gives_model_bounded_evidence():
    review = json.loads((Path(__file__).parent / "fixtures/review-native-positions.json").read_text())["review"]
    comparison = compare_lesson(review, 16, "b1")
    worse, better = comparison["choices"]
    assert worse["opponent_reply"] == better["frames"][2]["coordinate"] == "e1"
    assert better["frames"][3]["coordinate"] == "b1"
    facts = verified_teaching_facts(comparison, 16)
    assert any("every legal first reply" in fact["text"] for fact in facts)
    assert any("not permanent corner safety" in fact["text"] for fact in facts)
    assert all("full search-score difference" in fact["text"] for fact in facts if ":proof_" in fact["id"])


def test_native_edax_independently_checks_forcing_and_defending_certificates():
    root = Path(__file__).resolve().parents[2]
    executable, weights = root / "deploy/edax/edax", root / "deploy/edax/eval.dat"
    if not executable.is_file() or not weights.is_file():
        pytest.skip("Native Edax and eval.dat are required")
    engine = Edax(executable, weights, "4.6", 1)
    review = json.loads((Path(__file__).parent / "fixtures/review-native-positions.json").read_text())["review"]
    comparison = compare_lesson(review, 16, "b1")

    def native_moves(board, actor):
        engine._exchange(f"setboard {''.join(board)} {actor}")
        output = engine._exchange("hint 64")
        moves = set()
        for line in output.splitlines():
            match = RESULT_LINE.match(line)
            if match and not match.group(3):
                pv = PV_MOVE.findall(match.group(5))
                if pv and pv[0].lower() != "pa":
                    moves.add(pv[0].lower())
        return moves

    try:
        engine._start()
        worse, better = comparison["choices"]
        proof = worse["corner_proof"]
        board = tuple(worse["frames"][1]["board"])
        assert proof["attack"] in native_moves(board, "O")
        replied = advance(board, "O", proof["attack"])
        assert native_moves(replied, "X") == set(proof["defenses"])
        for defense in proof["defenses"]:
            assert proof["target"] in native_moves(advance(replied, "X", defense), "O")
        proof = comparison["insight"]["proof"]
        board = tuple(better["frames"][1]["board"])
        assert native_moves(board, "O") == {entry["attack"] for entry in proof["refutations"]}
        for entry in proof["refutations"]:
            replied = advance(board, "O", entry["attack"])
            assert entry["defense"] in native_moves(replied, "X")
            assert proof["target"] not in native_moves(advance(replied, "X", entry["defense"]), "O")
    finally:
        engine.close()
