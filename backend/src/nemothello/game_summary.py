import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from nemothello.board_features import CORNERS
from nemothello.coaching import LANGUAGES, game_summary_context, stage
from nemothello.errors import AppError
from nemothello.game_profile import game_profile
from nemothello.learning_goal import mechanism_text
from nemothello.rules import coordinate, flips
from nemothello.summary_methods import teaching_method
from nemothello.summary_validation import (
    paragraph_problems,
    paragraph_style_notes,
    prepare_paragraph,
    render_position_references,
)
from nemothello.teaching import compare_lesson

SUMMARY_VERSION = "game-presentation-v8"
SUMMARY_PROMPT = (
    "Write the actual game-summary prose for an Othello beginner. You have a complete record of their "
    "choices and verified comparisons from this game. Write three short paragraphs with purposes game, "
    "lesson and practice. Each contains your own text and supporting fact_ids. No prewritten passages "
    "are supplied. Choose focus_position from the review position IDs, or null if none are available. "
    "The game paragraph explains what stands out across this game's choices, using phase totals and "
    "observed patterns. Describe this game only, without assigning a skill rank or guessing intentions. "
    "Do not force praise. A hinted move is not unaided skill, and a forced move is not a decision. "
    "The lesson paragraph develops one useful idea from that observation, anchored by a brief, concrete "
    "example. Explain why the change matters, not merely how a legal capture works. A changed legal square "
    "is not automatically a threat. Do not write a separate critique of every review position. "
    "The practice paragraph gives a usable recognition-and-action method for the next game: where to look, "
    "what arrangement to recognize, and what to change. Connect it to the lesson; 'think ahead' alone "
    "teaches nothing. Keep detailed variations for the individual lessons. "
    "Choose the learning priority from the evidence. No category automatically comes first. Similar "
    "games can share advice, but do not turn an isolated tactic into a repeated habit or the cause of "
    "the final result. Flipping fewer discs is not inherently better. Blocking one immediate corner "
    "capture does not make that corner safe for the game. Use a local opportunity exactly as bounded "
    "by its evidence; never embellish it into complete safety or inevitable loss. "
    "A player's own move can only flip opponent discs to their own color, never the reverse. "
    "Different colors on two alternative boards are not a transition between those boards. "
    "Write in the requested language, as a teacher speaking directly to you/你 about the opponent/对手. "
    "Use concrete, natural language. Avoid stock encouragement, slogans, textbook rules paragraphs, "
    "report language, and disclaimers. The board shows the final game; the focus button opens your example. "
    "To refer to a game move, insert its position ID in braces, such as {review_A}; the app fills in the "
    "real move number from the game record. Do not calculate a move number yourself. "
    "Avoid statistical reports, search scores, side colors, result, headings and "
    "internal names. Cite game facts for game observations, and the focus "
    "position's primary_fact for the lesson and practice. Every coordinate must appear in the cited facts. "
    "Keep the total under 600 Chinese characters or 1800 English characters. Call submit_summary."
)
SUMMARY_CHECK_PROMPT = (
    "Audit the displayed Othello game summary against the supplied evidence. Return a list of specific factual "
    "issues through check_summary; leave issues empty when the summary is supported. Every observation and board claim needs support from its "
    "cited facts, and the advice follows from those observations. Check ownership, timing, alternatives, "
    "which replies are possible versus forced, and whether a local result is exaggerated into a full-game "
    "cause or universal strategy. Phase comparisons must use all choices, not selected mistakes. "
    "Resolve frequency and phase references using the complete decisions and phase totals as well as cited facts. "
    "Do not reject a supported statement merely because it paraphrases the evidence. "
    "Do not infer player intention or skill level. A maximum-flip correlation is not a causal diagnosis. "
    "Reject unearned factual praise and a single local mechanism presented as a repeated habit without support. Reject merely describing a "
    "legal capture as a decisive threat. Do not demand novelty, force a topic, or rewrite acceptable prose. "
    "This is a game-level reflection and a concrete learning priority, not a detailed position lesson. "
    "Reject only factual errors, unsupported conclusions, or advice that contradicts the rules or evidence. "
    "Vocabulary preferences, coordinate list length, paragraph order, tone and teaching depth belong in "
    "style_notes, not issues; do not reject an otherwise supported summary for presentation. "
    "If rejecting, identify the unsupported claim and the relevant fact, with an actionable correction."
)


class SummaryParagraph(BaseModel):
    model_config = ConfigDict(extra="forbid")
    purpose: Literal["game", "lesson", "practice"]
    text: str = Field(min_length=1)
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
        if goal:
            selected.append({"id": f"p{revision}:mechanism", "topic": "corners"
                             if goal["reply"] in CORNERS else "comparison", "revision": revision,
                             "text": mechanism_text(goal["changes"][0]["square"], goal, LANGUAGES[language],
                                                    show_continuation=True)})
        facts.extend(selected)
        positions.append({**references[revision],
                          "phase": stage(item), "played": item["actual_move"],
                          "recommended": comparison["recommended_move"], "primary_fact": position["focus"][0]
                          if position["focus"] else f"p{revision}:decision",
                          "learning_goal": position["learning_goal"],
                          "verified_operation": teaching_method(item, position["learning_goal"])})
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
    cited_ids, problems, notes = [], [], []
    roles = {paragraph.purpose: paragraph for paragraph in draft.paragraphs}
    if set(roles) != {"game", "lesson", "practice"}:
        raise AppError("REVIEW_PLAN_INVALID", "Include a game reflection, lesson, and practice", 502)
    draft.paragraphs = [roles[purpose] for purpose in ("game", "lesson", "practice")]
    for paragraph in draft.paragraphs:
        paragraph.text, paragraph.fact_ids = prepare_paragraph(
            paragraph.text, paragraph.fact_ids, available, positions, evidence["language"])
        if not paragraph.fact_ids:
            raise AppError("REVIEW_PLAN_INVALID", "Support each paragraph with supplied fact_ids", 502)
        if not set(paragraph.fact_ids) <= available.keys():
            raise AppError("REVIEW_PLAN_INVALID", "Cite only supplied fact_ids", 502)
        cited = [available[identifier] for identifier in paragraph.fact_ids]
        background = next(entry for entry in evidence["facts"] if entry["id"] == "game:rules")
        problems.extend(paragraph_problems(paragraph.text, [*cited, background], evidence["positions"]))
        notes.extend(paragraph_style_notes(paragraph.text))
        if paragraph.purpose == "game" and not any(entry["id"].startswith("game:") for entry in cited):
            problems.append("The game reflection must cite whole-game evidence")
        cited_ids.extend(entry["id"] for entry in cited)
    if not any(identifier.startswith("game:") for identifier in cited_ids):
        problems.append("Use whole-game evidence, not only a single position")
    focus_fact = positions[draft.focus_position]["primary_fact"] if positions else None
    if focus_fact and focus_fact not in cited_ids:
        problems.append("Cite the selected focus position's primary_fact")
    answer = "\n\n".join(paragraph.text.strip() for paragraph in draft.paragraphs)
    limit = 600 if evidence["language"] == "Simplified Chinese" else 1800
    if len(answer) > limit:
        notes.append(f"Prefer a complete summary under {limit} characters")
    if problems:
        raise AppError("REVIEW_PLAN_INVALID", "; ".join(problems[:8]), 502)
    ordered_ids = list(dict.fromkeys(([focus_fact] if focus_fact else []) + cited_ids))
    original = {entry["id"]: entry for entry in evidence["facts"]}
    return {"answer": answer, "answer_facts": [original[identifier] for identifier in ordered_ids],
            "plan": draft.model_dump(), "style_notes": list(dict.fromkeys(notes))}


def fact_aliases(evidence):
    prefixes = {f"p{position['revision']}": position["id"] for position in evidence["positions"]}
    return {entry["id"]: prefixes.get(entry["id"].partition(":")[0], entry["id"].partition(":")[0])
            + "_" + entry["id"].partition(":")[2]
            for entry in evidence["facts"] if not entry["id"].endswith(":turn")}


def summary_message(evidence):
    profile = evidence["profile"]
    aliases = fact_aliases(evidence)
    positions = []
    for position in evidence["positions"]:
        goal = position["learning_goal"]
        positions.append({key: value for key, value in position.items()
                          if key not in ("revision", "primary_fact", "learning_goal")}
                         | {"primary_fact": aliases[position["primary_fact"]],
                            "learning_goal": {**goal, "fact_id": aliases[goal["fact_id"]]} if goal else None})
    facts = []
    move_numbers = {position["revision"]: position["move_number"] for position in evidence["positions"]}
    for entry in evidence["facts"]:
        if entry["id"] not in aliases:
            continue
        text = re.sub(r"\bposition (\d+)\b", lambda match:
                      f"game move {move_numbers[int(match.group(1))]}" if int(match.group(1)) in move_numbers
                      else "this position", entry["text"])
        facts.append({"id": aliases[entry["id"]], "text": text, "topic": entry["topic"]})
    guidance = ("直接用教练的口吻讲这盘棋。引用手数时写 {review_A} 这样的局面标记，程序会填入棋谱中的真实手数。"
                "不要写统计报告、编号列表或内部分类。"
                "翻得多只是观察，不据此猜测动机。自己的落子只会把对手棋子翻成自己的颜色；"
                "两种候选走法留下的棋盘颜色不同，不代表自己的落子把自己的棋子变成对手的。"
                "mechanism 是已验证的棋盘事实，结合整盘特点讲清这盘最值得学的原因和操作办法。"
                if evidence["language"] == "Simplified Chinese" else
                "Use the verified mechanism as board evidence, and explain this game's learning priority.")
    return json.dumps({"language": evidence["language"], "writing_guidance": guidance,
        "facts": facts, "positions": positions, "profile": {
        "counts": profile["counts"], "phases": profile["phases"],
        "decisions": [{"move": item["move"], "phase": item["phase"], "forced": item["category"] == "forced",
                       "matches_search": item["category"] == "best", "worth_reviewing": item["category"] == "review",
                       "hint_displayed": item["hint_displayed"]} for item in profile["decisions"]],
        "observations": [{"id": item["id"], "fact_id": aliases[item["fact_id"]]} for item in profile["observations"]],
    }}, ensure_ascii=False)
