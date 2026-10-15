import math
from typing import Any

from nemothello.policy import (
    GENERATION_MODE,
    GENERATION_SETTINGS,
    SCORING_MODE,
    SYMBOLS,
    TEMPLATE_VERSION,
    TEMPLATE_VERSIONS,
)

GENERATION_CALIBRATION = "single-token-generation-v1"


def calibration_passed(
    report: dict[str, Any], base_model: str, mode: str, template_version: str = TEMPLATE_VERSION,
) -> bool:
    if (template_version not in TEMPLATE_VERSIONS
            or report.get("status") != "passed" or report.get("base_model") != base_model
            or report.get("template_version") != template_version
            or report.get("scoring_mode") != mode):
        return False
    if mode == SCORING_MODE:
        return template_version == TEMPLATE_VERSION and report.get("batch_order_checked") is True
    if mode != GENERATION_MODE:
        return False
    samples = report.get("samples", [])
    checks = report.get("checks", {})
    if (report.get("calibration_kind") != GENERATION_CALIBRATION
            or report.get("symbols") != SYMBOLS
            or report.get("generation_settings") != GENERATION_SETTINGS
            or report.get("repeat_count", 0) < 3 or len(samples) < 2
            or any(checks.get(name) is not True for name in
                   ("encoding", "train_restore", "legal_outputs", "repeat_selection",
                    "sampler_restore_selection"))):
        return False
    repeats = report["repeat_count"]
    tolerance = report.get("tolerance")
    if (type(tolerance) not in (int, float) or not math.isfinite(tolerance)
            or not 0 <= tolerance <= 1e-4):
        return False
    for sample in samples:
        before, after = sample.get("before", []), sample.get("after", [])
        if len(before) != repeats or len(after) != repeats:
            return False
        difference = sample.get("max_restore_difference")
        if (type(difference) not in (int, float) or not math.isfinite(difference)
                or not 0 <= difference <= tolerance):
            return False
        outputs = before + after
        if (any(item.get("legal") is not True or not item.get("coordinate") for item in outputs)
                or len({item["coordinate"] for item in outputs}) != 1):
            return False
    return True
