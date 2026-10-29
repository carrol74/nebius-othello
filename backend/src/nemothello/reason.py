from nemothello.board_features import CORNERS
from nemothello.concepts import concept_focus, concept_profile
from nemothello.rules import apply_move, legal_moves, opponent

MAX_FOCUS = 3
# The profile field each concept highlights on the board
CONCEPT_MARKS = {"quiet": "exposed", "mobility": "safe_replies", "stable": "stable_gained", "parity": None}


def corner_replies(board, actor, move):
    return sorted(set(legal_moves(apply_move(board, actor, move), opponent(actor))) & set(CORNERS))


def explains_loss(item, reply):
    # A reply is the reason only if blocking it would recover at least half of the move's loss
    others = [score for move, score in item["reply_scores"].items() if move != reply]
    recovered = item["reply_scores"][reply] - max(others) if others else item["score_loss"]
    return 2 * recovered >= item["score_loss"]


def threat_frame(choice):
    # A direct corner shows after your move; a forced one after the opponent's setup move
    return 1 if choice["kind"] == "corner_given" else 2


def lesson_reasons(item, comparison):
    revision = comparison["revision"]
    choices = {choice["coordinate"]: choice for choice in comparison["choices"]}
    insight = comparison["insight"]
    reasons = []

    def add(kind, fact, move, frame, marks=None, target=None, actor=None):
        reasons.append({"kind": kind, "fact": f"p{revision}:{fact}", "move": move,
                        "frame": min(frame, len(choices[move]["frames"]) - 1),
                        "marks": marks or {}, "target": target, "actor": actor})

    if insight["kind"] == "forced":
        add("forced_move", "forced_move", comparison["selected_move"], 1)
        return reasons
    witness = insight["witness"]
    proofs = [choice for choice in choices.values() if choice["corner_proof"] and choice["corner_proof"]["forced"]]
    if witness:
        found = witness["opportunity"]
        line = found["capture_line"]
        add("corner_contrast", "corner_contrast", found["available_after"], len(witness["prefix"]) + 1,
            {found["available_after"]: line, found["blocked_after"]: line}, line[0], found["actor"])
    elif insight["kind"] == "corner_defense":
        loser = choices[insight["worse_move"]]
        add("corner_defense", "defense", loser["coordinate"], threat_frame(loser), target=insight["target"])
    elif len(proofs) == 1:
        add("corner_threat", f"proof_{proofs[0]['coordinate']}", proofs[0]["coordinate"],
            threat_frame(proofs[0]), target=proofs[0]["target"])
    board, actor = tuple(item["analysis"]["board"]), item["actor"]
    moves = list(choices)
    ranked = sorted(moves, key=lambda move: choices[move]["score"])
    worse = ranked[0] if len(moves) == 2 and choices[ranked[0]]["score"] != choices[ranked[1]]["score"] else None
    better = ranked[-1] if worse else comparison["selected_move"]
    if len(moves) == 2 and insight["kind"] != "shared_corner":
        corners = {move: corner_replies(board, actor, move) for move in moves}
        if (moves[0] in CORNERS) != (moves[1] in CORNERS) or corners[moves[0]] != corners[moves[1]]:
            shown = [move for move in moves if corners[move]] or [move for move in moves if move in CORNERS]
            add("corners", "corners", shown[0], 1, corners)
    contrast = comparison["decision_contrast"]
    if contrast:
        consequence = contrast.get("consequence")
        if consequence:
            found = consequence["opportunity"]
            add("reply_consequence", "reply_consequence", found["blocked_after"], 2,
                {found["blocked_after"]: consequence["actual_moves"],
                 found["available_after"]: found["capture_line"]}, found["coordinate"], actor)
        elif contrast["removed_reply"] and explains_loss(item, contrast["removed_reply"]["coordinate"]):
            found = contrast["removed_reply"]
            line = found["capture_line"]
            add("reply_contrast", "decision_contrast", found["available_after"], 1,
                {found["available_after"]: line, found["blocked_after"]: line}, found["coordinate"], found["actor"])
    recaptures = [choice for choice in choices.values() if choice["continuation_lesson"]]
    if len(recaptures) == 1:
        lesson = recaptures[0]["continuation_lesson"]
        move = recaptures[0]["coordinate"]
        add("recapture", f"continuation_{move}", move, lesson["frame_index"], {move: lesson["capture_line"]})
    profiles = {move: concept_profile(board, actor, move) for move in moves}
    for name in concept_focus(profiles, worse, better):
        field = CONCEPT_MARKS[name]
        add(name, name, better if name in ("stable", "parity") else worse or better, 1,
            {move: profiles[move][field] for move in moves} if field else {})
    return reasons


def lesson_focus(reasons, comparison):
    # Facts the coach builds on, primary reason first
    focus = [reason["fact"] for reason in reasons]
    if comparison["insight"]["kind"] == "shared_corner":
        focus.insert(1, f"p{comparison['revision']}:shared_corner")
    return list(dict.fromkeys(focus))[:MAX_FOCUS]
