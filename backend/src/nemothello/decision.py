from math import isfinite

from nemothello.board_features import CORNERS
from nemothello.corner_proof import prove_corner
from nemothello.errors import AppError
from nemothello.rules import apply_move, legal_moves, square


def assess_decision(item, coordinate):
    candidates = item["analysis"]["candidates"]
    moves = legal_moves(tuple(item["analysis"]["board"]), item["actor"])
    by_move = {candidate["coordinate"]: candidate for candidate in candidates}
    if (len(by_move) != len(candidates) or set(by_move) != set(moves)
            or not all(isfinite(candidate["score"]) for candidate in candidates)):
        raise AppError("REVIEW_SCORES", "Teaching requires finite scores for every legal move", 502)
    if coordinate not in by_move:
        raise AppError("ILLEGAL_MOVE", "Choose a legal comparison move", 422)
    selected = by_move[coordinate]
    best_score = max(candidate["score"] for candidate in candidates)
    best_moves = [move for move in moves if by_move[move]["score"] == best_score]
    status = ("forced" if len(moves) == 1 else "lower_rated" if selected["score"] < best_score
              else "tied_best" if len(best_moves) > 1 else "best")
    return {
        "status": status, "legal_move_count": len(moves), "best_moves": best_moves,
        "is_played": item.get("is_played", True) and coordinate == item["actual_move"],
        "score_loss": best_score - selected["score"],
        "score_kind": "exact" if all(candidate["score_kind"] == "exact" for candidate in candidates) else "estimate",
        "position": "ahead" if best_score > 0 else "behind" if best_score < 0 else "level",
    }


def lost_corners(board, actor, move):
    after = apply_move(board, actor, move)
    return {target for target in CORNERS
            if after[square(target)[0]][square(target)[1]] == "." and prove_corner(after, actor, target)["forced"]}


def lesson_moves(item):
    actual = item["actual_move"]
    assessment = assess_decision(item, actual)
    if assessment["status"] != "lower_rated":
        return [actual]
    best = assessment["best_moves"]
    if len(best) > 1:
        board, actor = tuple(item["analysis"]["board"]), item["actor"]
        lost = lost_corners(board, actor, actual)
        # Among equally good moves, compare with one that keeps the corners the played move loses
        best = sorted(best, key=lambda move: len(lost & lost_corners(board, actor, move)))
    return [actual, best[0]]


def reference_move(item, coordinate):
    return next((move for move in lesson_moves(item) if move != coordinate), None)
