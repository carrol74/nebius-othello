from copy import deepcopy

import pytest

from nemothello.calibration import GENERATION_CALIBRATION, calibration_passed
from nemothello.policy import (
    FEATURE_TEMPLATE_VERSION,
    GENERATION_MODE,
    GENERATION_SETTINGS,
    SCORING_MODE,
    SYMBOLS,
    TEMPLATE_VERSION,
    create_policy,
)
from nemothello.rule_features import candidate_features
from nemothello.rules import INITIAL_BOARD, legal_moves


class ByteTokenizer:
    """Only checks serialization and candidate mapping; no model predictions."""

    def encode(self, text, **kwargs):
        return list(text.encode())

    def apply_chat_template(self, messages, **kwargs):
        assert kwargs == {
            "tokenize": False,
            "add_generation_prompt": True,
            "enable_thinking": False,
        }
        return "\n".join(message["content"] for message in messages) + "\nAssistant:"


def feature_gate():
    output = {"legal": True, "coordinate": "c4"}
    return {
        "status": "passed",
        "base_model": "test-model",
        "template_version": FEATURE_TEMPLATE_VERSION,
        "scoring_mode": GENERATION_MODE,
        "calibration_kind": GENERATION_CALIBRATION,
        "symbols": SYMBOLS,
        "generation_settings": dict(GENERATION_SETTINGS),
        "repeat_count": 3,
        "tolerance": 1e-4,
        "source_sampler_path": "trio://test/sampler_weights/test",
        "checks": {
            key: True
            for key in (
                "encoding",
                "train_restore",
                "legal_outputs",
                "repeat_selection",
                "sampler_restore_selection",
            )
        },
        "samples": [
            {
                "before": [deepcopy(output) for _ in range(3)],
                "after": [deepcopy(output) for _ in range(3)],
                "max_restore_difference": 0,
            }
            for _ in range(2)
        ],
    }


def test_corner_capture_counts_the_resulting_board():
    board = (".OXXXXXX",) + ("XXXXXXXX",) * 7
    assert candidate_features(board, "X") == [
        {
            "coordinate": "a1",
            "corner": 1,
            "empty_corner_neighbor": 0,
            "opponent_moves": 0,
            "own_moves": 0,
            "frontier_difference": 0,
            "disc_difference": 64,
        }
    ]


@pytest.mark.parametrize("row, move, danger", [("..OX....", "b2", 2), (".OXXXXXX", "a2", 1)])
def test_empty_corner_neighbor_distinguishes_edge_and_diagonal(row, move, danger):
    board = ("........", row) + ("........",) * 6
    features = {f["coordinate"]: f for f in candidate_features(board, "X")}
    assert features[move]["empty_corner_neighbor"] == danger
    assert features[move]["corner"] == 0


@pytest.mark.parametrize(
    "template, has_features", [(TEMPLATE_VERSION, False), (FEATURE_TEMPLATE_VERSION, True)]
)
def test_runtime_uses_explicit_template_for_actual_score_path(monkeypatch, template, has_features):
    policy = create_policy("unused", "test", "saved", template_version=template)
    policy.tokenizer, policy.sampler = ByteTokenizer(), object()
    seen = []

    def inspect(encoded):
        seen.append(encoded)
        return {"coordinate": encoded.coordinates[0]}

    monkeypatch.setattr(policy, "_generate", inspect)
    decision = policy.score(INITIAL_BOARD, "X")
    encoded = seen[0]
    assert encoded.coordinates == legal_moves(INITIAL_BOARD, "X")
    assert decision["coordinate"] == encoded.coordinates[0]
    assert ("frontier_delta" in encoded.rendered) is has_features
    assert template in policy.config_id
    assert encoded.symbol_tokens == tuple(ord(s) for s in encoded.symbols)


def test_unknown_template_and_legacy_feature_combination_fail_before_api_access():
    with pytest.raises(ValueError, match="未知"):
        create_policy("", "test", "saved", template_version="unknown")
    with pytest.raises(ValueError, match="只支持"):
        create_policy("", "test", "saved", SCORING_MODE, FEATURE_TEMPLATE_VERSION)


def test_feature_calibration_cannot_be_reused_with_old_or_unknown_template():
    report = feature_gate()
    assert calibration_passed(report, "test-model", GENERATION_MODE, FEATURE_TEMPLATE_VERSION)
    assert not calibration_passed(report, "test-model", GENERATION_MODE)
    assert not calibration_passed(report, "test-model", GENERATION_MODE, "unknown")
    report["scoring_mode"] = SCORING_MODE
    report["batch_order_checked"] = True
    assert not calibration_passed(report, "test-model", SCORING_MODE, FEATURE_TEMPLATE_VERSION)


@pytest.mark.parametrize("failure", ["failed", "unstable", "restore", "missing", "tolerance"])
def test_feature_selection_preserves_strict_calibration_checks(failure):
    report = feature_gate()
    if failure == "failed":
        report["status"] = "failed"
    elif failure == "unstable":
        report["samples"][0]["after"][0]["coordinate"] = "d3"
    elif failure == "restore":
        report["samples"][0]["max_restore_difference"] = 0.1
    elif failure == "missing":
        report["samples"][0]["before"].pop()
    else:
        report["tolerance"] = 0.01
    assert not calibration_passed(report, "test-model", GENERATION_MODE, FEATURE_TEMPLATE_VERSION)
