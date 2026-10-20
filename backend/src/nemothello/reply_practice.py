from nemothello.decision_contrast import reply_opportunity
from nemothello.errors import AppError
from nemothello.rules import apply_move, legal_moves, opponent
from nemothello.teaching import teaching_frames


def reply_options(board, turn):
    return {move: list(legal_moves(apply_move(board, turn, move), opponent(turn)))
            for move in legal_moves(board, turn)}


def grade_reply(question, move, alternative):
    board, turn, target = tuple(question["board"]), question["turn"], question["target"]
    options = reply_options(board, turn)
    blocking = [candidate for candidate, replies in options.items() if target not in replies]
    allowing = [candidate for candidate, replies in options.items() if target in replies]
    if not blocking or not allowing or target in options:
        raise AppError("PRACTICE_DATA", "This exercise needs two distinct reply opportunities", 500)
    blocks, allows = move in blocking, alternative in allowing
    blocked_move = move if blocks else blocking[0]
    allowed_move = alternative if allows else allowing[0]
    blocked = {"move": blocked_move, "board": apply_move(board, turn, blocked_move)}
    allowed = {"move": allowed_move, "board": apply_move(board, turn, allowed_move)}
    witness = reply_opportunity(allowed, blocked, opponent(turn), (), target)
    return {"objective": "reply_access", "legal": move in options, "move_matches_goal": blocks,
            "alternative_legal": alternative in options, "alternative_matches": allows,
            "witness": witness,
            "added_reply": reply_opportunity(blocked, allowed, opponent(turn), (), None),
            "blocking_frame": teaching_frames(board, turn, [blocked_move])[1],
            "allowing_frame": teaching_frames(board, turn, [allowed_move])[1],
            "replies_after_blocking": options[blocked_move], "replies_after_allowing": options[allowed_move],
            "reason_reviewed": False, "rubric_version": question["rubric_version"]}
