from typing import Any

from nemothello.coaching import COACH_VERSION, enrich_evidence
from nemothello.errors import AppError
from nemothello.rules import Position, apply_move, legal_moves, opponent
from nemothello.teaching import compare_lesson


def position_at(game: dict[str, Any], revision: int) -> Position:
    if revision == 0:
        return Position(tuple(game["initial_board"]), game["initial_turn"])
    event = next((item for item in game["history"] if item["revision"] == revision), None)
    if event is None:
        raise AppError("REVIEW_POSITION", "This position is not in the saved game", 422)
    return Position(tuple(event["board"]), event["turn"])


def check_teachable(game: dict[str, Any], revision: int) -> Position:
    if game["status"] != "finished":
        raise AppError("REVIEW_REQUIRES_END", "Finish this game before reviewing it", 409)
    position = position_at(game, revision)
    if position.turn is None:
        raise AppError("REVIEW_TERMINAL", "Step back to a position before the game ended", 422)
    if not position.moves:
        raise AppError("REVIEW_PASS", "This player must pass. Step forward to the next turn", 422)
    if position.turn != game["human_color"]:
        raise AppError("REVIEW_OPPONENT", "Choose one of your own turns for teaching", 422)
    return position


def opponent_replies(board, actor, game_opponent) -> dict[str, str]:
    # The game's own opponent answers each candidate, so demonstrations match the game's difficulty
    other = opponent(actor)
    replies = {}
    for move in legal_moves(board, actor):
        after = apply_move(board, actor, move)
        if legal_moves(after, other):
            replies[move] = game_opponent.score(after, other)["coordinate"]
    return replies


def analyze_position(game: dict[str, Any], revision: int, engine, game_opponent) -> dict[str, Any]:
    position = check_teachable(game, revision)
    analysis = {key: value for key, value in engine.analyze(position.board, position.turn).items()
                if key != "raw_output"}
    played = next(event for event in game["history"] if event["revision"] == revision + 1)
    best = max(analysis["candidates"], key=lambda item: item["score"])
    actual = next(item for item in analysis["candidates"] if item["coordinate"] == played["coordinate"])
    return enrich_evidence({
        "revision": revision, "actor": position.turn, "actual_move": played["coordinate"],
        "recommended_move": best["coordinate"],
        "score_loss": best["score"] - actual["score"], "analysis": analysis,
        "shown_hint_ids": [], "adopted_hint": False,
        "opponent_replies": opponent_replies(position.board, position.turn, game_opponent),
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


def lesson_key(game_id, revision, language):
    return f'{game_id}:{revision}:{language}'


def lesson_document(context, evidence, language='en'):
    return {"game_id": context["game_id"], "revision": evidence["revision"], "task_id": None,
            'language': language, 'coaching_version': COACH_VERSION,
            "evidence": evidence,
            "comparison": compare_lesson(context, evidence["revision"], evidence["actual_move"]),
            "hint_adoption": context["hint_adoption"], "coaching": [], "coaching_status": "not_requested",
            "coaching_error": None, "coaching_error_code": None, "model_id": None, "usage": None}
