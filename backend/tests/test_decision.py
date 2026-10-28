import json
from copy import deepcopy
from pathlib import Path

import pytest

from nemothello.coaching import enrich_evidence, position_facts, review_context
from nemothello.decision import assess_decision, lesson_moves
from nemothello.errors import AppError
from nemothello.rules import legal_moves
from nemothello.schemas import DecisionAssessment, TeachingComparison
from nemothello.teaching import compare_lesson


@pytest.fixture
def evidence():
    directory = Path(__file__).parent / "fixtures"
    review = json.loads((directory / "review-native-positions.json").read_text())["review"]
    forced = json.loads((directory / "forced-move-native.json").read_text())["evidence"]
    return [*review["evidence"], forced]


def test_every_native_candidate_has_one_consistent_decision_assessment(evidence):
    statuses, actors, score_kinds, positions = set(), set(), set(), set()
    for item in evidence:
        candidates = item["analysis"]["candidates"]
        best_score = max(candidate["score"] for candidate in candidates)
        best_moves = {candidate["coordinate"] for candidate in candidates if candidate["score"] == best_score}
        for candidate in candidates:
            assessment = DecisionAssessment.model_validate(assess_decision(item, candidate["coordinate"]))
            assert assessment.legal_move_count == len(legal_moves(tuple(item["analysis"]["board"]), item["actor"]))
            assert set(assessment.best_moves) == best_moves
            assert assessment.score_loss == best_score - candidate["score"]
            assert assessment.is_played == (item.get("is_played", True) and candidate["coordinate"] == item["actual_move"])
            assert (assessment.status == "forced") == (len(candidates) == 1)
            if assessment.status == "tied_best":
                assert len(best_moves) > 1 and candidate["coordinate"] in best_moves
            if assessment.status == "lower_rated":
                assert candidate["score"] < best_score
            statuses.add(assessment.status)
            actors.add(item["actor"])
            score_kinds.add(assessment.score_kind)
            positions.add(assessment.position)
    assert statuses == {"forced", "best", "tied_best", "lower_rated"}
    assert actors == {"X", "O"} and score_kinds == {"exact", "estimate"}
    assert positions == {"ahead", "behind", "level"}


def test_lessons_only_compare_a_lower_rated_game_move_with_the_recommendation(evidence):
    insight_kinds = set()
    for item in evidence:
        assessment = assess_decision(item, item["actual_move"])
        expected = {item["actual_move"]}
        if assessment["status"] == "lower_rated":
            expected.add(assessment["best_moves"][0])
        for candidate in item["analysis"]["candidates"]:
            if candidate["coordinate"] not in expected:
                with pytest.raises(AppError) as error:
                    compare_lesson({"evidence": [item]}, item["revision"], candidate["coordinate"])
                assert error.value.code == "REVIEW_MOVE"
                continue
            result = compare_lesson({"evidence": [item]}, item["revision"], candidate["coordinate"])
            lesson = TeachingComparison.model_validate(result)
            first = lesson.choices[0]
            assert {choice.coordinate for choice in lesson.choices} == expected
            assert first.coordinate == candidate["coordinate"]
            assert first.assessment.model_dump() == assess_decision(item, first.coordinate)
            assert lesson.recommended_move in assessment["best_moves"]
            if len(expected) == 1:
                assert lesson.reference_move is None and len(lesson.choices) == 1
                assert lesson.insight.kind == ("forced" if assessment["status"] == "forced" else "best")
            else:
                assert len(lesson.choices) == 2
                assert first.coordinate != lesson.reference_move == lesson.choices[1].coordinate
                assert first.score != lesson.choices[1].score
            insight_kinds.add(lesson.insight.kind)
    assert {"forced", "best", "shared_corner", "corner_defense", "search"} <= insight_kinds


def test_ties_and_unfavorable_best_moves_are_never_turned_into_mistakes(evidence):
    result = json.loads((Path(__file__).parent / "fixtures/review-native-positions.json").read_text())["review"]["result"]
    opening = evidence[0]
    assessment = assess_decision(opening, opening["actual_move"])
    assert assessment["status"] == "tied_best" and assessment["position"] == "behind"
    facts, _, _ = position_facts(enrich_evidence(opening))
    assert "equally good move" in facts[0]["text"]
    assert not any("mistake" in fact["text"] for fact in facts)
    context = review_context({"evidence": [opening], "key_moves": [opening], "human_color": opening["actor"],
                              "result": result, "hint_adoption": {"shown_turns": 0, "adopted_turns": 0}, "hints": []}, None, revision=0)
    assert context["positions"][0]["decision"] == assessment


def test_a_best_game_move_has_single_move_facts_without_self_comparisons(evidence):
    checked = 0
    for item in evidence:
        assessment = assess_decision(item, item["actual_move"])
        if assessment["status"] not in ("best", "tied_best"):
            continue
        facts, _, _ = position_facts(enrich_evidence(item))
        comparison = compare_lesson({"evidence": [item]}, item["revision"], item["actual_move"])
        assert comparison["reference_move"] is None
        assert comparison["recommended_move"] == item["actual_move"]
        assert len(comparison["choices"]) == 1
        for fact in facts:
            if fact["id"].split(":")[1] in {"score", "mobility", "frontier", "endgame"}:
                assert fact["text"].lower().count(item["actual_move"]) == 1
                assert "alternatives" not in fact["text"]
        checked += 1
    assert checked > 1


@pytest.mark.parametrize("corruption", ["missing_candidate", "duplicate_candidate", "nonfinite_score"])
def test_incomplete_or_corrupt_evidence_cannot_produce_a_decision(evidence, corruption):
    item = deepcopy(evidence[0])
    candidates = item["analysis"]["candidates"]
    if corruption == "missing_candidate":
        candidates.pop()
    elif corruption == "duplicate_candidate":
        candidates.append(deepcopy(candidates[0]))
    else:
        candidates[0]["score"] = float("nan")
    with pytest.raises(AppError) as error:
        assess_decision(item, item["actual_move"])
    assert error.value.code == "REVIEW_SCORES"


def test_tied_best_moves_compare_with_the_one_that_keeps_the_lost_corner():
    item = json.loads((Path(__file__).parent / "fixtures/tied-best-corner-native.json").read_text())["evidence"]
    assert assess_decision(item, "g5")["best_moves"] == ["d7", "e7"]
    assert lesson_moves(item) == ["g5", "e7"]
    assert compare_lesson({"evidence": [item]}, 0, "g5")["recommended_move"] == "e7"
    facts, _, _ = position_facts(item)
    assert "Edax recommends e7 instead; d7 is equally good." in facts[0]["text"]
