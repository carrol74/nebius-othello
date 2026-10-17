from itertools import pairwise

from nemothello.board_features import CORNERS
from nemothello.coaching import variation_frames
from nemothello.errors import AppError
from nemothello.rules import (
    DIRECTIONS,
    apply_move,
    coordinate,
    flips,
    legal_moves,
    opponent,
    square,
)


def teaching_frames(board, turn, moves):
    frames = variation_frames(board, turn, moves)
    result = [{**frames[0], "actor": None, "flipped": []}]
    for before, after in pairwise(frames):
        captured = [] if after["coordinate"] == "pass" else [
            coordinate(row, col) for row, col in flips(tuple(before["board"]), before["turn"], after["coordinate"])
        ]
        result.append({**after, "actor": before["turn"], "flipped": captured})
    return result


def corner_access(board, actor):
    return sorted(set(legal_moves(board, actor)) & set(CORNERS))


def capture_lines(board, actor, move):
    captured = set(flips(board, actor, move))
    row, col = square(move)
    lines = []
    for dr, dc in DIRECTIONS:
        r, c = row + dr, col + dc
        ray = []
        while (r, c) in captured:
            ray.append(coordinate(r, c))
            r, c = r + dr, c + dc
        if ray:
            lines.append([move, *ray, coordinate(r, c)])
    return lines


def teach_move(item, move):
    candidate = next(entry for entry in item["analysis"]["candidates"] if entry["coordinate"] == move)
    board, actor = tuple(item["analysis"]["board"]), item["actor"]
    other = opponent(actor)
    after = apply_move(board, actor, move)
    pv = candidate["principal_variation"]
    if not pv or pv[0] != move:
        raise AppError("REVIEW_VARIATION", "Search variation does not start with its candidate", 502)
    lesson = {"coordinate": move, "score": candidate["score"], "score_kind": candidate["score_kind"],
              "kind": "line", "target": None, "opponent_reply": None,
              "checked_defenses": [], "defense_lines": [], "capture_lines": [], "line_source": "engine"}
    demonstration = pv[:3]
    if move in CORNERS:
        lesson.update(kind="corner_taken", target=move)
    elif corner_access(after, other):
        target = corner_access(after, other)[0]
        lesson.update(kind="corner_given", target=target, opponent_reply=target, line_source="rules")
        lesson["capture_lines"] = capture_lines(after, other, target)
        demonstration = [move, target]
    elif not legal_moves(after, other) and legal_moves(after, actor):
        lesson.update(kind="pass")
        demonstration = [move, "pass"]
    elif len(pv) > 1 and pv[1] != "pass":
        reply = pv[1]
        replied = apply_move(after, other, reply)
        defenses = legal_moves(replied, actor)
        for target in corner_access(replied, other):
            if all(target in legal_moves(apply_move(replied, actor, defense), other) for defense in defenses):
                defense = pv[2] if len(pv) > 2 and pv[2] in defenses else next(iter(defenses), "pass")
                lesson.update(kind="corner_forced", target=target, opponent_reply=reply,
                              checked_defenses=list(defenses), line_source="rules")
                lesson["capture_lines"] = capture_lines(replied, other, target)
                lesson["defense_lines"] = [{"coordinate": response,
                    "frames": teaching_frames(board, actor, [move, reply, response, target])}
                    for response in defenses]
                demonstration = [move, reply, defense, target]
                break
    lesson["frames"] = teaching_frames(board, actor, demonstration)
    lesson["opponent_corner_moves_after_reply"] = (
        corner_access(tuple(lesson["frames"][2]["board"]), other)
        if len(lesson["frames"]) > 2 else []
    )
    return lesson


def compare_lesson(review, revision, move):
    item = next((entry for entry in review["evidence"] if entry["revision"] == revision), None)
    if item is None:
        raise AppError("REVIEW_POSITION", "Choose a position before a recorded move", 422)
    if move not in legal_moves(tuple(item["analysis"]["board"]), item["actor"]):
        raise AppError("ILLEGAL_MOVE", "Choose a legal comparison move", 422)
    choices = list(dict.fromkeys([move, item["recommended_move"]]))
    return {"revision": revision, "actor": item["actor"], "selected_move": move,
            "recommended_move": item["recommended_move"],
            "choices": [teach_move(item, choice) for choice in choices]}
