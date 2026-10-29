from collections import Counter

from nemothello.board_features import CORNERS
from nemothello.coaching import KEY_MOVE_LOSS, fact, stage
from nemothello.decision import assess_decision
from nemothello.errors import AppError
from nemothello.rules import apply_move, flips, legal_moves, opponent


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
        totals["choices"] += 1
        totals[category] += 1
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
    # Only the counts the summary should mention; moves with one legal square are left out
    facts.insert(0, fact("game:choices", f"{totals['best']} of your moves "
                        f"matched the recommended move, {totals['close']} were only slightly worse than it, which is "
                        f"not a mistake, and {totals['review']} were much worse than it and worth reviewing. "
                        f"Hints were displayed on {totals['assisted']} moves. Agreement with the recommendation "
                        "in this game does not establish a skill rank, intent, or performance in other games.",
                        "performance"))
    facts.append(fact("game:hints", f"Hints were displayed on {totals['assisted']} non-forced player choices. "
                      "A displayed hint does not prove it was read or followed.", "hints"))
    observations = []
    for topic, revisions in patterns.items():
        if not revisions:
            continue
        evidence = ("Each of these played moves flipped the most discs of any legal move in its position, while a "
                    "searched best alternative flipped fewer. Saying the player played the move that flipped the most "
                    "is accurate; it does not show why, and fewer flips are not a rule."
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
    return {"facts": facts, "counts": dict(totals),
            "observations": observations, "decisions": decisions,
            "revisions": [entry["revision"] for entry in decisions if entry["category"] != "forced"]}
