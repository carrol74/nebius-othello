from typing import Any

from nemothello.coaching import enrich_evidence
from nemothello.errors import AppError
from nemothello.rules import Position


def position_at(game: dict[str, Any], revision: int) -> Position:
    if revision == 0:
        return Position(tuple(game["initial_board"]), game["initial_turn"])
    event = next((item for item in game["history"] if item["revision"] == revision), None)
    if event is None:
        raise AppError("REVIEW_POSITION", "This position is not in the saved game", 422)
    return Position(tuple(event["board"]), event["turn"])


def check_teachable(game: dict[str, Any], revision: int) -> Position:
    position = position_at(game, revision)
    if position.turn is None:
        raise AppError("REVIEW_TERMINAL", "Step back to a position before the game ended", 422)
    if not position.moves:
        raise AppError("REVIEW_PASS", "This player must pass. Step forward to the next turn", 422)
    return position


def analyze_position(game: dict[str, Any], revision: int, engine) -> dict[str, Any]:
    position = check_teachable(game, revision)
    analysis = {key: value for key, value in engine.analyze(position.board, position.turn).items()
                if key != "raw_output"}
    played = next((event for event in game["history"]
                   if event["revision"] == revision + 1 and event["kind"] == "move"), None)
    best = max(analysis["candidates"], key=lambda item: item["score"])
    move = played["coordinate"] if played else best["coordinate"]
    actual = next(item for item in analysis["candidates"] if item["coordinate"] == move)
    return enrich_evidence({
        "revision": revision, "actor": position.turn, "actual_move": move,
        "is_played": played is not None, "recommended_move": best["coordinate"],
        "score_loss": best["score"] - actual["score"], "analysis": analysis,
        "shown_hint_ids": [], "adopted_hint": False,
    })


def lesson_context(game: dict[str, Any], evidence: dict[str, Any], hints: list[dict[str, Any]]):
    shown = [hint for hint in hints if hint["game_id"] == game["game_id"] and hint["displayed"]]
    adopted = 0
    for revision in {hint["revision"] for hint in shown}:
        move = next((item for item in game["history"]
                     if item["revision"] == revision + 1 and item["kind"] == "move"), None)
        adopted += bool(move and any(hint["recommended_move"] == move["coordinate"]
                                    for hint in shown if hint["revision"] == revision))
    return {**game, "evidence": [evidence], "key_moves": [evidence], "hints": shown,
            "hint_adoption": {"shown_turns": len({hint["revision"] for hint in shown}),
                              "adopted_turns": adopted}}
