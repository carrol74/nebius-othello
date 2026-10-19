import json
from copy import deepcopy
from pathlib import Path

import pytest

from nemothello.coaching import enrich_evidence, position_facts, review_context
from nemothello.decision import assess_decision
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


def test_every_nonforced_choice_gets_a_distinct_reference_and_grounded_insight(evidence):
    insight_kinds = set()
    for item in evidence:
        for candidate in item["analysis"]["candidates"]:
            result = compare_lesson({"evidence": [item]}, item["revision"], candidate["coordinate"])
            lesson = TeachingComparison.model_validate(result)
            first = lesson.choices[0]
            assert first.coordinate == candidate["coordinate"]
            assert first.assessment.model_dump() == assess_decision(item, first.coordinate)
            if first.assessment.status == "forced":
                assert lesson.reference_move is None and len(lesson.choices) == 1
            else:
                assert len(lesson.choices) == 2
                assert first.coordinate != lesson.reference_move == lesson.choices[1].coordinate
                equal = first.score == lesson.choices[1].score
                assert (lesson.insight.kind == "equal") == equal
            insight_kinds.add(lesson.insight.kind)
    assert {"forced", "equal", "shared_corner", "corner_defense", "search"} <= insight_kinds


def test_ties_and_unfavorable_best_moves_are_never_turned_into_mistakes(evidence):
    opening = evidence[0]
    assessment = assess_decision(opening, opening["actual_move"])
    assert assessment["status"] == "tied_best" and assessment["position"] == "behind"
    facts, _ = position_facts(enrich_evidence(opening))
    assert "equally highest-rated" in facts[0]["text"]
    assert not any("mistake" in fact["text"] for fact in facts)
    context = review_context({"evidence": [opening], "key_moves": [opening], "human_color": opening["actor"],
                              "result": None, "hint_adoption": {"shown_turns": 0, "adopted_turns": 0}, "hints": []}, None, revision=0)
    assert context["positions"][0]["decision"] == assessment


def test_an_unplayed_position_does_not_label_any_option_as_played(evidence):
    item = {**evidence[0], "is_played": False}
    for candidate in item["analysis"]["candidates"]:
        result = compare_lesson({"evidence": [item]}, item["revision"], candidate["coordinate"])
        assert all(not choice["assessment"]["is_played"] for choice in result["choices"])


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
