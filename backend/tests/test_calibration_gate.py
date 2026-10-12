import json
from pathlib import Path

import pytest

from nemothello.policy import SCORING_MODE, TEMPLATE_VERSION
from nemothello.training import train


def test_real_failed_calibration_blocks_training(tmp_path):
    report_path = Path(__file__).parent / "fixtures/pytrio-failed-calibration.json"
    report = json.loads(report_path.read_text())
    assert report["status"] == "failed"
    # Nonexistent data/output and an empty key confirm rejection before data or API access.
    with pytest.raises(ValueError, match="真实评分核验"):
        train("", report["base_model"], tmp_path / "missing-data", tmp_path / "output",
              "must-not-start", report)
    assert not (tmp_path / "output").exists()


def test_legacy_pass_report_without_batch_check_blocks_training(tmp_path):
    # This is gate metadata, not a fabricated successful model score.
    legacy_report = {"status": "passed", "base_model": "Qwen/Qwen3.5-4B",
                     "template_version": TEMPLATE_VERSION, "scoring_mode": SCORING_MODE}
    with pytest.raises(ValueError, match="真实评分核验"):
        train("", legacy_report["base_model"], tmp_path / "missing-data", tmp_path / "output",
              "must-not-start", legacy_report)
