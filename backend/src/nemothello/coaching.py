import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from nemothello.board_features import CORNERS, candidate_features
from nemothello.concepts import concept_facts, concept_focus, concept_profile
from nemothello.decision import assess_decision, reference_move
from nemothello.errors import AppError
from nemothello.rules import apply_move, flips, legal_moves, opponent

REVIEW_VERSION = "grounded-v1"
COLORS = {"X": "Black", "O": "White"}
LANGUAGES = {"en": "English", "zh": "Simplified Chinese"}
# Displayed text limits, so an answer fits in a few short sentences
TEXT_LIMITS = {"English": 480, "Simplified Chinese": 160}
VALUE_MEANINGS = {
    "legal_moves": "number of legal moves for the player at this position",
    "replies": "legal replies the opponent has after this move (in Chinese: 应对, not 回合)",
    "flips": "opponent discs this move flips",
    "corner_replies": "corners the opponent could take on the next turn",
    "exposed": "discs this move flips that then touch an empty square, not counting edge discs",
    "safe_replies": "opponent replies that do not let you take a new corner",
    "stable_gained": "your discs that become impossible to flip after this move",
    "region": "empty squares in the group of touching empty squares where this move is played",
}
LESSONS = {
    "forced_move": {
        "title": "Recognize a forced move",
        "text": "When only one square is legal, you must play it. Follow the continuation to understand which discs and opportunities it changes.",
        "question": "What changes after this forced move?",
    },
    "comparison": {
        "title": "Compare what each move changes",
        "text": "Compare what each move does on the board: which discs it flips, which replies it gives the opponent, and which capture lines those replies complete. Immediate disc gains alone do not decide a move.",
        "question": "After each move, what can the opponent do next?",
    },
    "quiet_move": {
        "title": "Play quiet moves",
        "text": "A disc next to an empty square can be attacked from that square. A quiet move flips discs that are already surrounded, so it gives the opponent few new places to play.",
        "question": "Which discs does this move flip next to empty squares?",
    },
    "mobility": {
        "title": "Leave the opponent only bad moves",
        "text": "Count the opponent's safe replies, not just its replies. A reply that lets you take a corner is a bad move for the opponent. When the opponent runs out of safe moves, it has to give you something.",
        "question": "After this move, which replies are safe for the opponent?",
    },
    "stable_discs": {
        "title": "Build discs that cannot be flipped",
        "text": "A disc that can never be flipped again is stable. Corners are always stable, and discs packed against a corner along the edge can become stable too.",
        "question": "Which of your discs can no longer be flipped after this move?",
    },
    "parity": {
        "title": "Count the empty regions",
        "text": "Near the end, empty squares split into separate regions. If you play first into a region with an odd number of empty squares, you can often also make the last move there.",
        "question": "How many empty squares are in the region where you play?",
    },
    "corners": {
        "title": "Check corner access",
        "text": "A disc in a corner cannot be flipped. Before choosing a move, check whether the opponent can take a corner on the next turn. Corner access is one feature of the position, not a replacement for comparing the search results.",
        "question": "Does either move give the opponent an immediate corner?",
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
        "title": "Play out the endgame",
        "text": "Near the end, Edax can search to the last move. Explain which squares remain, who can play them, and which discs each move keeps. Later mistakes can still change a played game's result.",
        "question": "Which remaining squares decide the final count?",
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


def side(color: str, human: str) -> str:
    return "you" if color == human else "the opponent"


def cell_owner(value: str, human: str) -> str:
    return "empty" if value == "." else "yours" if value == human else "the opponent's"


def fact(identifier, text, topic, revision=None):
    return {"id": identifier, "text": text, "topic": topic, "revision": revision}


def summary_facts(review: dict[str, Any]) -> list[dict[str, Any]]:
    result = review["result"]
    facts = []
    if result is not None:
        winner = "The game was a draw" if result["winner"] == "draw" else side(result["winner"], review["human_color"]).capitalize() + " won"
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
    facts.append(fact("outcome_limit", "Following the Edax recommendation does not guarantee a win. The original result does not establish what would happen after an unplayed alternative; a saved replay proves only that replay's result.", "outcome"))
    for branch in review.get("branch_results", []):
        outcome = branch["result"]
        facts.append(fact(f"branch:{branch['game_id']}", f"The saved hint replay from position {branch['parent_revision']} finished Black {outcome['black_count']}, White {outcome['white_count']}. It used the original opponent configuration.", "outcome", branch["parent_revision"]))
    return facts


def position_facts(item: dict[str, Any], comparison_move: str | None = None):
    revision = item["revision"]
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
        decision = (f"At position {revision}, you played {actual}." if item.get("is_played", True)
                    else f"At position {revision}, you must play {actual}; no move has been recorded yet.")
        consequence = (f" After {actual}, the opponent can take "
                       + ", ".join(a["opponent_corners"]) + ".") if a["opponent_corners"] else ""
        return [fact(prefix + "decision", decision, "forced_move", revision),
                fact(prefix + "forced_move", f"{actual} is your only legal move. "
                     "There is no alternative to compare on this turn." + consequence,
                     "forced_move", revision)], ["forced_move"], {"focus": [], "values": {}}
    judgment = (" Edax recommends this move together with another equally good move."
                if assessment["status"] == "tied_best" else " Edax recommends this move."
                if assessment["status"] == "best" else f" Edax recommends {assessment['best_moves'][0]} instead.")
    facts = [
        fact(prefix + "decision", f"At position {revision}, you "
             + (f"played {actual}." if item.get("is_played", True) else
                f"are comparing {actual}; the recorded move was {item['recorded_move']}." if item.get("recorded_move") else
                f"can play {actual}; no move has been recorded yet.")
             + judgment + f" There are {assessment['legal_move_count']} legal moves. This assessment is separate from any hint shown during play.", "comparison", revision),
    ]
    moves = list(dict.fromkeys((actual, recommended)))
    board = tuple(item["analysis"]["board"])
    profiles = {move: concept_profile(board, item["actor"], move) for move in moves}
    extra, lessons, values = concept_facts(profiles, moves, revision)
    facts += extra
    lessons = ["comparison", *lessons]
    if has_comparison and played["score"] != best["score"]:
        worse, better = sorted(moves, key=lambda move: candidates[move]["score"])
        focus = concept_focus(profiles, worse, better)
    else:
        focus = concept_focus(profiles, None, actual)
    if has_comparison and (a["corner"] != b["corner"] or set(a["opponent_corners"]) != set(b["opponent_corners"])):
        focus = ["corners", *focus]
    for move in dict.fromkeys((actual, recommended)):
        line = " → ".join(candidates[move]["principal_variation"])
        facts.append(fact(prefix + f"line_{move}", f"One searched continuation at position {revision}: {line}. This line is illustrative; it does not include every legal reply.", "comparison", revision))
    if a["corner"] or b["corner"] or a["opponent_corners"] or b["opponent_corners"]:
        corners = lambda value: ", ".join(value) or "none"
        facts.append(fact(prefix + "corners", f"Immediate corner replies for the opponent: after {actual}, {corners(a['opponent_corners'])}"
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
                texts.append(f"After {move}, " + ("the opponent must pass and you move again." if entry["own_moves"] else "neither player can move, so the game ends."))
        facts.append(fact(prefix + "pass", " ".join(texts), "pass", revision))
        lessons.append("pass")
    if assessment["score_kind"] == "exact":
        standing = lambda score: "ahead" if score > 0 else "behind" if score < 0 else "level"
        facts.append(fact(prefix + "endgame", f"Edax searched to the end of the game. With best play from both "
                          f"sides, you finish {standing(played['score'])} after {actual}"
                          + (f" and {standing(best['score'])} after {recommended}" if has_comparison else "")
                          + ". A played game can still change through later mistakes.", "endgame", revision))
        lessons.append("endgame")
    return facts, lessons, {"focus": [prefix + name for name in focus], "values": values}


def position_values(item: dict[str, Any]) -> dict[str, Any]:
    revision, actor = item["revision"], item["actor"]
    board = tuple(item["analysis"]["board"])
    comparisons = {entry["coordinate"]: entry for entry in item["comparisons"]}
    candidates = item["analysis"]["candidates"]
    values: dict[str, Any] = {f"p{revision}.legal_moves": len(candidates)}
    for candidate in candidates:
        move = candidate["coordinate"]
        entry = comparisons[move]
        key = f"p{revision}.{move}"
        values.update({
            f"{key}.replies": entry["opponent_moves"], f"{key}.flips": len(flips(board, actor, move)),
        })
        if entry["opponent_corners"]:
            values[f"{key}.corner_replies"] = entry["opponent_corners"]
    return values


def summary_values(review: dict[str, Any]) -> dict[str, Any]:
    adopted = review["hint_adoption"]
    values = {"hints.shown": adopted["shown_turns"], "hints.adopted": adopted["adopted_turns"]}
    if review["result"] is not None:
        values.update({"result.black": review["result"]["black_count"],
                       "result.white": review["result"]["white_count"]})
    return values


def move_fact(position: dict[str, Any], move: str) -> dict[str, Any]:
    revision = position["revision"]
    values = position["values"]
    key = f"p{revision}.{move}"
    return fact(f"p{revision}:{move}", f"At position {revision}, {move} is legal; it leaves "
                f"{values[key + '.replies']} opponent replies.", "comparison", revision)


def pass_context(review: dict[str, Any], revision: int):
    board = tuple(review["initial_board"])
    for event in review["history"]:
        if event["kind"] == "pass" and event["revision"] - 1 == revision:
            actor = event["actor"]
            if legal_moves(board, actor) or not legal_moves(board, opponent(actor)):
                raise AppError("REPLAY_MISMATCH", "Recorded pass does not match the board", 500)
            text = f"At position {revision}, you had no legal move and passed. The opponent could still move. The pass did not change the board or disc counts."
            return {"revision": revision,
                    "human": actor == review["human_color"], "allowed_lessons": ["pass"], "values": {}, "focus": [],
                    "facts": [fact(f"p{revision}:decision", f"At position {revision}, you passed.", "pass", revision),
                              fact(f"p{revision}:pass", text, "pass", revision)]}
        if event["kind"] == "move":
            board = apply_move(board, event["actor"], event["coordinate"])
    return None


def verified_teaching_facts(teaching, revision, human):
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
                              f"In the displayed {choice['coordinate']} continuation: {mechanism} "
                              f"Verified capture line: {' → '.join(ray)}. This shows one local mechanism, "
                              "not a forced continuation.",
                              "comparison", revision))
        proof = choice["corner_proof"]
        if not proof or not proof['forced']:
            continue
        attack = proof["attack"]
        action = f"take {proof['target']} immediately" if attack == proof["target"] else (
            f"play {attack}; every legal defense then still permits {proof['target']} on the next turn")
        facts.append(fact(f"p{revision}:proof_{choice['coordinate']}",
                          f"After {choice['coordinate']}, {side(proof['attacker'], human)} can {action}. "
                          "This is a rules-verified corner threat within three plies after the root move.",
                          "corners", revision))
    insight = teaching["insight"]
    witness = insight.get('witness')
    if witness:
        opportunity = witness['opportunity']
        prefix = ' → '.join(witness['prefix']) or 'no further moves'
        cells = ', '.join(f"{entry['coordinate']}: {cell_owner(entry['available'], human)} versus "
                          f"{cell_owner(entry['blocked'], human)}" for entry in opportunity['changes'])
        facts.append(fact(f'p{revision}:corner_contrast',
                          f"Compare {opportunity['available_after']} and {opportunity['blocked_after']} "
                          f"after the same further sequence ({prefix}). "
                          f"Only in the {opportunity['available_after']} variation is there a capture line for "
                          f"{side(opportunity['actor'], human)} from {opportunity['coordinate']}: "
                          f"{' → '.join(opportunity['capture_line'])}. Changed cells: {cells}. "
                          "This compares capture geometry on those boards; it does not let that player "
                          "move out of turn.",
                          'corners', revision))
    contrast = teaching.get("decision_contrast")
    if contrast:
        changes = []
        for witness in (contrast["removed_reply"], contrast["added_reply"]):
            if witness:
                cells = ", ".join(f"{entry['coordinate']}: {cell_owner(entry['available'], human)} versus "
                                  f"{cell_owner(entry['blocked'], human)}" for entry in witness["changes"])
                changes.append(f"{side(witness['actor'], human).capitalize()} can play {witness['coordinate']} after "
                               f"{witness['available_after']}, but it is illegal after {witness['blocked_after']}. "
                               f"One verified capture line is {' → '.join(witness['capture_line'])}; "
                               f"the alternative board changes {cells}.")
        facts.append(fact(f"p{revision}:decision_contrast", " ".join(changes)
                          + " Both complete immediate reply sets were checked. These are opportunity changes; "
                          "fewer replies alone do not imply a better move.",
                          "comparison", revision))
    if insight["kind"] == "corner_defense":
        response = ("either ends the game without that corner or has a defense that prevents it on the following turn. "
                    if any(entry['defense'] is None for entry in insight['proof']['refutations']) else
                    f"has a defense that prevents {insight['target']} on the following turn. ")
        facts.append(fact(f"p{revision}:defense", f"After {insight['better_move']}, every legal first reply "
                          + response +
                          "This is verified within three plies after the root move, not permanent corner safety.",
                          "corners", revision))
        if insight['other_threats']:
            targets = ', '.join(proof['target'] for proof in insight['other_threats'])
            facts.append(fact(f'p{revision}:other_corners',
                              f"After {insight['better_move']}, other corner threats remain: {targets}. "
                              "Each is forced within the opponent's next two turns under the checked rules. "
                              "Defending the compared corner does not secure the other corners.",
                              'corners', revision))
    return facts


def position_focus(facts: list[dict[str, Any]], revision: int, concepts: list[str]) -> list[str]:
    ids = [entry["id"] for entry in facts]

    def unique(prefix: str) -> str | None:
        # A fact that holds for both moves does not separate them
        matches = [key for key in ids if key.startswith(prefix)]
        return matches[0] if len(matches) == 1 else None

    proof = next((key for key in (f"p{revision}:corner_contrast", f"p{revision}:defense") if key in ids), None)
    ranked = [proof or unique(f"p{revision}:proof_"), *concepts[:1 if concepts[:1] == [f"p{revision}:corners"] else 0],
              f"p{revision}:decision_contrast" if f"p{revision}:decision_contrast" in ids else None,
              unique(f"p{revision}:continuation_"), *concepts]
    return list(dict.fromkeys(key for key in ranked if key))[:3]


def review_context(review: dict[str, Any], question: str | None, revision: int | None = None,
                   language: str = "en") -> dict[str, Any]:
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
        facts, lessons, concepts = position_facts(item, reference)
        if teaching and assess_decision(item, item["actual_move"])["status"] != "forced":
            teaching_facts = verified_teaching_facts(teaching, item["revision"], item["actor"])
            facts.extend(teaching_facts)
            if any(entry["topic"] == "corners" for entry in teaching_facts) and "corners" not in lessons:
                lessons.append("corners")
        if view:
            line = " → ".join(view["line"]) or "before the selected move"
            last = (f"Last move: {side(view['actor'], item['actor'])} played {view['line'][-1]}, flipping "
                    + (", ".join(view["flipped"]) or "no discs") + ". ") if view["line"] else ""
            turn = (f"Next to move: {side(view['turn'], item['actor'])}; legal squares: "
                    + (", ".join(view["legal_moves"]) or "none; this player must pass")) if view["turn"] else "The game has ended"
            facts.append(fact(f"p{item['revision']}:view", f"The question refers to the {view['selected_move']} line: {line}. "
                              + last + turn + ". The recommendation is for the root choice, not this later board.",
                              "comparison", item["revision"]))
        earlier = review.get('earlier_decision') if revision == item['revision'] else None
        if earlier and earlier['status'] == 'verified':
            link = earlier['link']
            move_number = sum(event['kind'] == 'move' and event['revision'] <= link['revision']
                              for event in review['history']) + 1
            topic = 'forced_move' if assess_decision(item, item['actual_move'])['status'] == 'forced' else 'corners'
            facts.append(fact(f"p{item['revision']}:earlier_decision",
                              f"In the recorded history, at move {move_number}, "
                              f"{side(link['actor'], item['actor'])} played {link['recorded_move']}, allowing a forced "
                              f"{link['target']} capture within the next two opponent turns. "
                              f"The recommended {link['recommended_move']} offers a defense within that horizon. "
                              "The same bounded threat remained at every subsequent recorded state up to this decision. "
                              "This is a verified local connection, not proof of permanent corner safety, "
                              "or a different game result.", topic, item['revision']))
            if topic not in lessons:
                lessons.append(topic)
        positions.append({"revision": item["revision"],
                          "decision": assess_decision(item, item["actual_move"]),
                          "player_reflection": review.get("player_reflection") if revision == item["revision"] else None,
                          **({"view": view} if view else {}),
                          "human": item["actor"] == review["human_color"], "facts": facts,
                          "focus": position_focus(facts, item["revision"], concepts["focus"]),
                          "values": {**position_values(item), **concepts["values"]}, "allowed_lessons": lessons})
    for requested_revision in sorted(requested - {item["revision"] for item in positions}):
        position = pass_context(review, requested_revision)
        if position is None:
            raise AppError("REVIEW_POSITION", "Choose a saved position before a move or pass", 422)
        if not position["human"]:
            raise AppError("REVIEW_OPPONENT", "Choose one of your own turns for teaching", 422)
        positions.append(position)
    return {"summary_facts": summary_facts(review), "summary_values": summary_values(review),
            "positions": positions, "value_meanings": VALUE_MEANINGS, "lessons": LESSONS, "question": question,
            "language": LANGUAGES[language], "task": "question" if question else "review"}


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
    fact_ids: list[str] = Field(min_length=1, max_length=6)
    lesson_id: str
    text: str | None = Field(default=None, max_length=700)


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(default="", max_length=900)
    fact_ids: list[str] = Field(default_factory=list, max_length=8)


class CoachingPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: Literal["review", "comparison", "hints", "outcome", "strategy", "unsupported"]
    answer: Answer = Field(default_factory=Answer)
    selections: list[Selection] = Field(max_length=3)


SLOT = re.compile(r"\{([A-Za-z0-9_.]+)\}")
CITATION = re.compile(r"\s*[{（(]\s*(?:facts?\s*)?([A-Za-z0-9_:.\-]+(?:\s*[,，]\s*[A-Za-z0-9_:.\-]+)*)\s*[}）)]")
COORDINATE = re.compile(r"(?<![A-Za-z0-9])[a-h][1-8](?![A-Za-z0-9])", re.IGNORECASE)
ENGLISH_NUMBERS = {
    "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
    "fifty": 50, "sixty": 60,
}
CHINESE_DIGITS = {"两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
ENGLISH_NUMBER = re.compile(r"\b(" + "|".join(ENGLISH_NUMBERS) + r")\b", re.IGNORECASE)
# The numeral one appears in ordinary Chinese phrases, so only check two and above
# 两步都 means both moves, not a count
CHINESE_NUMBER = re.compile(r"(?!两步[都均各])([两二三四五六七八九十百]+)\s*[个种颗枚步手分子次条回轮]")
BOARD_LINE = re.compile(r"\b(?:row|rank) [1-8]\b|第 ?[1-8] ?行", re.IGNORECASE)
TOPIC_WORDS = (
    (re.compile(r"hint|提示|推荐点", re.IGNORECASE), {"hints"}, "a displayed-hint fact"),
    (re.compile(r"\bwin|\bwon\b|victory|赢|获胜|胜利|必胜", re.IGNORECASE),
     {"outcome", "endgame"}, "an outcome fact"),
    (re.compile(r"corner|(?<!视)角(?![度色])", re.IGNORECASE),
     {"corners", "corner_neighbor", "forced_move", "tool"}, "a corner fact or tool result"),
    (re.compile(r"\bpass|跳过|弃权", re.IGNORECASE), {"pass", "tool"}, "a pass fact or tool result"),
)

# Explain the board, not engine scores; address sides as you/opponent
SCORE_WORDS = re.compile(r"\bscor(?:e|es|ed|ing)\b|\brat(?:e|es|ed|ing|ings)\b|\bevaluat\w*|评分|得分|分数|分值|估值|盘差",
                         re.IGNORECASE)
SIDE_NAMES = re.compile(r"\b(?:Black|White)\b|\bthe player\b|黑方|白方|黑棋|白棋|玩家")
COORDINATE_RUN = re.compile(r"(?<![A-Za-z0-9])[a-h][1-8](?:(?:\s*(?:[,，、→/]|和|及|或|and|or)\s*|\s+)[a-h][1-8]){3,}",
                            re.IGNORECASE)
COMPARISON_WORDS = re.compile(r"更|比(?!如|较)|多于|少于|\b(?:more|fewer|less|greater|higher|lower|better|worse)\b",
                              re.IGNORECASE)
IDENTIFIER = re.compile(r"\b[a-z]+(?:_[a-z]+)+\b")


def available_facts(context: dict[str, Any], tool_facts=()) -> dict[str, dict[str, Any]]:
    facts = {item["id"]: item for item in context["summary_facts"]}
    for position in context["positions"]:
        facts.update((item["id"], item) for item in position["facts"])
    facts.update((item["id"], item) for item in tool_facts)
    return facts


def context_values(context: dict[str, Any], tool_facts=()) -> dict[str, Any]:
    values = dict(context["summary_values"])
    for position in context["positions"]:
        values.update(position["values"])
    for item in tool_facts:
        values.update(item["values"])
    return values


def known_coordinates(context: dict[str, Any], tool_facts=()) -> set[str]:
    evidence = json.dumps([context["summary_facts"], context["positions"], list(tool_facts)])
    return {move.lower() for move in COORDINATE.findall(evidence)}


def plan_schema(context: dict[str, Any], tool_facts=()) -> dict[str, Any]:
    positions = context["positions"]
    fact_ids = {"type": "array", "items": {"type": "string", "enum": list(available_facts(context, tool_facts))}}
    if positions:
        selection = {
            "type": "object", "additionalProperties": False,
            "required": ["revision", "fact_ids", "lesson_id", "text"],
            "properties": {
                "revision": {"type": "integer", "enum": [item["revision"] for item in positions]},
                "fact_ids": {**fact_ids, "minItems": 1, "maxItems": 6},
                "lesson_id": {"type": "string", "enum": sorted({lesson for item in positions
                                                                for lesson in item["allowed_lessons"]})},
                # Length is checked after placeholders are filled; a schema limit would cut the text
                "text": {"type": "string", "minLength": 1},
            },
        }
        selections = {"type": "array", "items": selection, "maxItems": len(positions)}
        if context["task"] == "review":
            selections["minItems"] = len(positions)
    else:
        selections = {"type": "array", "items": {"type": "object"}, "maxItems": 0}
    return {
        "type": "object", "additionalProperties": False,
        "required": ["topic", "answer", "selections"],
        "properties": {
            "topic": {"type": "string", "enum": ["review"] if context["task"] == "review"
                      else ["comparison", "hints", "outcome", "strategy", "unsupported"]},
            "answer": {"type": "object", "additionalProperties": False, "required": ["text", "fact_ids"],
                       "properties": {"text": {"type": "string", **({"maxLength": 0} if context["task"] == "review" else {})},
                                      "fact_ids": {**fact_ids, "maxItems": 8}}},
            "selections": selections,
        },
    }


def ungrounded(message: str) -> AppError:
    return AppError("COACH_UNGROUNDED", message, 502)


def value_source(key: str) -> str:
    head = key.split(".", 1)[0]
    return {"result": "result", "hints": "adoption"}.get(head, head)


def mask(pattern: re.Pattern, text: str) -> str:
    return pattern.sub(lambda match: " " * len(match.group()), text)


def excerpt(text: str, start: int, end: int) -> str:
    return "'" + text[max(0, start - 12):end + 12].strip() + "'"


def strip_citations(text: str, available: dict[str, Any]) -> tuple[str, list[str]]:
    cited = []

    def replace(match: re.Match) -> str:
        identifiers = [re.sub(r"\.text$", "", item.strip()) for item in re.split(r"[,，]", match.group(1))]
        # Models sometimes write p16.mobility for p16:mobility
        identifiers = [key if key in available else key.replace(".", ":", 1) for key in identifiers]
        if not all(identifier in available for identifier in identifiers):
            return match.group()
        cited.extend(identifiers)
        return ""

    return re.sub(r"\s*[（(]\s*[）)]", "", CITATION.sub(replace, text)).strip(), cited


def check_text(text: str, cited: list[dict[str, Any]], values: dict[str, Any],
               coordinates: set[str], label: str) -> list[str]:
    problems = []
    for match in SLOT.finditer(text):
        key = match.group(1)
        if key not in values:
            problems.append(f"{label} uses an unknown placeholder {{{key}}}")
            continue
        source = value_source(key)
        position = re.fullmatch(r"p(\d+)", source)
        supported = (any(item["revision"] == int(position.group(1)) for item in cited) if position
                     else any(item["id"] == source for item in cited))
        if not supported:
            problems.append(f"{label} uses {{{key}}} without citing a fact from {source}")
    # Same-length masking keeps offsets for excerpts
    bare = mask(SLOT, text)
    for match in re.finditer(r"\d+", mask(BOARD_LINE, mask(COORDINATE, bare))):
        problems.append(f"{label} writes {match.group()} directly in {excerpt(text, *match.span())}")
    # Number words are allowed only when a cited fact states them
    stated = {ENGLISH_NUMBERS[word.lower()] for item in cited
              for word in ENGLISH_NUMBER.findall(item["text"])}
    for match, value in [*((match, ENGLISH_NUMBERS[match.group().lower()])
                           for match in ENGLISH_NUMBER.finditer(bare)),
                         *((match, chinese_number(match.group(1)))
                           for match in CHINESE_NUMBER.finditer(bare))]:
        if value not in stated:
            problems.append(f"{label} writes {match.group()} directly in {excerpt(text, *match.span())}")
    for match in COORDINATE.finditer(bare):
        if match.group().lower() not in coordinates:
            problems.append(f"{label} mentions {match.group()}, which is not in the evidence")
    for match in SCORE_WORDS.finditer(bare):
        problems.append(f"{label} talks about engine scores in {excerpt(text, *match.span())}; "
                        "explain what happens on the board instead")
    for match in SIDE_NAMES.finditer(bare):
        problems.append(f"{label} names a side in {excerpt(text, *match.span())}; "
                        "write you and the opponent (你/对手)")
    for match in COORDINATE_RUN.finditer(text):
        problems.append(f"{label} lists too many squares in {excerpt(text, *match.span())}; "
                        "name at most three that matter")
    for match in IDENTIFIER.finditer(bare):
        problems.append(f"{label} shows the internal name {match.group()}; write plain words")
    if COMPARISON_WORDS.search(bare):
        compared: dict[tuple[str, str], dict[str, Any]] = {}
        for match in SLOT.finditer(text):
            parts = match.group(1).split(".")
            if len(parts) == 3 and match.group(1) in values:
                compared.setdefault((parts[0], parts[2]), {})[parts[1]] = values[match.group(1)]
        for (_, metric), by_move in compared.items():
            if len(by_move) > 1 and len({json.dumps(value) for value in by_move.values()}) == 1:
                problems.append(f"{label} compares {metric} for {' and '.join(by_move)}, but the values are "
                                "equal, so they are not a reason; leave them out")
    topics = {item["topic"] for item in cited}
    for pattern, required, name in TOPIC_WORDS:
        found = pattern.search(bare)
        if found and not topics & required:
            problems.append(f"{label} mentions {found.group()} without citing {name}")
    return problems


def chinese_number(text: str) -> int | None:
    tens, separator, ones = text.partition("十")
    if not separator:
        return CHINESE_DIGITS.get(text) if len(text) == 1 else None
    if (tens and tens not in CHINESE_DIGITS) or (ones and ones not in CHINESE_DIGITS):
        return None
    return (CHINESE_DIGITS[tens] if tens else 1) * 10 + (CHINESE_DIGITS[ones] if ones else 0)


def format_value(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def fill(text: str, values: dict[str, Any]) -> str:
    return SLOT.sub(lambda match: format_value(values[match.group(1)]), text)


def validate_plan(raw: str, context: dict[str, Any], tool_facts=()) -> CoachingPlan:
    try:
        plan = CoachingPlan.model_validate_json(raw)
    except ValidationError as exc:
        problem = exc.errors()[0]
        raise AppError("REVIEW_PLAN_INVALID", "The coach returned an invalid lesson plan: "
                       f"{'.'.join(str(part) for part in problem['loc'])} {problem['msg']}", 502) from exc
    available = available_facts(context, tool_facts)
    # Move inline citations like {t1} into fact_ids
    for part in [plan.answer, *plan.selections]:
        if part.text:
            part.text, inline = strip_citations(part.text, available)
            part.fact_ids = [*part.fact_ids, *(key for key in dict.fromkeys(inline) if key not in part.fact_ids)]
    positions = {item["revision"]: item for item in context["positions"]}
    question = context["task"] == "question"
    if question and (plan.topic == "review" or (plan.topic == "unsupported" and plan.selections)):
        raise AppError("REVIEW_PLAN_INVALID", "The coach returned an incompatible answer plan", 502)
    if question and not plan.answer.text.strip():
        raise AppError("REVIEW_PLAN_INVALID", "The coach did not write an answer to the question", 502)
    if question and plan.topic != "unsupported" and not plan.answer.fact_ids:
        raise AppError("REVIEW_PLAN_INVALID", "The coach answered without citing evidence", 502)
    if not question and (plan.topic != "review" or len(plan.selections) != len(positions)):
        raise AppError("REVIEW_PLAN_INVALID", "The coach did not cover the selected player decisions", 502)
    if not question and plan.answer.text.strip():
        raise AppError("REVIEW_PLAN_INVALID", "For task=review, leave answer.text empty and write in the selections", 502)
    if (not set(plan.answer.fact_ids) <= available.keys()
            or len(plan.answer.fact_ids) != len(set(plan.answer.fact_ids))):
        raise AppError("REVIEW_PLAN_INVALID", "The coach cited unavailable or repeated evidence", 502)
    seen = set()
    for selection in plan.selections:
        position = positions.get(selection.revision)
        if position is None or selection.revision in seen:
            raise AppError("REVIEW_PLAN_INVALID", "The coach referenced an unavailable or repeated position", 502)
        own = {item["id"]: item for item in position["facts"]}
        if (selection.lesson_id not in position["allowed_lessons"]
                or not set(selection.fact_ids) <= available.keys()
                or len(selection.fact_ids) != len(set(selection.fact_ids))
                or not any(own[key]["topic"] == selection.lesson_id for key in selection.fact_ids if key in own)):
            raise AppError("REVIEW_PLAN_INVALID", "The coach selected unsupported evidence or a lesson without evidence", 502)
        if not (selection.text or "").strip():
            raise AppError("REVIEW_PLAN_INVALID", f"The coach wrote no explanation for position {selection.revision}", 502)
        seen.add(selection.revision)
    values = context_values(context, tool_facts)
    coordinates = known_coordinates(context, tool_facts)
    problems, cited_by_cards = [], []
    for selection in plan.selections:
        cited = [available[key] for key in selection.fact_ids]
        problems += check_text(selection.text, cited, values, coordinates,
                               f"The explanation for position {selection.revision}")
        focus = positions[selection.revision].get("focus") or []
        if not question and focus and focus[0] not in selection.fact_ids:
            problems.append(f"The explanation for position {selection.revision} must build on its first focus "
                            f"fact {focus[0]}; cite it and explain what it shows")
        cited_by_cards.extend(cited)
    problems += check_text(plan.answer.text, [*(available[key] for key in plan.answer.fact_ids), *cited_by_cards],
                           values, coordinates, "The answer")
    limit = TEXT_LIMITS[context["language"]]
    for part, label in [*((item, f"The explanation for position {item.revision}") for item in plan.selections),
                        (plan.answer, "The answer")]:
        shown = SLOT.sub(lambda match: format_value(values.get(match.group(1), match.group())), part.text or "")
        if len(shown) > limit:
            problems.append(f"{label} has {len(shown)} characters; keep it under {limit}")
    if problems:
        raise ungrounded("Correct these problems: " + "; ".join(problems[:10]))
    return plan


def used_move_facts(text: str, positions: dict[int, dict[str, Any]], shown: list[dict[str, Any]]):
    covered = " ".join(item["text"] for item in shown)
    moves = dict.fromkeys(re.findall(r"\{p(\d+)\.([a-h][1-8])\.", text))
    return [move_fact(positions[int(revision)], move) for revision, move in moves
            if int(revision) in positions and move not in covered]


def render_plan(plan: CoachingPlan, context: dict[str, Any], tool_facts=()):
    positions = {item["revision"]: item for item in context["positions"]}
    available = available_facts(context, tool_facts)
    values = context_values(context, tool_facts)
    cards = []
    for selection in plan.selections:
        position = positions[selection.revision]
        own = {item["id"] for item in position["facts"]}
        required = [f"p{selection.revision}:decision"]
        if f"p{selection.revision}:view" in own:
            required.append(f"p{selection.revision}:view")
        if context["task"] == "question" and f"p{selection.revision}:mobility" in own:
            required.append(f"p{selection.revision}:mobility")
        facts = [available[key] for key in dict.fromkeys([*required, *selection.fact_ids])]
        if selection.text:
            facts.extend(used_move_facts(selection.text, positions, facts))
        cards.append({"revision": selection.revision, "facts": facts,
                      "lesson_id": selection.lesson_id, "lesson": LESSONS[selection.lesson_id],
                      "text": fill(selection.text, values) if selection.text else None})
    summary = context["summary_facts"]
    answer_facts = [available[key] for key in plan.answer.fact_ids]
    if context["task"] == "review":
        answer_facts = [*summary[:2], *(item for item in answer_facts if item not in summary[:2])]
    answer_facts.extend(used_move_facts(plan.answer.text, positions, answer_facts))
    answer = fill(plan.answer.text, values)
    written = [answer] if answer else []
    written.extend(card["text"] for card in cards if card["text"])
    if written:
        blocks = written
    else:
        blocks = [item["text"] for item in answer_facts]
        for card in cards:
            blocks.append(" ".join(item["text"] for item in card["facts"]))
            blocks.append(card["lesson"]["text"])
    if (context["task"] == "question" and plan.topic in ("comparison", "strategy", "hints")
            and re.search(r"\b(win|won|winning|guarantee|guaranteed|victory)\b|获胜|赢|保证", context["question"], re.IGNORECASE)
            and not any(item["id"] == "outcome_limit" for item in answer_facts)):
        boundary = next(item for item in summary if item["id"] == "outcome_limit")
        if not written:
            blocks.append(boundary["text"])
        answer_facts.append(boundary)
    return {"text": "\n\n".join(blocks), "answer": answer, "coaching": cards,
            "answer_facts": answer_facts, "topic": plan.topic}
