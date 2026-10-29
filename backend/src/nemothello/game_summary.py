import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from nemothello.board_features import CORNERS
from nemothello.coaching import LANGUAGES, game_summary_context, stage
from nemothello.errors import AppError
from nemothello.game_profile import game_profile
from nemothello.learning_goal import mechanism_text
from nemothello.rules import Position, coordinate, flips, opponent
from nemothello.summary_validation import (
    paragraph_problems,
    paragraph_style_notes,
    prepare_paragraph,
    presentation_problems,
    question_only,
    render_position_references,
    replace_terms,
)
from nemothello.teaching import compare_lesson

SUMMARY_VERSION = "game-presentation-v9"
# Characters of model-written text per paragraph; a lesson with a verified opening has no model text
SUMMARY_LIMITS = {"Simplified Chinese": {"game": 150, "lesson": 140, "practice": 50},
                  "English": {"game": 420, "lesson": 420, "practice": 160}}
SUMMARY_PROMPT = (
    "Write a short game summary for an Othello beginner: three paragraphs with purposes game, lesson and "
    "practice, each with its supporting fact_ids. Choose focus_position from the review position IDs, or null "
    "if none are available. Stay within the character limits in the message. "
    "game: one sentence with how many moves matched the recommendation and how many are worth reviewing, then, "
    "when a game fact describes a pattern, such as often flipping the most discs or giving the opponent a "
    "corner, one or two sentences on that pattern with at most two example moves, citing game facts. Do not count moves with only one legal "
    "square or give phase-by-phase statistics. Describe this game only, without a skill rank, guessed "
    "intentions, or forced praise. A hinted move is not unaided skill, and a forced move is not a decision. "
    "lesson: if the focus position has a lesson_opening, the app shows exactly that verified text as the lesson; "
    "leave the lesson text empty. Without a lesson_opening, explain the primary_fact in two or three sentences. "
    "If focus_position is null, state one thing the record shows, such as on how many choices hints were "
    "displayed, without saying what the hints did for the player or explaining the rules. "
    "practice: exactly one short question the player can ask themselves before a move in the next game, "
    "turning the lesson into a habit, with no coordinates and no statement before it. When hints were shown on "
    "most choices, it may ask which move they would pick before looking at the hint. "
    "Choose the learning priority from the evidence. Do not turn an isolated tactic into a repeated habit or "
    "the cause of the final result. Flipping fewer discs is not inherently better. A player's own move only "
    "turns opponent discs into their own color. Write in the requested language, as a teacher speaking to "
    "you/你 about the opponent/对手, in plain words a beginner knows. Avoid statistics reports, search scores, "
    "side colors, the result, headings, the engine's name, English words in Chinese text, and field names. To refer to a game "
    "move, write its position ID in braces, such as {review_A}; the app fills in the move number. Every "
    "coordinate must appear in the cited facts. Call submit_summary."
)
SUMMARY_CHECK_PROMPT = (
    "Audit the displayed Othello game summary against the supplied evidence. Return specific factual issues "
    "through check_summary; leave issues empty when the summary is supported. A lesson that opens with the "
    "played move and the recommended move comes from the rules engine and is correct. The practice question "
    "is a prompt for the player's next game, not a claim; reject it only if it contradicts the rules or the "
    "lesson. Every observation and board claim in the game and lesson paragraphs needs support from its cited "
    "facts. Check ownership, timing and alternatives, and whether a local result is exaggerated into a "
    "full-game cause or universal strategy. Resolve frequency references using the complete decisions. "
    "Do not infer player intention or skill level. A maximum-flip correlation is not a causal diagnosis. "
    "Reject only factual errors, unsupported conclusions, or advice that contradicts the rules or evidence. "
    "Wording, length, tone and teaching depth belong in style_notes, not issues; do not reject supported "
    "prose for presentation or because it paraphrases the evidence. If rejecting, name the unsupported claim "
    "and the relevant fact, with an actionable correction."
)


class SummaryParagraph(BaseModel):
    model_config = ConfigDict(extra="forbid")
    purpose: Literal["game", "lesson", "practice"]
    text: str
    fact_ids: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("purpose", mode="before")
    @classmethod
    def normalize_purpose(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


class SummaryDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paragraphs: list[SummaryParagraph] = Field(min_length=3, max_length=3)
    focus_position: str | None


class SummaryCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    issues: list[str] = Field(max_length=8)
    style_notes: list[str] = Field(default_factory=list, max_length=8)


def summary_references(review, revisions):
    items = {item["revision"]: item for item in review["evidence"]}
    return {f"review_{chr(65 + index)}": {
        "id": f"review_{chr(65 + index)}", "revision": revision,
        "move_number": sum(cell != "." for row in items[revision]["analysis"]["board"] for cell in row) - 3,
    } for index, revision in enumerate(revisions)}


def display_saved_summary(summary, review):
    positions = summary_references(review, [item["revision"] for item in review["key_moves"]])
    text, _ = render_position_references(summary["text"], positions, LANGUAGES[summary["language"]])
    return {**summary, "text": text}


def summary_evidence(review, revisions, language):
    profile = game_profile(review)
    items = {item["revision"]: item for item in review["evidence"] if item["actor"] == review["human_color"]}
    if not items:
        raise AppError("SUMMARY_UNAVAILABLE", "There are no saved player moves to summarize", 409)
    if any(revision not in items for revision in revisions):
        raise AppError("REVIEW_OPPONENT", "Summary lessons must be saved human moves", 422)
    references = {entry["revision"]: entry for entry in summary_references(review, revisions).values()}
    positions = []
    facts = list(profile["facts"])
    facts.append({"id": "game:rules", "topic": "rules", "revision": None,
                  "text": "Captures follow eight straight directions. A legal move brackets at least one opponent disc. "
                          "Two candidate moves can be compared on separate boards; those boards are alternatives, not successive turns."})
    context = game_summary_context(review, revisions, language) if revisions else {"positions": []}
    for position in context["positions"]:
        revision = position["revision"]
        item = items[revision]
        comparison = compare_lesson(review, revision, item["actual_move"])
        # Keep the primary mechanism and decision facts; full variations belong to the position lesson.
        relevant = {f"p{revision}:decision", *position["focus"]}
        selected = [{key: value for key, value in entry.items() if key != "frames"}
                    for entry in position["facts"] if entry["id"] in relevant]
        for entry in selected:
            if entry["id"] == f"p{revision}:decision":
                entry["text"] = f"You played {item['actual_move']}; the searched recommendation is {comparison['recommended_move']}."
        captures = {choice["coordinate"]: [coordinate(row, col) for row, col in
                    flips(tuple(item["analysis"]["board"]), item["actor"], choice["coordinate"])]
                    for choice in comparison["choices"]}
        selected.append({"id": f"p{revision}:root_flips", "topic": "comparison", "revision": revision,
                         "text": " ".join(f"Your {move} flips {', '.join(cells)} from the opponent's color to yours."
                                          for move, cells in captures.items())})
        goal = position["learning_goal"]
        mechanism = None
        if goal:
            mechanism = {"id": f"p{revision}:mechanism", "topic": "corners"
                         if goal["reply"] in CORNERS else "comparison", "revision": revision,
                         "text": mechanism_text(goal["changes"][0]["square"], goal, LANGUAGES[language],
                                                show_continuation=True).strip()
                         + consequence_text(goal, LANGUAGES[language], capture_is_next(item, goal))}
            selected.append(mechanism)
        facts.extend(selected)
        positions.append({**references[revision],
                          "phase": stage(item), "played": item["actual_move"],
                          "recommended": comparison["recommended_move"], "primary_fact": position["focus"][0]
                          if position["focus"] else f"p{revision}:decision",
                          "mechanism": mechanism})
    return {"language": LANGUAGES[language], "profile": {key: value for key, value in profile.items() if key != "facts"},
            "positions": positions, "facts": facts}


def summary_tool(evidence):
    schema = SummaryDraft.model_json_schema()
    schema["$defs"]["SummaryParagraph"]["properties"]["fact_ids"]["items"]["enum"] = [
        *fact_aliases(evidence).values()]
    schema["properties"]["focus_position"] = {
        "enum": [position["id"] for position in evidence["positions"]] or [None]}
    return {"type": "function", "function": {"name": "submit_summary",
            "description": "Write a game-specific coaching summary with supporting evidence", "parameters": schema}}


def summary_check_tool():
    return {"type": "function", "function": {"name": "check_summary",
            "description": "Identify factual issues separately from presentation suggestions", "parameters": SummaryCheck.model_json_schema()}}


def validate_summary_check(raw):
    try:
        result = SummaryCheck.model_validate_json(raw)
    except ValidationError as exc:
        raise AppError("REVIEW_PLAN_INVALID", "Return factual issues and style_notes for the summary audit", 502) from exc
    if result.issues:
        raise AppError("REVIEW_PLAN_INVALID", "; ".join(result.issues), 502)
    return {**result.model_dump(), "accepted": True}


def render_summary(raw, evidence):
    try:
        draft = SummaryDraft.model_validate_json(raw)
    except ValidationError as exc:
        raise AppError("REVIEW_PLAN_INVALID", "Write paragraphs with text and fact_ids, and focus_position", 502) from exc
    aliases = fact_aliases(evidence)
    available = {aliases[entry["id"]]: entry for entry in evidence["facts"] if entry["id"] in aliases}
    positions = {position["id"]: position for position in evidence["positions"]}
    if (positions and draft.focus_position not in positions) or (not positions and draft.focus_position is not None):
        raise AppError("REVIEW_PLAN_INVALID", "Choose focus_position from the supplied review positions", 502)
    cited_ids, problems, notes, shown = [], [], [], []
    roles = {paragraph.purpose: paragraph for paragraph in draft.paragraphs}
    if set(roles) != {"game", "lesson", "practice"}:
        raise AppError("REVIEW_PLAN_INVALID", "Include a game reflection, lesson, and practice", 502)
    draft.paragraphs = [roles[purpose] for purpose in ("game", "lesson", "practice")]
    language = evidence["language"]
    focus = positions.get(draft.focus_position)
    mechanism = focus["mechanism"] if focus else None
    limits = SUMMARY_LIMITS[language]
    for paragraph in draft.paragraphs:
        paragraph.text, paragraph.fact_ids = prepare_paragraph(
            paragraph.text, paragraph.fact_ids, available, positions, language)
        paragraph.text = replace_terms(paragraph.text, language)
        if paragraph.purpose == "practice":
            question = question_only(paragraph.text)
            if question is None:
                problems.append("End the practice paragraph with one short question for the next game")
            else:
                paragraph.text = question
        # Text the model wrote and the player sees
        own = paragraph.text
        text = own
        if paragraph.purpose == "lesson" and focus:
            # The lesson is about the focus position, so its facts are cited without costing a retry
            added = [aliases[focus["primary_fact"]]]
            if mechanism:
                # Only the verified move and mechanism are shown, so the lesson cannot overstate them
                own = ""
                text = lesson_opening(focus, language)
                added += [f"{focus['id']}_decision", aliases[mechanism["id"]]]
            paragraph.fact_ids = list(dict.fromkeys([*paragraph.fact_ids, *added]))
        # A practice question asserts nothing, so it needs no facts
        if not paragraph.fact_ids and paragraph.purpose != "practice":
            raise AppError("REVIEW_PLAN_INVALID", f"Support the {paragraph.purpose} paragraph with supplied fact_ids", 502)
        if not set(paragraph.fact_ids) <= available.keys():
            raise AppError("REVIEW_PLAN_INVALID", "Cite only supplied fact_ids", 502)
        cited = [available[identifier] for identifier in paragraph.fact_ids]
        if paragraph.purpose == "lesson":
            lesson_facts = cited
        background = next(entry for entry in evidence["facts"] if entry["id"] == "game:rules")
        # The practice question follows the lesson, so the lesson's facts support it too
        support = [*cited, *lesson_facts] if paragraph.purpose == "practice" else cited
        problems.extend(paragraph_problems(text, [*support, background], evidence["positions"]))
        problems.extend(presentation_problems(own, language))
        notes.extend(paragraph_style_notes(own))
        limit = limits[paragraph.purpose]
        if len(own) > limit:
            notes.append(f"Keep the {paragraph.purpose} paragraph under {limit} characters")
        if paragraph.purpose == "game" and not any(entry["id"].startswith("game:") for entry in cited):
            problems.append("The game reflection must cite whole-game evidence")
        cited_ids.extend(entry["id"] for entry in cited)
        shown.append({"purpose": paragraph.purpose, "text": text.strip(), "fact_ids": paragraph.fact_ids})
    if not any(identifier.startswith("game:") for identifier in cited_ids):
        problems.append("Use whole-game evidence, not only a single position")
    focus_fact = focus["primary_fact"] if focus else None
    if problems:
        raise AppError("REVIEW_PLAN_INVALID", "; ".join(problems[:8]), 502)
    ordered_ids = list(dict.fromkeys(([focus_fact] if focus_fact else []) + cited_ids))
    original = {entry["id"]: entry for entry in evidence["facts"]}
    return {"answer": "\n\n".join(paragraph["text"] for paragraph in shown), "paragraphs": shown,
            "answer_facts": [original[identifier] for identifier in ordered_ids],
            "plan": draft.model_dump(), "style_notes": list(dict.fromkeys(notes))}



def capture_is_next(item, goal):
    # Replays the shown moves to learn whether the capturing side moves next or the other side moves first
    position, _ = Position(tuple(item["analysis"]["board"]), item["actor"]).play(goal["available_move"])
    for move in goal["after_same_moves"]:
        position, _ = position.play(move)
    capturer = item["actor"] if goal["actor"] == "you" else opponent(item["actor"])
    return position.turn == capturer


def consequence_text(goal, language, immediate):
    # The verified capture spelled out as what the player would see happen next
    if "consequence" in goal:
        return ""
    move, target, prefix = goal["available_move"], goal["reply"], goal["after_same_moves"]
    corner = target in CORNERS
    if language == "Simplified Chinese":
        actor, victim = ("你", "对手") if goal["actor"] == "you" else ("对手", "你")
        timing = f"，再经过 {' → '.join(prefix)}" if prefix else ""
        when = f"{actor}可以下" if immediate else f"轮到{victim}下；如果{victim}不挡住，{actor}下一步就可以下"
        text = f"也就是说，下 {move}{timing} 后，{when} {target}，把这条线中间{victim}的棋子翻过来。"
        return text + (f"{target} 是角，角上的棋子再也不会被翻回。" if corner else "")
    actor, victim, first = (("you", "the opponent's", "the opponent moves first; unless the opponent blocks it, you")
                            if goal["actor"] == "you" else
                            ("the opponent", "your", "you move first; unless you block it, the opponent"))
    timing = f" and {' → '.join(prefix)}" if prefix else ""
    when = f"{actor} can play" if immediate else f"{first} can then play"
    text = f" In other words, after {move}{timing}, {when} {target} and flip {victim} discs along that line."
    return text + (f" {target} is a corner, and a disc there can never be flipped back." if corner else "")


def lesson_opening(position, language):
    mechanism = position["mechanism"]["text"].strip()
    if language == "Simplified Chinese":
        return f"第 {position['move_number']} 手你下了 {position['played']}，推荐下 {position['recommended']}。{mechanism}"
    return f"At move {position['move_number']} you played {position['played']}; the recommended move is {position['recommended']}. {mechanism}"


def fact_aliases(evidence):
    prefixes = {f"p{position['revision']}": position["id"] for position in evidence["positions"]}
    return {entry["id"]: prefixes.get(entry["id"].partition(":")[0], entry["id"].partition(":")[0])
            + "_" + entry["id"].partition(":")[2]
            for entry in evidence["facts"] if not entry["id"].endswith(":turn") and entry["id"] != "game:rules"}


def summary_message(evidence):
    profile = evidence["profile"]
    aliases = fact_aliases(evidence)
    positions = []
    for position in evidence["positions"]:
        mechanism = position["mechanism"]
        positions.append({key: value for key, value in position.items()
                          if key not in ("revision", "primary_fact", "mechanism")}
                         | {"primary_fact": aliases[position["primary_fact"]],
                            "lesson_opening": lesson_opening(position, evidence["language"]) if mechanism else None})
    facts = []
    move_numbers = {position["revision"]: position["move_number"] for position in evidence["positions"]}
    for entry in evidence["facts"]:
        if entry["id"] not in aliases:
            continue
        text = re.sub(r"\bposition (\d+)\b", lambda match:
                      f"game move {move_numbers[int(match.group(1))]}" if int(match.group(1)) in move_numbers
                      else "this position", entry["text"])
        facts.append({"id": aliases[entry["id"]], "text": text, "topic": entry["topic"]})
    guidance = ("用初学者听得懂的简单中文。game 段落用“你”称呼玩家，不写“我”；practice 的问题用“我”自问。三个阶段叫开局、中盘、终局。"
                "引用手数时写 {review_A} 这样的局面标记，程序会填入棋谱中的真实手数。"
                "game 段落先用一句话说几步与推荐一致、几步值得复盘，不说一共有几步可以选、几步只有一个地方能下；"
                "game 事实里有规律时，再用一两句话讲这个规律，比如常选翻子最多的走法、让对手可以马上占角；举例最多举两步，不要重复 lesson 里讲的那一步。"
                "比推荐差得多的步就说“值得复盘”，不要说“落后”，那会被理解成整盘处于劣势。全文不提 Edax。"
                "只差一点的步不是失误，不要和值得复盘的步合在一起。"
                "不要写统计报告、编号列表、英文单词或字段名。翻得多只是观察，不据此猜测动机。"
                "自己的落子只会把对手棋子翻成自己的颜色。有 lesson_opening 时，lesson 段落只显示它，"
                "lesson 的 text 留空；把这一步的道理变成 practice 里下盘落子前可以问自己的一个问题。"
                if evidence["language"] == "Simplified Chinese" else
                "When a lesson_opening exists, it is the whole lesson; leave the lesson text empty.")
    return json.dumps({"language": evidence["language"], "writing_guidance": guidance,
        "character_limits": SUMMARY_LIMITS[evidence["language"]],
        "facts": facts, "positions": positions, "profile": {
        "counts": {key: profile["counts"].get(key, 0) for key in ("best", "close", "review", "assisted")},
        "decisions": [{"move": item["move"], "phase": item["phase"], "forced": item["category"] == "forced",
                       "matches_search": item["category"] == "best", "worth_reviewing": item["category"] == "review",
                       "hint_displayed": item["hint_displayed"]} for item in profile["decisions"]],
        "observations": [{"id": item["id"], "fact_id": aliases[item["fact_id"]]} for item in profile["observations"]],
    }}, ensure_ascii=False)
