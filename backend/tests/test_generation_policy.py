from copy import deepcopy

import pytest

from nemothello.calibration import GENERATION_CALIBRATION, calibration_passed
from nemothello.errors import AppError
from nemothello.policy import (
    GENERATION_MODE,
    GENERATION_SETTINGS,
    SCORING_MODE,
    SYMBOLS,
    TEMPLATE_VERSION,
    EncodedPosition,
    generated_coordinate,
)
from nemothello.training import train


@pytest.mark.parametrize("tokens", [[], [32, 33], [99], [True]])
def test_invalid_generated_token_is_rejected(tokens):
    encoded = EncodedPosition([1], ("b1", "d1"), ("A", "B"), (32, 33), "")
    with pytest.raises(AppError) as error:
        generated_coordinate(tokens, encoded)
    assert error.value.code == "POLICY_ILLEGAL_OUTPUT"
    assert error.value.retryable is True


def test_symbol_mapping_uses_encoded_candidates():
    encoded = EncodedPosition([1], ("d1", "b1"), ("A", "B"), (32, 33), "")
    assert generated_coordinate([32], encoded) == "d1"
    assert generated_coordinate([33], encoded) == "b1"


def generation_gate_metadata():
    # Gate metadata only; no simulated logprobs or claims of measured model quality.
    output = {"legal": True, "coordinate": "b1"}
    return {
        "status": "passed", "base_model": "Qwen/Qwen3.5-4B",
        "template_version": TEMPLATE_VERSION, "scoring_mode": GENERATION_MODE,
        "calibration_kind": GENERATION_CALIBRATION, "symbols": SYMBOLS,
        "generation_settings": dict(GENERATION_SETTINGS), "repeat_count": 3,
        "tolerance": 1e-4,
        "checks": {name: True for name in ("encoding", "train_restore", "legal_outputs",
                                           "repeat_selection", "sampler_restore_selection")},
        "samples": [{"before": [deepcopy(output) for _ in range(3)],
                     "after": [deepcopy(output) for _ in range(3)],
                     "max_restore_difference": 0.0} for _ in range(2)],
    }


def test_policy_mode_cannot_reuse_other_calibration():
    report = generation_gate_metadata()
    assert calibration_passed(report, report["base_model"], GENERATION_MODE)
    assert not calibration_passed(report, report["base_model"], SCORING_MODE)


@pytest.mark.parametrize("failure", ["illegal", "unstable", "incomplete", "restore", "tolerance"])
def test_generation_gate_rejects_invalid_evidence_before_training(tmp_path, failure):
    report = generation_gate_metadata()
    if failure == "illegal":
        report["samples"][0]["before"][0]["legal"] = False
    elif failure == "unstable":
        report["samples"][0]["after"][0]["coordinate"] = "d1"
    elif failure == "incomplete":
        report["samples"][0]["before"].pop()
    elif failure == "restore":
        report["samples"][0]["max_restore_difference"] = 0.1
    else:
        report["tolerance"] = 0.3
    with pytest.raises(ValueError, match="live scoring verification"):
        train("", report["base_model"], tmp_path / "missing", tmp_path / "output",
              "must-not-start", report)
    assert not (tmp_path / "output").exists()
