from itertools import pairwise

from nemothello.board_features import CORNERS, capture_lines
from nemothello.concepts import concept_profile
from nemothello.corner_proof import prove_corner
from nemothello.decision import assess_decision, lesson_moves, reference_move
from nemothello.decision_contrast import decision_contrast, reply_opportunity
from nemothello.errors import AppError
from nemothello.reason import lesson_focus, lesson_reasons
from nemothello.rules import (
    apply_move,
    coordinate,
    flips,
    legal_moves,
    opponent,
    square,
)


def variation_frames(board, turn, moves):
    frames = [{"board": list(board), "turn": turn, "coordinate": None}]
    for move in moves:
        if turn is None:
            raise AppError("REVIEW_VARIATION", "Search variation continues after the game ends", 502)
        if move == "pass":
            if legal_moves(board, turn):
                raise AppError("REVIEW_VARIATION", "Search variation contains an invalid pass", 502)
        else:
            if move not in legal_moves(board, turn):
                raise AppError("REVIEW_VARIATION", "Search variation contains an illegal move", 502)
            board = apply_move(board, turn, move)
        turn = opponent(turn)
        if not legal_moves(board, turn) and not legal_moves(board, opponent(turn)):
            turn = None
        frames.append({"board": list(board), "turn": turn, "coordinate": move})
    return frames


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


def continuation_lesson(frames):
    if len(frames) < 3 or frames[2]["coordinate"] == "pass":
        return None
    gains = {frames[1]["coordinate"], *frames[1]["flipped"]}
    recaptured = [move for move in frames[2]["flipped"] if move in gains]
    if not recaptured:
        return None
    rays = capture_lines(tuple(frames[1]["board"]), frames[2]["actor"], frames[2]["coordinate"])
    ray = next(ray for ray in rays if set(ray[1:-1]) & set(recaptured))
    return {"kind": "recapture", "frame_index": 2, "capture_line": ray, "recaptured": recaptured}


def move_concepts(board, actor, move):
    profile = concept_profile(board, actor, move)
    return {"exposed": profile["exposed"], "inner_flips": profile["inner_flips"],
            "stable_gained": profile["stable_gained"], "safe_replies": len(profile["safe_replies"]),
            "unsafe_replies": profile["unsafe_replies"]}


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
              "checked_defenses": [], "capture_lines": [], "line_source": "engine",
              "corner_proof": None, "continuation_lesson": None, "defendable": None,
              "concepts": move_concepts(board, actor, move)}
    # Show your move and what this game's opponent plays next; corner cases replace this line
    reply = item["opponent_replies"].get(move)
    demonstration = [move, reply] if reply else [move]
    if move in CORNERS:
        lesson.update(kind="corner_taken", target=move)
        demonstration = [move]
    elif corner_access(after, other):
        target = corner_access(after, other)[0]
        lesson.update(kind="corner_given", target=target, opponent_reply=target, line_source="rules")
        lesson["corner_proof"] = prove_corner(after, actor, target)
        lesson["capture_lines"] = capture_lines(after, other, target)
        demonstration = [move, target]
    elif not legal_moves(after, other) and legal_moves(after, actor):
        lesson.update(kind="pass")
        demonstration = [move, "pass"]
    else:
        preferred = reply
        for target in CORNERS:
            row, col = square(target)
            if after[row][col] != ".":
                continue
            proof = prove_corner(after, actor, target, preferred)
            if proof["forced"]:
                reply = proof["attack"]
                defenses = [move for move in proof["defenses"] if move != "pass"]
                defense = pv[2] if len(pv) > 2 and pv[2] in defenses else next(iter(defenses), "pass")
                lesson.update(kind="corner_forced", target=target, opponent_reply=reply,
                              checked_defenses=defenses, line_source="rules", corner_proof=proof)
                demonstration = [move, reply, defense, target]
                break
    lesson["frames"] = teaching_frames(board, actor, demonstration)
    if lesson["kind"] in ("corner_given", "corner_forced"):
        lesson["defendable"] = any(corner_safe(board, actor, other_move, lesson["target"])
                                   for other_move in legal_moves(board, actor))
        lesson["capture_lines"] = capture_lines(tuple(lesson["frames"][-2]["board"]), other, lesson["target"])
    lesson["opponent_corner_moves_after_reply"] = (
        corner_access(tuple(lesson["frames"][2]["board"]), other)
        if len(lesson["frames"]) > 2 else []
    )
    if lesson["kind"] == "line":
        lesson["continuation_lesson"] = continuation_lesson(lesson["frames"])
    return lesson


def corner_comparison_witness(worse, better, target, example):
    defender = worse['frames'][0]['turn']
    attacker = opponent(defender)
    actual = {'move': worse['coordinate'], 'board': tuple(worse['frames'][1]['board'])}
    defensive = {'move': better['coordinate'], 'board': tuple(better['frames'][1]['board'])}

    def witness(available, blocked, actor, coordinate, prefix):
        if (coordinate in legal_moves(available['board'], actor)
                and coordinate not in legal_moves(blocked['board'], actor)):
            return {'prefix': prefix,
                    'opportunity': reply_opportunity(available, blocked, actor, (), coordinate)}
        return None

    direct = witness(actual, defensive, attacker, target, [])
    if direct:
        return direct
    attack = worse['corner_proof']['attack']
    if attack != 'pass':
        denied_setup = witness(actual, defensive, attacker, attack, [])
        if denied_setup:
            return denied_setup
    if example is None or example['attack'] != attack:
        return None
    if attack == 'pass':
        if legal_moves(actual['board'], attacker) or legal_moves(defensive['board'], attacker):
            return None
    elif any(attack not in legal_moves(state['board'], attacker) for state in (actual, defensive)):
        return None
    for state in (actual, defensive):
        if attack != 'pass':
            state['board'] = apply_move(state['board'], attacker, attack)
    setup_difference = witness(actual, defensive, attacker, target, [attack])
    if setup_difference:
        return setup_difference
    defense = example['defense']
    if defense is None:
        return None
    if defense != 'pass':
        new_defense = witness(defensive, actual, defender, defense, [attack])
        if new_defense:
            return new_defense
    if defense == 'pass':
        if legal_moves(actual['board'], defender) or legal_moves(defensive['board'], defender):
            return None
    elif any(defense not in legal_moves(state['board'], defender) for state in (actual, defensive)):
        return None
    for state in (actual, defensive):
        if defense != 'pass':
            state['board'] = apply_move(state['board'], defender, defense)
    difference = witness(actual, defensive, attacker, target, [attack, defense])
    if difference:
        worse['frames'] = teaching_frames(tuple(worse['frames'][0]['board']), defender,
                                          [worse['coordinate'], attack, defense, target])
        worse['capture_lines'] = capture_lines(actual['board'], attacker, target)
        worse['line_source'] = 'rules'
    return difference


def comparison_insight(choices):
    first = choices[0]
    result = {"kind": "forced", "better_move": None, "worse_move": None, "target": None, "gap": None,
              "score_kind": first["assessment"]["score_kind"], "proof": None, "example": [],
              'other_threats': [], 'witness': None}
    if first["assessment"]["status"] == "forced":
        return result
    if len(choices) == 1:
        return {**result, "kind": "best"}
    other = choices[1]
    if first["score"] == other["score"]:
        return {**result, "kind": "equal"}
    better, worse = sorted(choices, key=lambda choice: choice["score"], reverse=True)
    result.update(kind="search", better_move=better["coordinate"], worse_move=worse["coordinate"])
    corner_kinds = {"corner_given", "corner_forced"}
    if worse["kind"] in corner_kinds:
        target = worse["target"]
        defense_proof = prove_corner(tuple(better["frames"][1]["board"]), better["frames"][0]["turn"], target)
        if not defense_proof["forced"]:
            result.update(kind="corner_defense", target=target, proof=defense_proof)
            after = tuple(better['frames'][1]['board'])
            defender = better['frames'][0]['turn']
            result['other_threats'] = [proof for other_target in CORNERS if other_target != target
                                      for proof in [prove_corner(after, defender, other_target)] if proof['forced']]
            refutations = defense_proof["refutations"]
            example = next((entry for entry in refutations if entry["attack"] == worse["opponent_reply"]),
                           next(iter(refutations), None))
            if example:
                moves = [better["coordinate"], example["attack"]]
                if example["defense"] is not None:
                    moves.append(example["defense"])
                better["frames"] = teaching_frames(tuple(better["frames"][0]["board"]),
                                                    better["frames"][0]["turn"], moves)
                better.update(kind='corner_defense', target=target, corner_proof=defense_proof,
                              opponent_reply=example['attack'] if example['attack'] != 'pass' else None,
                              line_source='rules', continuation_lesson=None, capture_lines=[],
                              checked_defenses=[], defendable=None)
                better["opponent_corner_moves_after_reply"] = (
                    corner_access(tuple(better["frames"][2]["board"]), defense_proof["attacker"]))
                result["example"] = moves
            result['witness'] = corner_comparison_witness(worse, better, target, example)
        elif better["kind"] in corner_kinds and better["target"] == target:
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


def corner_safe(board, actor, move, target):
    after = apply_move(board, actor, move)
    row, col = square(target)
    return after[row][col] != "." or not prove_corner(after, actor, target)["forced"]


def corner_practice(item, target):
    # For every legal move, check whether the opponent can then force the target corner
    board, actor = tuple(item["analysis"]["board"]), item["actor"]
    other = opponent(actor)
    best = assess_decision(item, item["actual_move"])["best_moves"]
    row, col = square(target)
    options = []
    for move in legal_moves(board, actor):
        after = apply_move(board, actor, move)
        proof = prove_corner(after, actor, target) if after[row][col] == "." else None
        forced = bool(proof and proof["forced"])
        line = [move] if not forced else [move, target] if proof["attack"] == target else \
            [move, proof["attack"], proof["defenses"][0], target]
        frames = teaching_frames(board, actor, line)
        options.append({"coordinate": move, "safe": not forced, "recommended": move in best,
                        "attack": proof["attack"] if forced else None,
                        "replies": len([reply for reply in proof["defenses"] if reply != "pass"]) if forced else 0,
                        "frames": frames,
                        "capture_lines": capture_lines(tuple(frames[-2]["board"]), other, target) if forced else []})
    return {"target": target, "options": options}


def compare_lesson(review, revision, move):
    item = next((entry for entry in review["evidence"] if entry["revision"] == revision), None)
    if item is None:
        raise AppError("REVIEW_POSITION", "Choose a position before a recorded move", 422)
    assess_decision(item, move)
    if move not in lesson_moves(item):
        raise AppError("REVIEW_MOVE", "Choose the recorded move or the recommendation", 422)
    reference = reference_move(item, move)
    choices = [teach_move(item, coordinate) for coordinate in [move, reference] if coordinate is not None]
    insight = comparison_insight(choices)
    contrast = decision_contrast(item, choices) if insight["kind"] == "search" else None
    if contrast:
        for choice in choices:
            if contrast.get("consequence"):
                consequence = contrast["consequence"]
                choice["frames"] = teaching_frames(tuple(item["analysis"]["board"]), item["actor"],
                                                    [choice["coordinate"], consequence["reply"]])
                choice["line_source"] = "engine" if choice["coordinate"] == item["actual_move"] else "rules"
                opportunity = consequence["opportunity"]
                choice["target"] = opportunity["coordinate"] if choice["coordinate"] == opportunity["available_after"] else None
                choice["capture_lines"] = []
                choice["continuation_lesson"] = continuation_lesson(choice["frames"])
                choice["opponent_corner_moves_after_reply"] = corner_access(tuple(choice["frames"][2]["board"]), opponent(item["actor"]))
                continue
            witness = next((entry for entry in (contrast["removed_reply"], contrast["added_reply"])
                            if entry and entry["available_after"] == choice["coordinate"]), None)
            if witness:
                choice["frames"] = teaching_frames(tuple(item["analysis"]["board"]), item["actor"],
                                                    [choice["coordinate"], witness["coordinate"]])
                choice["capture_lines"] = [witness["capture_line"]]
                choice["line_source"] = "rules"
                choice["target"] = witness["coordinate"]
                choice["continuation_lesson"] = continuation_lesson(choice["frames"])
                choice["opponent_corner_moves_after_reply"] = corner_access(tuple(choice["frames"][2]["board"]), opponent(item["actor"]))
    comparison = {"revision": revision, "actor": item["actor"], "selected_move": move,
                  "recommended_move": max(choices, key=lambda choice: choice["score"])["coordinate"],
                  "reference_move": reference, "insight": insight, "decision_contrast": contrast, "choices": choices}
    reasons = lesson_reasons(item, comparison)
    return {**comparison, "reason": reasons[0] if reasons else None, "focus": lesson_focus(reasons, comparison)}
