import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from nemothello.board_features import CORNERS, candidate_features
from nemothello.errors import AppError
from nemothello.rules import apply_move, legal_moves, opponent

REVIEW_VERSION = "grounded-v1"
COLORS = {"X": "Black", "O": "White"}
LESSONS = {
    "comparison": {
        "title": "Compare the whole position",
        "text": "Compare alternatives from the same player's perspective. The search score considers later replies; immediate disc gains alone do not determine the best move.",
        "question": "Which alternative keeps the better evaluation after the opponent replies?",
    },
    "mobility": {
        "title": "Count the opponent's choices",
        "text": "Mobility means having legal moves to choose from. Fewer replies can restrict an opponent, but the position and quality of those replies also matter. A move can score better while allowing more replies.",
        "question": "Does the better-scoring move reduce the opponent's options here?",
    },
    "corners": {
        "title": "Check corner access",
        "text": "A disc in a corner cannot be flipped. Before choosing a move, check whether the opponent can take a corner on the next turn. Corner access is one feature of the position, not a replacement for comparing the search results.",
        "question": "Does either move give the opponent an immediate corner?",
    },
    "frontier": {
        "title": "Look beyond the disc count",
        "text": "Frontier discs touch an empty square. Having many can make more of your discs available for future flips. Compare this with mobility and the search score; frontier counts alone do not prove which move is better.",
        "question": "How does each alternative change the frontier balance?",
    },
    "corner_neighbor": {
        "title": "Inspect the empty corner",
        "text": "A square next to an empty corner deserves a closer look. Its risk depends on whether later play gives the opponent access to that corner. Adjacency alone does not make a move wrong.",
        "question": "After this move, can the opponent actually take the nearby corner?",
    },
    "pass": {
        "title": "Notice the forced pass",
        "text": "A player with no legal move must pass. If the other player can still move, play continues; if neither can move, the game ends. A forced pass changes who gets the next decision.",
        "question": "Who can move next after this alternative?",
    },
    "endgame": {
        "title": "Read exact endgame scores",
        "text": "An exact endgame score resolves the final disc difference under best play, from the stated player's perspective. A positive value favors that player, zero is a draw, and a negative value favors the opponent. Later mistakes can still change a played game's result.",
        "question": "Which move has the best exact outcome for the player to move?",
    },
}


def stage(item: dict[str, Any]) -> str:
    empties = sum(row.count(".") for row in item["analysis"]["board"])
    return "opening" if empties >= 44 else "endgame" if empties <= 16 else "midgame"


def select_key_moves(evidence: list[dict[str, Any]], human_color: str) -> list[dict[str, Any]]:
    human = [item for item in evidence if item["actor"] == human_color
             and len(item["analysis"]["candidates"]) > 1]
    ordered = sorted(human, key=lambda item: (-item["score_loss"], item["revision"]))
    losses = [item for item in ordered if item["score_loss"] > 0]
    pool = losses or ordered[:1]
    selected = []
    for phase in ("opening", "midgame", "endgame"):
        choices = [item for item in pool if stage(item) == phase]
        if choices:
            selected.append(choices[0])
    for item in pool:
        if len(selected) >= 3:
            break
        if item not in selected:
            selected.append(item)
    return sorted(selected, key=lambda item: item["revision"])


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


def enrich_evidence(item: dict[str, Any]) -> dict[str, Any]:
    board, actor = tuple(item["analysis"]["board"]), item["actor"]
    features = {entry["coordinate"]: entry for entry in candidate_features(board, actor)}
    comparisons = []
    for candidate in item["analysis"]["candidates"]:
        move = candidate["coordinate"]
        if not candidate["principal_variation"] or candidate["principal_variation"][0] != move:
            raise AppError("REVIEW_VARIATION", "Search variation does not start with its candidate", 502)
        after = apply_move(board, actor, move)
        replies = list(legal_moves(after, opponent(actor)))
        comparisons.append({
            **features[move], "opponent_legal_moves": replies,
            "opponent_corners": [reply for reply in replies if reply in CORNERS],
            "frames": variation_frames(board, actor, candidate["principal_variation"]),
        })
    return {**item, "comparisons": comparisons, "stage": stage(item)}


def fact(identifier, text, topic, revision=None):
    return {"id": identifier, "text": text, "topic": topic, "revision": revision}


def summary_facts(review: dict[str, Any]) -> list[dict[str, Any]]:
    result = review["result"]
    winner = "The game was a draw" if result["winner"] == "draw" else f"{COLORS[result['winner']]} won"
    facts = [fact("result", f"You played {COLORS[review['human_color']]}. {winner}: Black {result['black_count']}, White {result['white_count']}.", "outcome")]
    adopted = review["hint_adoption"]
    facts.append(fact("adoption", f"You followed hints on {adopted['adopted_turns']} of {adopted['shown_turns']} turns with a displayed hint.", "hints"))
    for hint in review["hints"]:
        entry = next((item for item in review["evidence"] if hint["hint_id"] in item["shown_hint_ids"]), None)
        choice = (f"You played {entry['actual_move']} and {'followed it' if entry['actual_move'] == hint['recommended_move'] else 'chose a different move'}."
                  if entry else "No subsequent player move is recorded.")
        facts.append(fact(f"hint:{hint['hint_id']}", f"At position {hint['revision']}, the displayed hint was {hint['recommended_move']}. {choice}", "hints", hint["revision"]))
    facts.append(fact("outcome_limit", "A better search estimate does not guarantee a win. The original result does not establish what would happen after an unplayed alternative; a saved replay proves only that replay's result.", "outcome"))
    for branch in review.get("branch_results", []):
        outcome = branch["result"]
        facts.append(fact(f"branch:{branch['game_id']}", f"The saved hint replay from position {branch['parent_revision']} finished Black {outcome['black_count']}, White {outcome['white_count']}. It used the original opponent configuration.", "outcome", branch["parent_revision"]))
    return facts


def position_facts(item: dict[str, Any], extra_moves: set[str] | None = None):
    revision, actor = item["revision"], item["actor"]
    actual, recommended = item["actual_move"], item["recommended_move"]
    candidates = {entry["coordinate"]: entry for entry in item["analysis"]["candidates"]}
    comparisons = {entry["coordinate"]: entry for entry in item["comparisons"]}
    played, best = candidates[actual], candidates[recommended]
    a, b = comparisons[actual], comparisons[recommended]
    prefix = f"p{revision}:"
    score_kind = "exact endgame scores under best play" if played["score_kind"] == best["score_kind"] == "exact" else "search scores; non-exact values are estimates"
    facts = [
        fact(prefix + "decision", f"At position {revision}, {COLORS[actor]} played {actual}. The analysis recommendation is {recommended}; this is separate from any hint shown during play.", "comparison", revision),
        fact(prefix + "score", f"From {COLORS[actor]}'s perspective, {actual} scores {played['score']:g} and {recommended} scores {best['score']:g}. The difference is {item['score_loss']:g}; these are {score_kind}." + (" These alternatives are equally rated." if item["score_loss"] == 0 else " Higher scores favor this player."), "comparison", revision),
        fact(prefix + "mobility", f"After {actual}, {COLORS[opponent(actor)]} has {a['opponent_moves']} legal replies; after {recommended}, {b['opponent_moves']}. Reply count alone does not explain the search preference.", "mobility", revision),
        fact(prefix + "frontier", f"After {actual}, the frontier-disc difference is {a['frontier_difference']}; after {recommended}, {b['frontier_difference']}, counting {COLORS[actor]}'s frontier discs minus the opponent's.", "frontier", revision),
    ]
    lessons = ["comparison", "mobility", "frontier"]
    for move in dict.fromkeys((actual, recommended)):
        line = " → ".join(candidates[move]["principal_variation"])
        facts.append(fact(prefix + f"line_{move}", f"One searched continuation at position {revision}: {line}. This line is illustrative; it does not include every legal reply.", "comparison", revision))
    if a["corner"] or b["corner"] or a["opponent_corners"] or b["opponent_corners"]:
        corners = lambda value: ", ".join(value) or "none"
        facts.append(fact(prefix + "corners", f"Immediate corner replies for {COLORS[opponent(actor)]}: after {actual}, {corners(a['opponent_corners'])}; after {recommended}, {corners(b['opponent_corners'])}." + (f" {recommended} itself occupies a corner." if b["corner"] else ""), "corners", revision))
        lessons.append("corners")
    if a["empty_corner_neighbor"] or b["empty_corner_neighbor"]:
        affected = [move for move in {actual, recommended} if comparisons[move]["empty_corner_neighbor"]]
        facts.append(fact(prefix + "corner_neighbor", f"{', '.join(sorted(affected))} is adjacent to an empty corner before the move. This describes adjacency, not a proven mistake.", "corner_neighbor", revision))
        lessons.append("corner_neighbor")
    if not a["opponent_moves"] or not b["opponent_moves"]:
        texts = []
        for move in dict.fromkeys((actual, recommended)):
            entry = comparisons[move]
            if not entry["opponent_moves"]:
                texts.append(f"After {move}, " + (f"{COLORS[opponent(actor)]} must pass and {COLORS[actor]} moves again." if entry["own_moves"] else "neither player can move, so the game ends."))
        facts.append(fact(prefix + "pass", " ".join(texts), "pass", revision))
        lessons.append("pass")
    if played["score_kind"] == best["score_kind"] == "exact":
        facts.append(fact(prefix + "endgame", f"These alternatives have exact endgame scores: {actual} {played['score']:g}, {recommended} {best['score']:g}, from {COLORS[actor]}'s perspective under best play.", "endgame", revision))
        lessons.append("endgame")
    for move in sorted((extra_moves or set()) & candidates.keys() - {actual, recommended}):
        candidate = candidates[move]
        facts.append(fact(prefix + move, f"At position {revision}, {move} is legal and scores {candidate['score']:g} ({candidate['score_kind']}) from {COLORS[actor]}'s perspective; it leaves {comparisons[move]['opponent_moves']} opponent replies.", "comparison", revision))
    return facts, lessons


def pass_context(review: dict[str, Any], revision: int):
    board = tuple(review["initial_board"])
    for event in review["history"]:
        if event["kind"] == "pass" and event["revision"] - 1 == revision:
            actor = event["actor"]
            if legal_moves(board, actor) or not legal_moves(board, opponent(actor)):
                raise AppError("REPLAY_MISMATCH", "Recorded pass does not match the board", 500)
            text = f"At position {revision}, {COLORS[actor]} had no legal move and passed. {COLORS[opponent(actor)]} could still move. The pass did not change the board or disc counts."
            return {"revision": revision, "actor": COLORS[actor],
                    "human": actor == review["human_color"], "allowed_lessons": ["pass"],
                    "facts": [fact(f"p{revision}:decision", f"At position {revision}, {COLORS[actor]} passed.", "pass", revision),
                              fact(f"p{revision}:pass", text, "pass", revision)]}
        if event["kind"] == "move":
            board = apply_move(board, event["actor"], event["coordinate"])
    return None


def review_context(review: dict[str, Any], question: str | None) -> dict[str, Any]:
    requested = {int(value) for value in re.findall(r"(?:position(?:\s+revision)?|revision)\s*(\d+)", question or "", re.IGNORECASE)}
    evidence = review.get("evidence", review["key_moves"])
    if requested:
        selected = [item for item in evidence if item["revision"] in requested]
        if len(requested) > 3:
            raise AppError("REVIEW_POSITION", "Ask about at most three positions at a time", 422)
    else:
        selected = select_key_moves(evidence, review["human_color"])
    extra = set(re.findall(r"\b[a-h][1-8]\b", question or "", re.IGNORECASE))
    positions = []
    for original in selected:
        item = original if original.get("comparisons") else enrich_evidence(original)
        facts, lessons = position_facts(item, {move.lower() for move in extra})
        positions.append({"revision": item["revision"], "actor": COLORS[item["actor"]],
                          "human": item["actor"] == review["human_color"], "facts": facts,
                          "allowed_lessons": lessons})
    for revision in sorted(requested - {item["revision"] for item in positions}):
        position = pass_context(review, revision)
        if position is None:
            raise AppError("REVIEW_POSITION", "Choose a saved position before a move or pass", 422)
        positions.append(position)
    return {"summary_facts": summary_facts(review), "positions": positions,
            "lessons": LESSONS, "question": question,
            "task": "question" if question else "review"}


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
    fact_ids: list[str] = Field(min_length=1, max_length=4)
    lesson_id: str


class CoachingPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: Literal["review", "comparison", "hints", "outcome", "strategy", "unsupported"]
    selections: list[Selection] = Field(max_length=3)


def plan_schema(context: dict[str, Any]):
    schema = CoachingPlan.model_json_schema()
    schema["properties"]["selections"]["maxItems"] = len(context["positions"])
    if context["task"] == "review":
        schema["properties"]["selections"]["minItems"] = len(context["positions"])
    schema["properties"]["topic"]["enum"] = (["review"] if context["task"] == "review"
        else ["comparison", "hints", "outcome", "strategy", "unsupported"])
    if context["positions"]:
        selection = schema["$defs"]["Selection"]["properties"]
        selection["revision"]["enum"] = [item["revision"] for item in context["positions"]]
        selection["lesson_id"]["enum"] = sorted({lesson for item in context["positions"]
                                                 for lesson in item["allowed_lessons"]})
        selection["fact_ids"]["items"]["enum"] = [fact["id"] for item in context["positions"]
                                                     for fact in item["facts"]]
    return schema


def factual_question_plan(question: str | None):
    if question is None:
        return None
    text = question.lower()
    moves = set(re.findall(r"\b[a-h][1-8]\b", text))
    if not moves and any(word in text for word in ("guarantee", "guaranteed", "would i win", "would i have won", "final result")):
        return CoachingPlan(topic="outcome", selections=[])
    if not moves and "hint" in text and any(word in text for word in ("follow", "adopt", "ignore", "display", "shown")):
        return CoachingPlan(topic="hints", selections=[])
    return None


def validate_plan(raw: str, context: dict[str, Any]) -> CoachingPlan:
    try:
        plan = CoachingPlan.model_validate_json(raw)
    except ValidationError as exc:
        raise AppError("REVIEW_PLAN_INVALID", "The coach returned an invalid lesson plan. Retry coaching", 502) from exc
    positions = {item["revision"]: item for item in context["positions"]}
    if context["task"] == "question" and (plan.topic == "review" or (plan.topic == "unsupported" and plan.selections)):
        raise AppError("REVIEW_PLAN_INVALID", "The coach returned an incompatible answer plan", 502)
    if context["task"] == "review" and (plan.topic != "review" or len(plan.selections) != len(positions)):
        raise AppError("REVIEW_PLAN_INVALID", "The coach did not cover the selected player decisions", 502)
    seen = set()
    for selection in plan.selections:
        position = positions.get(selection.revision)
        if position is None or selection.revision in seen:
            raise AppError("REVIEW_PLAN_INVALID", "The coach referenced an unavailable or repeated position", 502)
        available = {item["id"]: item for item in position["facts"]}
        if (selection.lesson_id not in position["allowed_lessons"]
                or not set(selection.fact_ids) <= available.keys()
                or len(selection.fact_ids) != len(set(selection.fact_ids))
                or not any(available[key]["topic"] == selection.lesson_id for key in selection.fact_ids)):
            raise AppError("REVIEW_PLAN_INVALID", "The coach selected unsupported evidence or a lesson without evidence", 502)
        seen.add(selection.revision)
    if context["task"] == "question" and plan.topic in ("comparison", "strategy") and not plan.selections:
        raise AppError("REVIEW_PLAN_INVALID", "The coach omitted evidence for the question", 502)
    return plan


def render_plan(plan: CoachingPlan, context: dict[str, Any]):
    positions = {item["revision"]: item for item in context["positions"]}
    cards = []
    for selection in plan.selections:
        position = positions[selection.revision]
        facts = {item["id"]: item for item in position["facts"]}
        required = [f"p{selection.revision}:decision"]
        if f"p{selection.revision}:score" in facts:
            required.append(f"p{selection.revision}:score")
        if context["task"] == "question" and f"p{selection.revision}:mobility" in facts:
            required.append(f"p{selection.revision}:mobility")
        identifiers = list(dict.fromkeys([*required, *selection.fact_ids]))
        cards.append({"revision": selection.revision, "facts": [facts[key] for key in identifiers],
                      "lesson_id": selection.lesson_id, "lesson": LESSONS[selection.lesson_id]})
    summary = context["summary_facts"]
    if context["task"] == "review":
        blocks = [item["text"] for item in summary[:2]]
    elif plan.topic == "hints":
        blocks = [item["text"] for item in summary if item["topic"] == "hints"]
    elif plan.topic == "outcome":
        blocks = [item["text"] for item in summary if item["topic"] == "outcome"]
    elif plan.topic == "unsupported":
        blocks = ["The saved game evidence does not answer that question. Ask about a move, displayed hints, or the game's result."]
    else:
        blocks = []
    for card in cards:
        blocks.append(" ".join(item["text"] for item in card["facts"]))
        blocks.append(card["lesson"]["text"])
    if (context["task"] == "question" and plan.topic in ("comparison", "strategy", "hints")
            and re.search(r"\b(win|won|winning|guarantee|guaranteed|victory)\b", context["question"], re.IGNORECASE)):
        blocks.append(next(item["text"] for item in summary if item["id"] == "outcome_limit"))
    return {"text": "\n\n".join(blocks), "coaching": cards}
