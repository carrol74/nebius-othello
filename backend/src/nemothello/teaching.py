from itertools import pairwise

from nemothello.board_features import CORNERS
from nemothello.coaching import variation_frames
from nemothello.decision import assess_decision, reference_move
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
              "assessment": assess_decision(item, move),
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


def comparison_insight(choices):
    first = choices[0]
    result = {"kind": "forced", "better_move": None, "worse_move": None, "target": None, "gap": None,
              "score_kind": first["assessment"]["score_kind"]}
    if first["assessment"]["status"] == "forced":
        return result
    other = choices[1]
    if first["score"] == other["score"]:
        return {**result, "kind": "equal"}
    better, worse = sorted(choices, key=lambda choice: choice["score"], reverse=True)
    result.update(kind="search", better_move=better["coordinate"], worse_move=worse["coordinate"])
    corner_kinds = {"corner_given", "corner_forced"}
    if worse["kind"] in corner_kinds:
        target = worse["target"]
        if better["kind"] in corner_kinds and better["target"] == target:
            result.update(kind="shared_corner", target=target)
        elif worse["kind"] == "corner_given" and target not in corner_access(
                tuple(better["frames"][1]["board"]), opponent(better["frames"][0]["turn"])):
            result.update(kind="corner_access", target=target)
        elif (worse["kind"] == "corner_forced" and len(better["frames"]) > 2
              and target not in better["opponent_corner_moves_after_reply"]):
            result.update(kind="illustrated_corner", target=target)
            result["gap"] = next((square for line in worse["capture_lines"] for square in line[1:-1]
                                  if better["frames"][2]["board"][int(square[1]) - 1][ord(square[0]) - 97] == "."), None)
    return result


def compare_lesson(review, revision, move):
    item = next((entry for entry in review["evidence"] if entry["revision"] == revision), None)
    if item is None:
        raise AppError("REVIEW_POSITION", "Choose a position before a recorded move", 422)
    assessment = assess_decision(item, move)
    reference = reference_move(item, move, assessment)
    choices = [teach_move(item, coordinate) for coordinate in [move, reference] if coordinate is not None]
    return {"revision": revision, "actor": item["actor"], "selected_move": move,
            "recommended_move": assessment["best_moves"][0], "reference_move": reference,
            "insight": comparison_insight(choices), "choices": choices}
