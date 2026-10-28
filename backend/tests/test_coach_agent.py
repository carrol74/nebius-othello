import json
from pathlib import Path

import pytest

from nemothello.board_features import CORNERS
from nemothello.coach_agent import CoachSession, CoachTools
from nemothello.coaching import render_plan, review_context
from nemothello.corner_proof import prove_corner
from nemothello.errors import AppError
from nemothello.lesson_view import resolve_lesson_view
from nemothello.rules import apply_move, flips, legal_moves, opponent, square


@pytest.fixture
def native_review():
    path = Path(__file__).parent / "fixtures/review-native-positions.json"
    return json.loads(path.read_text())["review"]


def call(name, arguments, identifier="call-1"):
    return {"id": identifier, "function": {"name": name, "arguments": json.dumps(arguments)}}


def root(review, revision):
    item = next(item for item in review["evidence"] if item["revision"] == revision)
    return tuple(item["analysis"]["board"]), item["actor"]


def test_play_line_reports_rule_engine_results(native_review):
    context = review_context(native_review, "What if I play b3?", 16)
    tools = CoachTools(native_review, context)
    board, actor = root(native_review, 16)
    reply = legal_moves(apply_move(board, actor, "b3"), opponent(actor))[0]
    result = tools.run("play_line", json.dumps({"revision": 16, "moves": ["b3", reply]}))
    after = apply_move(apply_move(board, actor, "b3"), opponent(actor), reply)
    values = result["values"]
    assert result["fact_id"] == "t1"
    assert values["t1.s1.flips"] == len(flips(board, actor, "b3"))
    assert values["t1.replies"] == len(legal_moves(after, actor))
    assert values["t1.your_discs"] == sum(row.count("X") for row in after)
    assert "you: b3, flipping" in result["text"] and "other replies are possible" in result["text"]
    assert tools.trace == [{"name": "play_line", "arguments": {"revision": 16, "moves": ["b3", reply]},
                            "fact_id": "t1", "error": None}]


def test_play_line_inserts_passes_and_reports_game_end(native_review):
    item = next(item for item in native_review['evidence'] if item['revision'] == 47)
    view = resolve_lesson_view(item, {'selected_move': 'e7', 'line': []})
    context = review_context({**native_review, 'human_color': 'O', 'teaching_view': view}, 'What happens next?', 47)
    context['positions'].extend(review_context({**native_review, 'human_color': 'O'}, 'What happens next?', 63)['positions'])
    tools = CoachTools(native_review, context)
    board, actor = root(native_review, 47)
    after = apply_move(board, actor, "e7")
    again = legal_moves(after, actor)[0]
    passed = tools.run("play_line", json.dumps({"revision": 47, "moves": ["e7", again]}))
    assert "the opponent: no legal move, must pass" in passed["text"]
    assert f"you: {again}, flipping" in passed["text"]
    ended = tools.run("play_line", json.dumps({"revision": 63, "moves": ["h8"]}))
    assert "Neither player can move" in ended["text"] and "t2.replies" not in ended["values"]


def test_tool_input_errors_return_guidance_without_creating_facts(native_review):
    context = review_context(native_review, "What if?", 16)
    tools = CoachTools(native_review, context)
    illegal = tools.run("play_line", json.dumps({"revision": 16, "moves": ["a1"]}))
    assert "a1 is not legal for you" in illegal["error"] and "b1" in illegal["error"]
    assert "not available" in tools.run("play_line", json.dumps({"revision": 11, "moves": ["c4"]}))["error"]
    assert "JSON" in tools.run("check_corner_threat", "{not json")["error"]
    assert tools.facts == [] and [entry["fact_id"] for entry in tools.trace] == [None, None, None]


def test_corner_threat_matches_the_corner_proof(native_review):
    context = review_context(native_review, "Is b1 safe?", 16)
    tools = CoachTools(native_review, context)
    board, actor = root(native_review, 16)
    for move in legal_moves(board, actor):
        after = apply_move(board, actor, move)
        expected = [target for target in CORNERS if after[square(target)[0]][square(target)[1]] == "."
                    and prove_corner(after, actor, target)["forced"]]
        result = tools.run("check_corner_threat", json.dumps({"revision": 16, "move": move}))
        assert result["values"].get(f"{result['fact_id']}.threatened", []) == expected


def test_session_accepts_an_answer_built_on_tool_results(native_review):
    context = review_context(native_review, "What if I play b3?", 16)
    session = CoachSession(native_review, context)
    first = session.respond([call("play_line", {"revision": 16, "moves": ["b3"]})])
    assert json.loads(first[0]["content"])["fact_id"] == "t1"
    submit = {"topic": "comparison", "selections": [], "answer": {
        "text": "{t1.replies}.", "fact_ids": ["t1"]}}
    assert session.tools.definitions(context)[-1]["function"]["parameters"]["properties"]["answer"][
        "properties"]["fact_ids"]["items"]["enum"][-1] == "t1"
    second = session.respond([call("submit_answer", submit, "call-2")])
    assert json.loads(second[0]["content"]) == {"accepted": True}
    rendered = render_plan(session.plan, context, session.tools.facts)
    replies = session.tools.facts[0]["values"]["t1.replies"]
    assert rendered["answer"] == f"After this line, the opponent has {replies} legal moves."
    assert rendered["answer_facts"][0]["id"] == "t1"


def test_session_returns_two_corrections_then_fails(native_review):
    context = review_context(native_review, "Why b1?", 16)
    session = CoachSession(native_review, context)
    wrong = {"topic": "comparison", "selections": [], "answer": {
        "text": "b1 leaves 9 replies.", "fact_ids": ["p16:mobility"]}}
    for attempt in ("call-1", "call-2"):
        feedback = json.loads(session.respond([call("submit_answer", wrong, attempt)])[0]["content"])
        assert "writes 9 directly in 'b1 leaves 9 replies.'" in feedback["error"] and session.plan is None
    with pytest.raises(AppError) as error:
        session.respond([call("submit_answer", wrong, "call-3")])
    assert error.value.code == "COACH_UNGROUNDED"


def test_fixed_ranges_stated_in_words_by_a_cited_fact_may_be_written_in_words(native_review):
    context = review_context(native_review, "b3 之后角安全吗？", 16)
    session = CoachSession(native_review, context)
    session.respond([call("check_corner_threat", {"revision": 16, "move": "b3"})])
    assert "three plies" in session.tools.facts[0]["text"]
    submit = {"topic": "comparison", "selections": [], "answer": {
        "text": "b3 之后，对手在接下来三步之内无法强制占角。", "fact_ids": ["t1"]}}
    assert json.loads(session.respond([call("submit_answer", submit, "call-2")])[0]["content"]) == {"accepted": True}


def test_inline_citations_count_and_are_removed_from_the_text(native_review):
    context = review_context(native_review, "Is b1 risky?", 16)
    session = CoachSession(native_review, context)
    session.respond([call("check_corner_threat", {"revision": 16, "move": "b1"})])
    repeated = json.loads(session.respond([call("check_corner_threat", {"revision": 16, "move": "b1"}, "call-2")])[0]["content"])
    assert repeated["fact_id"] == "t1" and "Already checked" in repeated["note"] and len(session.tools.facts) == 1
    submit = {"topic": "comparison", "selections": [], "answer": {
        "text": "{t1.threatened} ({t1}). {p16.b1.replies}（p16:mobility）.",
        "fact_ids": []}}
    assert json.loads(session.respond([call("submit_answer", submit, "call-3")])[0]["content"]) == {"accepted": True}
    rendered = render_plan(session.plan, context, session.tools.facts)
    assert rendered["answer"] == "After b1, the opponent can force a1 within its next two turns. After b1, the opponent has 9 legal replies."
    assert [fact["id"] for fact in rendered["answer_facts"]] == ["t1", "p16:mobility"]


def test_answer_only_rounds_offer_just_the_submit_tool(native_review):
    context = review_context(native_review, "Why b1?", 16)
    tools = CoachTools(native_review, context)
    assert [tool["function"]["name"] for tool in tools.definitions(context)] == [
        "play_line", "check_corner_threat", "submit_answer"]
    assert [tool["function"]["name"] for tool in tools.definitions(context, answer_only=True)] == ["submit_answer"]
