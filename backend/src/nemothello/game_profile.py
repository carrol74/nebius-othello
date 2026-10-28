from collections import Counter

from nemothello.board_features import CORNERS
from nemothello.coaching import KEY_MOVE_LOSS, fact, stage
from nemothello.decision import assess_decision
from nemothello.errors import AppError
from nemothello.rules import apply_move, flips, legal_moves, opponent

PHASES = ("opening", "midgame", "endgame")


def reply_corners(board, actor, move):
    return set(legal_moves(apply_move(board, actor, move), opponent(actor))) & set(CORNERS)


def player_decisions(review):
    expected = {}
    revision = 0
    for event in review["history"]:
        if event["kind"] == "move" and event["actor"] == review["human_color"]:
            expected[revision] = event["coordinate"]
        revision = event["revision"]
    items = [item for item in review["evidence"] if item["actor"] == review["human_color"]]
    if (len(items) != len(expected)
            or {item["revision"]: item["actual_move"] for item in items} != expected):
        raise AppError("SUMMARY_INCOMPLETE", "A game summary requires analysis of every played human move", 409)
    return sorted(items, key=lambda item: item["revision"])


def game_profile(review):
    items = player_decisions(review)
    phases = {phase: Counter() for phase in PHASES}
    totals = Counter()
    patterns = {"many_flips": [], "corner_access": []}
    decisions = []
    facts = []
    for item in items:
        played = item["actual_move"]
        assessment = assess_decision(item, played)
        phase = stage(item)
        forced = assessment["status"] == "forced"
        category = ("forced" if forced else "best" if assessment["score_loss"] == 0 else
                    "review" if assessment["score_loss"] >= KEY_MOVE_LOSS else "close")
        assisted = bool(item.get("shown_hint_ids"))
        decisions.append({"revision": item["revision"], "move": played, "phase": phase,
                          "category": category, "best_moves": assessment["best_moves"], "hint_displayed": assisted})
        detail = ("This was the only legal move." if forced else
                  f"Searched best choices: {', '.join(assessment['best_moves'])}. "
                  f"The played move is classified as {category} under this search.")
        facts.append(fact(f"p{item['revision']}:turn", f"In the {phase}, you played {played}. {detail} "
                          + ("A hint was displayed before this choice." if assisted else "No hint was displayed."),
                          "performance", item["revision"]))
        if forced:
            totals["forced"] += 1
            continue
        phases[phase]["choices"] += 1
        phases[phase][category] += 1
        totals["assisted"] += assisted
        if category != "review":
            continue
        board, actor = tuple(item["analysis"]["board"]), item["actor"]
        flip_counts = {candidate["coordinate"]: len(flips(board, actor, candidate["coordinate"]))
                       for candidate in item["analysis"]["candidates"]}
        if (flip_counts[played] == max(flip_counts.values())
                and any(flip_counts[move] < flip_counts[played] for move in assessment["best_moves"])):
            patterns["many_flips"].append(item["revision"])

        if reply_corners(board, actor, played) and any(
            not reply_corners(board, actor, move) for move in assessment["best_moves"]
        ):
            patterns["corner_access"].append(item["revision"])
    for counts in phases.values():
        totals.update(counts)
    facts.insert(0, fact("game:choices", f"Complete analysis of all {len(items)} played human moves: "
                        f"{totals['choices']} choices, {totals['forced']} forced moves. Among the choices, "
                        f"{totals['best']} matched a searched best move, {totals['close']} were close, "
                        f"{totals['review']} had a search-preferred alternative worth reviewing. "
                        f"Hints were displayed on {totals['assisted']} choices. Search agreement in this game "
                        "does not establish a skill rank, intent, or performance in other games.", "performance"))
    facts.insert(1, fact("game:phases", " ".join(
        f"{phase}: {counts['choices']} choices, {counts['best']} best, {counts['close']} close, "
        f"{counts['review']} worth reviewing." for phase, counts in phases.items())
        + " These are all the choices in each phase, not only selected mistakes.", "performance"))
    facts.append(fact("game:hints", f"Hints were displayed on {totals['assisted']} non-forced player choices. "
                      "A displayed hint does not prove it was read or followed; assisted choices do not "
                      "establish unaided ability.", "hints"))
    observations = []
    for topic, revisions in patterns.items():
        if not revisions:
            continue
        evidence = ("The played move flipped a maximum number of discs; a searched best alternative flipped fewer. "
                    "This is a correlation, not evidence of the player's intent or a rule that fewer flips are better."
                    if topic == "many_flips" else
                    "The played move allowed an immediate opponent corner capture, while at least one searched "
                    "best move did not. This establishes immediate access, not the cause of the final result.")
        played = [item["actual_move"] for item in items if item["revision"] in revisions]
        if topic == "corner_access":
            details = []
            for item in items:
                if item["revision"] not in revisions:
                    continue
                board, actor = tuple(item["analysis"]["board"]), item["actor"]
                targets = sorted(reply_corners(board, actor, item["actual_move"]))
                details.append(f"After {item['actual_move']}, the opponent can immediately take {', '.join(targets)}.")
            evidence += " " + " ".join(details)
        entry = fact(f"game:{topic}", f"Observed played moves: {', '.join(played)}. {evidence}",
                     "pattern" if topic == "many_flips" else "corners")
        facts.append(entry)
        observations.append({"id": topic, "positions": revisions, "fact_id": entry["id"]})
    return {"facts": facts, "counts": dict(totals), "phases": {p: dict(v) for p, v in phases.items()},
            "observations": observations, "decisions": decisions,
            "revisions": [entry["revision"] for entry in decisions if entry["category"] != "forced"]}
