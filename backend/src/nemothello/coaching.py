import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from nemothello.board_features import CORNERS, candidate_features
from nemothello.decision import assess_decision, reference_move
from nemothello.errors import AppError
from nemothello.rules import apply_move, legal_moves, opponent

REVIEW_VERSION = "grounded-v1"
COLORS = {"X": "Black", "O": "White"}
LESSONS = {
    "forced_move": {
        "title": "Recognize a forced move",
        "text": "When only one square is legal, you must play it. To study a decision you could change, revisit an earlier turn with more than one legal move.",
        "question": "At which earlier turn did you still have a choice?",
    },
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
    facts = []
    if result is not None:
        winner = "The game was a draw" if result["winner"] == "draw" else f"{COLORS[result['winner']]} won"
        facts.append(fact("result", f"You played {COLORS[review['human_color']]}. {winner}: Black {result['black_count']}, White {result['white_count']}.", "outcome"))
    adopted = review["hint_adoption"]
    facts.append(fact("adoption", f"You followed hints on {adopted['adopted_turns']} of {adopted['shown_turns']} turns with a displayed hint.", "hints"))
    for hint in review["hints"]:
        entry = next((item for item in review["evidence"] if hint["hint_id"] in item["shown_hint_ids"]), None)
        if entry is None:
            event = next((item for item in review.get("history", [])
                          if item["revision"] == hint["revision"] + 1 and item["kind"] == "move"), None)
            if event:
                entry = {"actual_move": event["coordinate"]}
        choice = (f"You played {entry['actual_move']} and {'followed it' if entry['actual_move'] == hint['recommended_move'] else 'chose a different move'}."
                  if entry else "No subsequent player move is recorded.")
        facts.append(fact(f"hint:{hint['hint_id']}", f"At position {hint['revision']}, the displayed hint was {hint['recommended_move']}. {choice}", "hints", hint["revision"]))
    facts.append(fact("outcome_limit", "A better search estimate does not guarantee a win. The original result does not establish what would happen after an unplayed alternative; a saved replay proves only that replay's result.", "outcome"))
    for branch in review.get("branch_results", []):
        outcome = branch["result"]
        facts.append(fact(f"branch:{branch['game_id']}", f"The saved hint replay from position {branch['parent_revision']} finished Black {outcome['black_count']}, White {outcome['white_count']}. It used the original opponent configuration.", "outcome", branch["parent_revision"]))
    return facts


def position_facts(item: dict[str, Any], extra_moves: set[str] | None = None, comparison_move: str | None = None):
    revision, actor = item["revision"], item["actor"]
    actual = item["actual_move"]
    assessment = assess_decision(item, actual)
    recommended = comparison_move or reference_move(item, actual)
    has_comparison = recommended is not None
    recommended = recommended or actual
    candidates = {entry["coordinate"]: entry for entry in item["analysis"]["candidates"]}
    comparisons = {entry["coordinate"]: entry for entry in item["comparisons"]}
    played, best = candidates[actual], candidates[recommended]
    a, b = comparisons[actual], comparisons[recommended]
    prefix = f"p{revision}:"
    if assessment["status"] == "forced":
        decision = (f"At position {revision}, {COLORS[actor]} played {actual}." if item.get("is_played", True)
                    else f"At position {revision}, {COLORS[actor]} must play {actual}; no move has been recorded yet.")
        consequence = (f" After {actual}, {COLORS[opponent(actor)]} can take "
                       + ", ".join(a["opponent_corners"]) + ".") if a["opponent_corners"] else ""
        return [fact(prefix + "decision", decision, "forced_move", revision),
                fact(prefix + "forced_move", f"{actual} is the only legal move for {COLORS[actor]}. "
                     "There is no alternative to compare on this turn." + consequence
                     + " Revisit an earlier turn with more than one legal move to study a choice you could change.",
                     "forced_move", revision)], ["forced_move"]
    score_kind = "exact endgame scores under best play" if assessment["score_kind"] == "exact" else "search scores; non-exact values are estimates"
    judgment = (" This is one of the equally highest-rated moves."
                if assessment["status"] == "tied_best" else " This is the highest-rated legal move."
                if assessment["status"] == "best" else f" The search rates {assessment['best_moves'][0]} higher.")
    difference = abs(played["score"] - best["score"])
    facts = [
        fact(prefix + "decision", f"At position {revision}, {COLORS[actor]} "
             + (f"played {actual}." if item.get("is_played", True) else
                f"is comparing {actual}; the recorded move was {item['recorded_move']}." if item.get("recorded_move") else
                f"can play {actual}; no move has been recorded yet.")
             + judgment + f" There are {assessment['legal_move_count']} legal moves. This assessment is separate from any hint shown during play.", "comparison", revision),
        fact(prefix + "score", (f"From {COLORS[actor]}'s perspective, {actual} scores {played['score']:g} and {recommended} scores {best['score']:g}. The difference is {difference:g}; these are {score_kind}. Higher scores favor this player."
             if has_comparison else f"From {COLORS[actor]}'s perspective, {actual} scores {played['score']:g} ({score_kind}). No legal move has a higher score."), "comparison", revision),
        fact(prefix + "mobility", f"After {actual}, {COLORS[opponent(actor)]} has {a['opponent_moves']} legal replies"
             + (f"; after {recommended}, {b['opponent_moves']}. Reply count alone does not explain the search preference." if has_comparison else ". Reply count alone does not explain the move's rating."), "mobility", revision),
        fact(prefix + "frontier", f"After {actual}, the frontier-disc difference is {a['frontier_difference']}"
             + (f"; after {recommended}, {b['frontier_difference']}" if has_comparison else "")
             + f", counting {COLORS[actor]}'s frontier discs minus the opponent's.", "frontier", revision),
    ]
    lessons = ["comparison", "mobility", "frontier"]
    for move in dict.fromkeys((actual, recommended)):
        line = " → ".join(candidates[move]["principal_variation"])
        facts.append(fact(prefix + f"line_{move}", f"One searched continuation at position {revision}: {line}. This line is illustrative; it does not include every legal reply.", "comparison", revision))
    if a["corner"] or b["corner"] or a["opponent_corners"] or b["opponent_corners"]:
        corners = lambda value: ", ".join(value) or "none"
        facts.append(fact(prefix + "corners", f"Immediate corner replies for {COLORS[opponent(actor)]}: after {actual}, {corners(a['opponent_corners'])}"
                          + (f"; after {recommended}, {corners(b['opponent_corners'])}" if has_comparison else "")
                          + "." + (f" {recommended} itself occupies a corner." if b["corner"] else ""), "corners", revision))
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
    if assessment["score_kind"] == "exact":
        facts.append(fact(prefix + "endgame", f"Exact endgame score under best play: {actual} {played['score']:g}"
                          + (f", {recommended} {best['score']:g}" if has_comparison else "")
                          + f", from {COLORS[actor]}'s perspective.", "endgame", revision))
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


def verified_teaching_facts(teaching, revision):
    facts = []
    for choice in teaching["choices"]:
        continuation = choice.get("continuation_lesson")
        if continuation:
            ray = continuation["capture_line"]
            mechanism = (f"The disc gained at {ray[-1]} by the root move anchors the later capture from {ray[0]}."
                         if continuation["kind"] == "anchor" else
                         f"The opponent can flip back newly gained discs: {', '.join(continuation['recaptured'])}."
                         if continuation["kind"] == "recapture" else
                         f"The opponent can use the disc at {ray[-1]} to capture from {ray[0]}.")
            facts.append(fact(f"p{revision}:continuation_{choice['coordinate']}",
                              f"In the displayed {choice['coordinate']} continuation, {mechanism} "
                              f"Verified capture line: {' → '.join(ray)}. This demonstrates a local mechanism, "
                              "not the reason for the full search evaluation or a forced continuation.",
                              "comparison", revision))
        proof = choice["corner_proof"]
        if not proof:
            continue
        attack = proof["attack"]
        action = f"take {proof['target']} immediately" if attack == proof["target"] else (
            f"play {attack}; every legal defense then still permits {proof['target']} on the next turn")
        facts.append(fact(f"p{revision}:proof_{choice['coordinate']}",
                          f"After {choice['coordinate']}, {COLORS[proof['attacker']]} can {action}. "
                          "This is a rules-verified corner threat within three plies after the root move; "
                          "it does not establish the reason for the full search-score difference.", "corners", revision))
    insight = teaching["insight"]
    contrast = teaching.get("decision_contrast")
    if contrast:
        changes = []
        for witness in (contrast["removed_reply"], contrast["added_reply"]):
            if witness:
                cells = ", ".join(f"{entry['coordinate']}: {entry['available']} versus {entry['blocked']}"
                                  for entry in witness["changes"])
                changes.append(f"{COLORS[witness['actor']]} can play {witness['coordinate']} after "
                               f"{witness['available_after']}, but it is illegal after {witness['blocked_after']}. "
                               f"One verified capture line is {' → '.join(witness['capture_line'])}; "
                               f"the alternative board changes {cells}.")
        facts.append(fact(f"p{revision}:decision_contrast", " ".join(changes)
                          + " Both complete immediate reply sets were checked. These are opportunity changes, "
                          "not proof of the reason for the full search-score gap; fewer replies alone do not imply a better move.",
                          "comparison", revision))
    if insight["kind"] == "corner_defense":
        facts.append(fact(f"p{revision}:defense", f"After {insight['better_move']}, every legal first reply "
                          f"has a defense that prevents {insight['target']} on the following turn. "
                          "This is verified within three plies after the root move, not permanent corner safety.",
                          "corners", revision))
    return facts


def review_context(review: dict[str, Any], question: str | None, revision: int | None = None) -> dict[str, Any]:
    requested = {int(value) for value in re.findall(r"(?:position(?:\s+revision)?|revision|局面)\s*(\d+)", question or "", re.IGNORECASE)}
    if revision is not None and requested - {revision}:
        raise AppError("REVIEW_POSITION", "Move to the requested position before asking about it", 422)
    evidence = review.get("evidence", review["key_moves"])
    if revision is not None:
        selected = [item for item in evidence if item["revision"] == revision]
    elif requested:
        selected = [item for item in evidence if item["revision"] in requested]
        if len(requested) > 3:
            raise AppError("REVIEW_POSITION", "Ask about at most three positions at a time", 422)
    else:
        selected = select_key_moves(evidence, review["human_color"])
    extra = set(re.findall(r"(?<![a-z0-9])[a-h][1-8](?![a-z0-9])", question or "", re.IGNORECASE))
    positions = []
    for original in selected:
        if original["actor"] != review["human_color"]:
            raise AppError("REVIEW_OPPONENT", "Choose one of your own turns for teaching", 422)
        item = original if original.get("comparisons") else enrich_evidence(original)
        view = review.get("teaching_view") if revision == item["revision"] else None
        if view:
            item = {**item, "actual_move": view["selected_move"],
                    "is_played": view["assessment"]["is_played"], "recorded_move": view["recorded_move"]}
        teaching = view["teaching"] if view else review.get("teaching_comparison") if revision == item["revision"] else None
        reference = next((choice["coordinate"] for choice in teaching["choices"]
                          if choice["coordinate"] != item["actual_move"]), None) if teaching else None
        facts, lessons = position_facts(item, {move.lower() for move in extra}, reference)
        if teaching and assess_decision(item, item["actual_move"])["status"] != "forced":
            teaching_facts = verified_teaching_facts(teaching, item["revision"])
            facts.extend(teaching_facts)
            if any(entry["topic"] == "corners" for entry in teaching_facts) and "corners" not in lessons:
                lessons.append("corners")
        if view:
            line = " → ".join(view["line"]) or "before the selected move"
            last = (f"Last move: {COLORS[view['actor']]} {view['line'][-1]}, flipping "
                    + (", ".join(view["flipped"]) or "no discs") + ". ") if view["line"] else ""
            turn = (f"{COLORS[view['turn']]} to move; legal squares: "
                    + (", ".join(view["legal_moves"]) or "none; this player must pass")) if view["turn"] else "The game has ended"
            facts.append(fact(f"p{item['revision']}:view", f"The question refers to the {view['selected_move']} line: {line}. "
                              + last + turn + ". Scores describe the root choice, not this later board.",
                              "comparison", item["revision"]))
        positions.append({"revision": item["revision"], "actor": COLORS[item["actor"]],
                          "decision": assess_decision(item, item["actual_move"]),
                          **({"view": view} if view else {}),
                          "human": item["actor"] == review["human_color"], "facts": facts,
                          "allowed_lessons": lessons})
    for requested_revision in sorted(requested - {item["revision"] for item in positions}):
        position = pass_context(review, requested_revision)
        if position is None:
            raise AppError("REVIEW_POSITION", "Choose a saved position before a move or pass", 422)
        if not position["human"]:
            raise AppError("REVIEW_OPPONENT", "Choose one of your own turns for teaching", 422)
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
    moves = set(re.findall(r"(?<![a-z0-9])[a-h][1-8](?![a-z0-9])", text))
    if not moves and any(word in text for word in ("guarantee", "guaranteed", "would i win", "would i have won", "final result", "保证获胜", "一定赢", "一定能赢", "能赢吗", "最终结果")):
        return CoachingPlan(topic="outcome", selections=[])
    if not moves and any(word in text for word in ("hint", "提示", "推荐点")) and any(word in text for word in ("follow", "adopt", "ignore", "display", "shown", "采用", "按照", "显示", "采纳")):
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
        if f"p{selection.revision}:view" in facts:
            required.append(f"p{selection.revision}:view")
        if f"p{selection.revision}:score" in facts:
            required.append(f"p{selection.revision}:score")
        if context["task"] == "question" and f"p{selection.revision}:mobility" in facts:
            required.append(f"p{selection.revision}:mobility")
        identifiers = list(dict.fromkeys([*required, *selection.fact_ids]))
        cards.append({"revision": selection.revision, "facts": [facts[key] for key in identifiers],
                      "lesson_id": selection.lesson_id, "lesson": LESSONS[selection.lesson_id]})
    summary = context["summary_facts"]
    answer_facts = []
    if context["task"] == "review":
        answer_facts = summary[:2]
        blocks = [item["text"] for item in answer_facts]
    elif plan.topic == "hints":
        answer_facts = [item for item in summary if item["topic"] == "hints"]
        blocks = [item["text"] for item in answer_facts]
    elif plan.topic == "outcome":
        answer_facts = [item for item in summary if item["topic"] == "outcome"]
        blocks = [item["text"] for item in answer_facts]
    elif plan.topic == "unsupported":
        blocks = ["The saved game evidence does not answer that question. Ask about a move, displayed hints, or the game's result."]
    else:
        blocks = []
    for card in cards:
        blocks.append(" ".join(item["text"] for item in card["facts"]))
        blocks.append(card["lesson"]["text"])
    if (context["task"] == "question" and plan.topic in ("comparison", "strategy", "hints")
            and re.search(r"\b(win|won|winning|guarantee|guaranteed|victory)\b|获胜|赢|保证", context["question"], re.IGNORECASE)):
        boundary = next(item for item in summary if item["id"] == "outcome_limit")
        blocks.append(boundary["text"])
        answer_facts.append(boundary)
    return {"text": "\n\n".join(blocks), "coaching": cards,
            "answer_facts": answer_facts, "topic": plan.topic}
