import json
import re
from pathlib import Path

import pytest

from nemothello.coach_agent import CoachTools
from nemothello.coaching import (
    enrich_evidence,
    game_summary_context,
    select_key_moves,
    validate_plan,
)
from nemothello.edax import Edax
from nemothello.errors import AppError
from nemothello.game_profile import game_profile
from nemothello.game_summary import (
    display_saved_summary,
    fact_aliases,
    lesson_opening,
    render_summary,
    summary_evidence,
    summary_message,
    summary_tool,
    validate_summary_check,
)
from nemothello.learning_goal import learning_goal, mechanism_text
from nemothello.opponents import EdaxOpponent
from nemothello.position_lessons import opponent_replies
from nemothello.rules import Position, coordinate, flips, legal_moves, opponent
from nemothello.teaching import compare_lesson


@pytest.fixture
def summary_context():
    review = json.loads((Path(__file__).parent / "fixtures/review-native-positions.json").read_text())["review"]
    revisions = [item["revision"] for item in select_key_moves(review["evidence"], review["human_color"])]
    return review, game_summary_context(review, revisions, "zh")


@pytest.fixture(scope="module", params=["X", "O"])
def complete_review(request):
    root = Path(__file__).resolve().parents[2]
    executable, weights = root / "deploy/edax/edax", root / "deploy/edax/eval.dat"
    if not executable.is_file() or not weights.is_file():
        pytest.skip("Native Edax and eval.dat are required")
    source = json.loads((Path(__file__).parent / "fixtures/review-native-positions.json").read_text())["review"]
    engine = Edax(executable, weights, "4.6", 4)
    position = Position(tuple(source["initial_board"]), source["initial_turn"])
    evidence, revision = [], 0
    try:
        for event in source["history"]:
            if event["kind"] == "move":
                if event["actor"] == request.param:
                    analysis = engine.analyze(position.board, position.turn)
                    actual = next(c for c in analysis["candidates"] if c["coordinate"] == event["coordinate"])
                    best = max(analysis["candidates"], key=lambda c: c["score"])
                    evidence.append(enrich_evidence({
                        "revision": revision, "actor": position.turn, "actual_move": event["coordinate"],
                        "recommended_move": best["coordinate"], "score_loss": best["score"] - actual["score"],
                        "analysis": analysis, "shown_hint_ids": [], "adopted_hint": False,
                        "opponent_replies": opponent_replies(position.board, position.turn, EdaxOpponent(engine)),
                    }))
                position, _ = position.play(event["coordinate"])
            revision = event["revision"]
    finally:
        engine.close()
    assert position.result() == source["result"]
    return {**source, "human_color": request.param, "evidence": evidence,
            "hints": [], "hint_adoption": {"shown_turns": 0, "adopted_turns": 0}}


def plan(text, fact_ids, selections=()):
    return json.dumps({"topic": "summary", "answer": {"text": text, "fact_ids": fact_ids},
                       "selections": list(selections)}, ensure_ascii=False)


def test_summary_covers_every_key_move_with_its_primary_reason_and_a_played_line(summary_context):
    review, context = summary_context
    assert [(position["revision"], position["primary_reason"]) for position in context["positions"]] == [
        (2, "reply_contrast"), (16, "corner_contrast"), (22, None)]
    focus = [position["focus"][0] for position in context["positions"]]
    assert focus == ["p2:decision_contrast", "p16:corner_contrast", "p22:shared_corner"]
    tools = CoachTools(review, context)
    played = [tools.run("play_line", json.dumps({"revision": revision, "moves": [move]}))["fact_id"]
              for revision, move in ((2, "b6"), (16, "b1"), (22, "a3"))]
    text = "b6 和 b1 都给对手接上了夹击线，a3 的角两步都保不住。下一盘落子前，先看新棋子会不会接上对手的夹击线。"
    assert validate_plan(plan(text, focus + played), context, tools.facts).answer.text == text
    with pytest.raises(AppError, match="first focus fact of every position: p22:shared_corner"):
        validate_plan(plan(text, focus[:2] + played), context, tools.facts)
    with pytest.raises(AppError, match="play out a3 at position 22"):
        validate_plan(plan(text, focus + played[:2]), context, tools.facts)
    with pytest.raises(AppError, match="leave selections empty"):
        validate_plan(plan(text, focus + played, [{"revision": 2, "fact_ids": focus[:1], "lesson_id": "comparison",
                                                   "text": "b6"}]), context, tools.facts)
    with pytest.raises(AppError, match="under 220"):
        validate_plan(plan(text * 5, focus + played), context, tools.facts)
    with pytest.raises(AppError, match="must name the move a3"):
        validate_plan(plan(text.replace("a3 的角", "这个角"), focus + played), context, tools.facts)
    with pytest.raises(AppError, match="backslash"):
        validate_plan(plan("\\n\\n" + text, focus + played), context, tools.facts)
    with pytest.raises(AppError, match="category name"):
        validate_plan(plan(text + "这是应对对比的问题。", focus + played), context, tools.facts)
    with pytest.raises(AppError, match="我们"):
        validate_plan(plan("我们" + text, focus + played), context, tools.facts)


def test_tools_stay_open_until_every_key_move_is_played_out(summary_context):
    review, context = summary_context
    tools = CoachTools(review, context)
    assert tools.unplayed() == [2, 16, 22]
    tools.run("play_line", json.dumps({"revision": 16, "moves": ["b1"]}))
    tools.run("check_corner_threat", json.dumps({"revision": 2, "move": "b6"}))
    assert tools.unplayed() == [22]


def learning_revisions(review):
    selected = [item["revision"] for item in select_key_moves(review["evidence"], review["human_color"])]
    return selected or [review["evidence"][0]["revision"]]


def written_draft(evidence):
    position = json.loads(summary_message(evidence))["positions"][0]
    return {"focus_position": position["id"], "paragraphs": [
        {"purpose": "game", "text": "Your decisions across the game provide context for this review.", "fact_ids": ["game_choices"]},
        {"purpose": "lesson", "text": f"Revisit {position['played']} and inspect what the alternative changes.",
         "fact_ids": [position["primary_fact"], f"{position['id']}_decision"]},
    ]}


def test_summary_supplies_game_evidence_without_preselected_passages(complete_review):
    review = complete_review
    revisions = [item["revision"] for item in select_key_moves(review["evidence"], review["human_color"])]
    evidence = summary_evidence(review, revisions, "en")
    assert len(evidence["profile"]["decisions"]) == len(review["evidence"])
    assert [item["revision"] for item in evidence["positions"]] == revisions
    assert "paragraphs" not in evidence["profile"] and "priorities" not in evidence
    message = json.loads(summary_message(evidence))
    facts = {entry["id"]: entry["text"] for entry in message["facts"]}
    for position, shown in zip(evidence["positions"], message["positions"]):
        assert "practice" not in position and "text" not in position
        mechanism = position["mechanism"]
        assert (shown["lesson_opening"] or "").endswith(mechanism["text"].strip() if mechanism else "")
        assert (shown["lesson_opening"] is None) == (mechanism is None)
        if mechanism:
            assert facts[f"{shown['id']}_mechanism"] == mechanism["text"]
    assert not re.search(r"anchor|learning_goal|operation", summary_message(evidence))
    assert "phases" not in message["profile"]
    aliases = fact_aliases(evidence)
    assert {entry["id"] for entry in message["facts"]} == set(aliases.values())
    assert "revision" not in summary_message(evidence)
    assert not re.search(r"\bp\d+:", summary_message(evidence))
    assert len(message["profile"]["decisions"]) == len(review["evidence"])
    assert all("revision" not in item for item in message["profile"]["decisions"])
    schema = summary_tool(evidence)["function"]["parameters"]
    assert "paragraphs" in schema["required"] and "example_id" not in schema["properties"]
    assert schema["properties"]["focus_position"]["enum"] == ([position["id"] for position in evidence["positions"]] or [None])
    assert len(summary_message(evidence)) < 26000


def test_summary_preserves_authored_paragraphs_and_keeps_the_focus_evidence_first(complete_review):
    revisions = learning_revisions(complete_review)
    evidence = summary_evidence(complete_review, revisions, "en")
    draft = written_draft(evidence)
    result = render_summary(json.dumps(draft), evidence)
    shown = [paragraph["text"] for paragraph in result["paragraphs"]]
    assert result["answer"] == "\n\n".join(shown)
    assert shown[0] == draft["paragraphs"][0]["text"]
    focus = evidence["positions"][0]
    assert shown[1] == (lesson_opening(focus, evidence["language"]) if focus["mechanism"]
                        else draft["paragraphs"][1]["text"])
    assert result["answer_facts"][0]["id"] == evidence["positions"][0]["primary_fact"]
    draft["paragraphs"][0]["text"] = "Use the complete record to put this decision in context."
    other = render_summary(json.dumps(draft), evidence)
    assert other["answer"] != result["answer"]
    assert other["answer"].startswith(draft["paragraphs"][0]["text"])


@pytest.mark.parametrize("mutation,match", [
    ("old_selector", "Write paragraphs"), ("unknown_fact", "supplied fact_ids"),
    ("unavailable_focus", "focus_position"), ("no_profile", "whole-game evidence"),
    ("raw_count", "99"),
])
def test_summary_rejects_untraceable_or_old_selector_output(complete_review, mutation, match):
    revisions = learning_revisions(complete_review)
    evidence = summary_evidence(complete_review, revisions, "en")
    draft = written_draft(evidence)
    if mutation == "old_selector":
        draft = {"example_id": "corner_flip_anchor"}
    elif mutation == "unknown_fact":
        draft["paragraphs"][0]["fact_ids"] = ["another-game:choices"]
    elif mutation == "unavailable_focus":
        draft["focus_position"] = "unavailable_position"
    elif mutation == "no_profile":
        draft["paragraphs"][0]["fact_ids"] = [f"{draft['focus_position']}_decision"]
    else:
        draft["paragraphs"][0]["text"] = "You played 99 moves."
    with pytest.raises(AppError, match=match):
        render_summary(json.dumps(draft), evidence)


def test_board_coordinates_must_come_from_that_paragraphs_cited_facts(complete_review):
    revisions = learning_revisions(complete_review)
    evidence = summary_evidence(complete_review, revisions, "en")
    draft = written_draft(evidence)
    coordinate = evidence["positions"][0]["played"]
    draft["paragraphs"][0]["text"] += f" Consider {coordinate}."
    with pytest.raises(AppError, match="not in the evidence"):
        render_summary(json.dumps(draft), evidence)


def test_a_summary_audit_requires_support_and_exposes_its_rejection():
    assert validate_summary_check('{"issues":[]}')["accepted"]
    assert validate_summary_check('{"issues":[],"style_notes":["Use a shorter coordinate list"]}')["accepted"]
    with pytest.raises(AppError, match="unsupported skill claim"):
        validate_summary_check('{"issues":["unsupported skill claim"]}')


@pytest.mark.parametrize("language", ["en", "zh"])
@pytest.mark.parametrize("branch", [False, True])
@pytest.mark.parametrize("reference", ["{review_A}", "review_A", "review-a"])
def test_summary_repairs_presentation_using_real_game_moves(complete_review, language, branch, reference):
    review = complete_review
    if branch:
        review = completed_branch(review, review["evidence"][len(review["evidence"]) // 2])
    after_pass = [event["revision"] for event in review["history"] if event["kind"] == "pass"]
    last = next((item for item in review["evidence"] if after_pass and item["revision"] >= after_pass[0]),
                review["evidence"][-1])
    revisions = list(dict.fromkeys([review["evidence"][0]["revision"], last["revision"]]))
    evidence = summary_evidence(review, revisions, language)
    count = sum(cell != "." for row in review["initial_board"] for cell in row) - 4
    revision, expected = 0, {}
    for event in review["history"]:
        if event["kind"] == "move":
            count += 1
            expected[revision] = count
        revision = event["revision"]
    for position in evidence["positions"]:
        assert position["move_number"] == expected[position["revision"]]
    draft = written_draft(evidence)
    position = evidence["positions"][0]
    primary = fact_aliases(evidence)[position["primary_fact"]]
    sentence = f"在{reference}中，你下{position['played'].upper()}。" if language == "zh" else f"Revisit {reference}: {position['played'].upper()}."
    follow = "比较另一种下法。" if language == "zh" else "Compare the alternative."
    draft["paragraphs"][1].update(
        purpose=" Lesson ",
        text=f"  1. {sentence}\\n{follow} ({primary}, {primary})  ",
        fact_ids=[],
    )
    draft["paragraphs"].reverse()
    result = render_summary(json.dumps(draft), evidence)
    paragraphs = result["plan"]["paragraphs"]
    assert [paragraph["purpose"] for paragraph in paragraphs] == ["game", "lesson"]
    label = f"第 {expected[position['revision']]} 手" if language == "zh" else f"move {expected[position['revision']]}"
    expected_text = f"在{label}中，你下{position['played']}。" if language == "zh" else f"Revisit {label}: {position['played']}."
    assert paragraphs[1]["text"] == f"{expected_text} {follow}"
    assert primary in paragraphs[1]["fact_ids"]
    assert f"{position['id']}_decision" in paragraphs[1]["fact_ids"]
    assert len(paragraphs[1]["fact_ids"]) == len(set(paragraphs[1]["fact_ids"]))
    assert render_summary(json.dumps(result["plan"]), evidence)["answer"] == result["answer"]
    assert result["answer_facts"][0]["id"] == position["primary_fact"]


def test_presentation_repair_does_not_guess_an_unknown_move(complete_review):
    branch = completed_branch(complete_review, complete_review["evidence"][len(complete_review["evidence"]) // 2])
    evidence = summary_evidence(branch, [0], "en")
    draft = written_draft(evidence)
    for reference, problem in [("move 0", "Move 0"), ("{review_Z}", "Unresolved reference"),
                               ("review_Z", "Unresolved reference"), ("review-z", "Unresolved reference")]:
        draft["paragraphs"][0]["text"] = f"Revisit {reference}: {evidence['positions'][0]['played']}."
        with pytest.raises(AppError, match=problem):
            render_summary(json.dumps(draft), evidence)


def test_saved_summary_references_use_original_review_order_without_changing_prose(complete_review):
    revisions = [item["revision"] for item in complete_review["evidence"][:3]]
    review = {**complete_review, "key_moves": [{"revision": revision} for revision in revisions]}
    evidence = summary_evidence(review, revisions, "zh")
    text = "在review_A中观察落点。\n\n再看{review_C}，然后回到review-b。"
    summary = {"language": "zh", "text": text,
               "facts": [{"revision": revisions[2]}, {"revision": revisions[0]}]}
    displayed = display_saved_summary(summary, review)
    a, b, c = [position["move_number"] for position in evidence["positions"]]
    assert displayed["text"] == f"在第 {a} 手中观察落点。\n\n再看第 {c} 手，然后回到第 {b} 手。"
    assert displayed["facts"] == summary["facts"]
    assert summary["text"] == text


def test_summary_style_notes_do_not_discard_supported_coordinates_or_cut_text(complete_review):
    item = next(item for item in complete_review["evidence"]
                if len(flips(tuple(item["analysis"]["board"]), item["actor"], item["actual_move"])) >= 3)
    evidence = summary_evidence(complete_review, [item["revision"]], "en")
    draft = written_draft(evidence)
    position = evidence["positions"][0]
    fact = next(entry for entry in evidence["facts"] if entry["id"] == f"p{position['revision']}:root_flips")
    coordinates = list(dict.fromkeys(re.findall(r"\b[a-h][1-8]\b", fact["text"])))
    assert len(coordinates) >= 4
    long_game = (draft["paragraphs"][0]["text"] + " ") * 32 + "Inspect " + ", ".join(coordinates) + "."
    draft["paragraphs"][0].update(text=long_game, fact_ids=["game_choices", fact_aliases(evidence)[fact["id"]]])
    result = render_summary(json.dumps(draft), evidence)
    assert result["paragraphs"][0]["text"] == long_game.strip()
    assert any("coordinate list" in note for note in result["style_notes"])
    assert any("game paragraph under" in note for note in result["style_notes"])


def test_lesson_opens_with_the_verified_move_and_mechanism(complete_review):
    revisions = learning_revisions(complete_review)
    for language in ("en", "zh"):
        evidence = summary_evidence(complete_review, revisions, language)
        focus = next((position for position in evidence["positions"] if position["mechanism"]), None)
        if focus is None:
            pytest.skip("This color has no verified mechanism among its key moves")
        draft = written_draft(evidence)
        draft["focus_position"] = focus["id"]
        primary = fact_aliases(evidence)[focus["primary_fact"]]
        why = "这会决定对手之后能从哪里翻回。" if language == "zh" else "This decides where the opponent can flip back later."
        draft["paragraphs"][1].update(text=why, fact_ids=[primary])
        lesson = render_summary(json.dumps(draft), evidence)["paragraphs"][1]
        lead = (f"第 {focus['move_number']} 手你下了 {focus['played']}，推荐下 {focus['recommended']}。"
                if language == "zh" else
                f"At move {focus['move_number']} you played {focus['played']}; the recommended move is {focus['recommended']}. ")
        assert lesson["text"] == lead + focus["mechanism"]["text"].strip()
        assert f"{focus['id']}_mechanism" in lesson["fact_ids"]


def test_chinese_summary_stays_plain(complete_review):
    revisions = learning_revisions(complete_review)
    evidence = summary_evidence(complete_review, revisions, "zh")
    draft = written_draft(evidence)
    draft["paragraphs"][0]["text"] = "玩家在中游和末局多次选了翻子最多的走法（game_choices, review_A_unknown）。多数步与 Edax 推荐一致。"
    draft["paragraphs"][1].update(text=draft["paragraphs"][1]["text"], fact_ids=["game_choices"])
    result = render_summary(json.dumps(draft), evidence)
    assert fact_aliases(evidence)[evidence["positions"][0]["primary_fact"]] in result["paragraphs"][1]["fact_ids"]
    assert result["paragraphs"][0]["text"] == "你在中盘和终局多次选了翻子最多的走法。多数步与推荐一致。"
    assert "game_choices" in result["paragraphs"][0]["fact_ids"]
    position = evidence["positions"][0]
    draft["paragraphs"][0]["text"] = f"您在 {{{position['id']}}} 和其他几步都选了翻子最多的走法。"
    shown = render_summary(json.dumps(draft), evidence)["paragraphs"][0]["text"]
    assert shown == f"你在第 {position['move_number']} 手和其他几步都选了翻子最多的走法。"
    draft["paragraphs"][0]["text"] = f"在第{{{position['id']}}}手和第 {{{position['played']}}} 步，你都选了翻子最多的走法。"
    shown = render_summary(json.dumps(draft), evidence)["paragraphs"][0]["text"]
    assert shown == f"在第 {position['move_number']} 手和 {position['played']} 这一步，你都选了翻子最多的走法。"
    draft["paragraphs"][0]["text"] = "你常检查 anchor 是不是对手的棋子。"
    with pytest.raises(AppError, match="English word anchor"):
        render_summary(json.dumps(draft), evidence)


def test_profile_covers_both_colors_and_excludes_forced_turns(complete_review):
    profile = game_profile(complete_review)
    items = complete_review["evidence"]
    choices = [item for item in items if len(legal_moves(tuple(item["analysis"]["board"]), item["actor"])) > 1]
    assert profile["counts"]["choices"] == len(choices)
    assert profile["counts"]["choices"] + profile["counts"].get("forced", 0) == len(items)
    assert set(profile["revisions"]) == {item["revision"] for item in choices}
    assert profile["counts"]["choices"] == sum(profile["counts"].get(key, 0) for key in ("best", "close", "review"))
    for observation in profile["observations"]:
        for revision in observation["positions"]:
            item = next(item for item in items if item["revision"] == revision)
            assert item["score_loss"] >= 4
            if observation["id"] == "many_flips":
                board = tuple(item["analysis"]["board"])
                played_flips = len(flips(board, item["actor"], item["actual_move"]))
                assert all(len(flips(board, item["actor"], move)) <= played_flips for move in legal_moves(board, item["actor"]))
                assert len(flips(board, item["actor"], item["recommended_move"])) < played_flips or any(
                    c["score"] == max(x["score"] for x in item["analysis"]["candidates"])
                    and len(flips(board, item["actor"], c["coordinate"])) < played_flips for c in item["analysis"]["candidates"])


def test_a_partial_or_duplicated_review_cannot_be_called_a_whole_game(complete_review):
    for evidence in (complete_review["evidence"][:3], complete_review["evidence"] + complete_review["evidence"][:1]):
        with pytest.raises(AppError, match="every played human move"):
            summary_evidence({**complete_review, "evidence": evidence}, [], "zh")


def completed_branch(review, first):
    offset = first["revision"]
    return {**review, "initial_board": first["analysis"]["board"], "initial_turn": first["actor"],
            "evidence": [{**item, "revision": item["revision"] - offset} for item in review["evidence"] if item["revision"] >= offset],
            "history": [{**event, "revision": event["revision"] - offset} for event in review["history"] if event["revision"] > offset]}


def test_forced_only_branch_has_no_skill_grade_or_invented_strength(complete_review):
    item = next(item for item in reversed(complete_review["evidence"])
                if len(item["analysis"]["candidates"]) == 1)
    branch = completed_branch(complete_review, item)
    evidence = summary_evidence(branch, [], "en")
    assert evidence["profile"]["counts"].get("choices", 0) == 0
    assert all(item["category"] == "forced" for item in evidence["profile"]["decisions"])
    assert not evidence["positions"] and "paragraphs" not in evidence["profile"]
    assert summary_tool(evidence)["function"]["parameters"]["properties"]["focus_position"]["enum"] == [None]
    draft = {"focus_position": None, "paragraphs": [
        {"purpose": "game", "text": "Every move in this branch had only one legal square.", "fact_ids": ["game_choices"]},
        {"purpose": "lesson", "text": "Hints helped you here.", "fact_ids": []},
    ]}
    result = render_summary(json.dumps(draft), evidence)
    assert [paragraph["purpose"] for paragraph in result["paragraphs"]] == ["game"]
    assert result["answer"] == "Every move in this branch had only one legal square."


def test_a_single_choice_in_a_finished_branch_does_not_establish_consistency(complete_review):
    item = next(item for item in reversed(complete_review["evidence"])
                if len(item["analysis"]["candidates"]) > 1)
    profile = game_profile(completed_branch(complete_review, item))
    assert profile["counts"]["choices"] == 1
    assert "paragraphs" not in profile
    assert "does not establish a skill rank" in profile["facts"][0]["text"]


def test_actual_displayed_hints_are_identified_in_the_assessment(complete_review):
    source = json.loads((Path(__file__).parent / "fixtures/review-native-positions.json").read_text())["review"]
    recorded = {item["revision"]: item for item in source["evidence"] if item["actor"] == complete_review["human_color"]}
    evidence = [{**item, "shown_hint_ids": recorded.get(item["revision"], {}).get("shown_hint_ids", [])}
                for item in complete_review["evidence"]]
    profile = game_profile({**complete_review, "evidence": evidence})
    hinted = [item for item in evidence if item["shown_hint_ids"] and len(item["analysis"]["candidates"]) > 1]
    assert profile["counts"]["assisted"] == len(hinted)
    assert sum(item["hint_displayed"] for item in profile["decisions"] if item["category"] != "forced") == len(hinted)


def test_lesson_consequence_names_a_capture_the_rules_allow(complete_review):
    checked = 0
    for item in complete_review["evidence"]:
        goal = learning_goal(compare_lesson(complete_review, item["revision"], item["actual_move"]))
        if not goal or "consequence" in goal:
            continue
        position, _ = Position(tuple(item["analysis"]["board"]), item["actor"]).play(goal["available_move"])
        for move in goal["after_same_moves"]:
            position, _ = position.play(move)
        capturer = item["actor"] if goal["actor"] == "you" else opponent(item["actor"])
        assert goal["immediate"] == (position.turn == capturer)
        if goal["immediate"]:
            assert goal["reply"] in position.moves
        assert set(goal["flipped"]) <= {coordinate(row, col) for row, col in flips(position.board, capturer, goal["reply"])}
        text = mechanism_text(goal["changes"][0]["square"], goal, "Simplified Chinese")
        assert f"可以下 {goal['reply']}" in text and ("不挡住" in text) == (not goal["immediate"])
        assert "、".join(goal["flipped"]) in text and text.count(f"你下 {goal['available_move']}") == 1
        assert ("是角" in text) == (goal["reply"] in ("a1", "h1", "a8", "h8"))
        checked += 1
    if complete_review["human_color"] == "X":
        assert checked
