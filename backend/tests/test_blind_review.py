import json
from pathlib import Path

from nemothello.blind_review import BlindChoice, blind_input, verify_choice
from nemothello.rules import apply_move, legal_moves, opponent


def test_blind_input_contains_only_board_and_legal_choices():
    review = json.loads((Path(__file__).parent / "fixtures/review-native-positions.json").read_text())["review"]
    item = next(entry for entry in review["evidence"] if entry["revision"] == 16)
    payload = blind_input(item)
    assert set(payload) == {"board", "to_move", "legal_moves", "coordinates"}
    assert payload["legal_moves"] == list(legal_moves(tuple(payload["board"]), item["actor"]))
    assert not any(key in json.dumps(payload) for key in ("recommended", "score", "history", "result"))


def test_choice_strength_and_explanation_facts_are_checked_separately():
    review = json.loads((Path(__file__).parent / "fixtures/review-native-positions.json").read_text())["review"]
    for item in review["evidence"]:
        candidates = item["analysis"]["candidates"]
        if len(candidates) < 2:
            continue
        best = max(candidates, key=lambda candidate: candidate["score"])
        alternative = next(candidate for candidate in candidates if candidate["coordinate"] != best["coordinate"])
        board, turn = tuple(item["analysis"]["board"]), item["actor"]
        replies = lambda move, board=board, turn=turn: legal_moves(apply_move(board, turn, move), opponent(turn))
        corners = lambda moves: [move for move in moves if move in ("a1", "h1", "a8", "h8")]
        choice = BlindChoice(move=best["coordinate"], alternative=alternative["coordinate"],
                             explanation="This text is deliberately not treated as verified.",
                             opponent_replies=len(replies(best["coordinate"])),
                             alternative_opponent_replies=len(replies(alternative["coordinate"])),
                             opponent_corner_moves=corners(replies(best["coordinate"])),
                             alternative_opponent_corner_moves=corners(replies(alternative["coordinate"])))
        checked = verify_choice(item, choice)
        assert checked["matches_best_score"] and checked["all_checked_claims_correct"]
        assert checked["free_text_explanation_status"].startswith("Not automatically verified")
        choice.opponent_replies += 1
        checked = verify_choice(item, choice)
        assert checked["matches_best_score"] and not checked["all_checked_claims_correct"]
