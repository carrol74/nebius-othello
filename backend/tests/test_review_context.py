import json
from pathlib import Path

from nemothello.nemotron import review_context
from nemothello.rules import INITIAL_BOARD, apply_move, legal_moves, opponent


def native_evidence():
    report = json.loads((Path(__file__).parent / "fixtures"
                         / "edax-4.6-macos-adapter-check.json").read_text())
    positions = []
    history = []
    for revision, name in enumerate(("initial_black", "after_d3_white")):
        analysis = next(case["analysis"] for case in report["cases"] if case["name"] == name)
        actual = analysis["candidates"][0]
        best = next(candidate for candidate in analysis["candidates"]
                    if candidate["coordinate"] == analysis["recommended_move"])
        positions.append({"revision": revision, "actor": analysis["turn"],
                          "actual_move": actual["coordinate"], "recommended_move": best["coordinate"],
                          "score_loss": best["score"] - actual["score"], "analysis": analysis})
        history.append({"revision": revision + 1, "actor": analysis["turn"],
                        "coordinate": actual["coordinate"], "kind": "move"})
    return {"initial_board": list(INITIAL_BOARD), "initial_turn": "X", "human_color": "X",
            "history": history, "result": None, "key_moves": positions, "evidence": positions,
            "hint_adoption": {"shown_turns": 0, "adopted_turns": 0},
            "hints": [], "automatic_hint_moves": []}


def test_real_engine_evidence_retains_move_revision_and_each_color_perspective():
    evidence = native_evidence()
    context = review_context(evidence, None)
    assert context["history"] == " ".join(
        f"{event['revision']}:{event['actor']}:{event['coordinate']}" for event in evidence["history"])
    for original, position in zip(evidence["key_moves"], context["positions"], strict=True):
        assert position["revision"] == original["revision"]
        color = "黑方" if original["actor"] == "X" else "白方"
        assert f"{color}实际落子 {original['actual_move']}" in position["fact"]
        assert f"{color}视角" in position["fact"]
        for candidate in position["candidates"]:
            after = apply_move(tuple(position["board"]), original["actor"], candidate["coordinate"])
            assert candidate["opponent_legal_moves_after"] == list(legal_moves(after, opponent(original["actor"])))


def test_question_fetches_requested_position_without_reusing_generated_explanation():
    evidence = native_evidence()
    evidence["key_moves"] = evidence["evidence"][:1]
    before = review_context(evidence, "针对局面版本 1：为什么这样下？")
    evidence["explanation"] = "上一轮生成的文字"
    after = review_context(evidence, "针对局面版本 1：为什么这样下？")
    assert before == after
    assert [item["revision"] for item in after["positions"]] == [0, 1]
    assert [item["revision"] for item in review_context(evidence, None)["positions"]] == [0]
