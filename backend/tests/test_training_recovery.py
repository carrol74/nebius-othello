import asyncio
import json
from copy import deepcopy
from subprocess import CompletedProcess
from types import SimpleNamespace

import httpx
import pytest
from pytrio.errors.actor import ActorEventSubmitError
from pytrio.transport.retry import request_with_retry_timeout

from nemothello.training import validate_training_output
from nemothello.training_recovery import (
    atomic_json,
    recoverable_error,
    supervise_training,
    validate_progress,
)


def test_atomic_progress_failure_keeps_previous_checkpoint_and_cleans_tmp(tmp_path):
    path = tmp_path / "progress.json"
    atomic_json(path, {"next_batch": 25})
    with pytest.raises(ValueError):
        atomic_json(path, {"next_batch": float("nan")})
    assert json.loads(path.read_text()) == {"next_batch": 25}
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("change", ["epoch", "batch", "updates", "state"])
def test_resume_rejects_inconsistent_progress(change):
    progress = {"version": 1, "next_epoch": 0, "next_batch": 2,
                "state_path": "trio://test/checkpoint", "history": [],
                "updates": [{"batch": 0}, {"batch": 1}]}
    validate_progress(progress, 5, 2)
    invalid = deepcopy(progress)
    if change == "epoch":
        invalid["next_epoch"] = 1
    elif change == "batch":
        invalid["next_batch"] = 6
    elif change == "updates":
        invalid["updates"][1]["batch"] = 0
    else:
        invalid["state_path"] = ""
    with pytest.raises(ValueError, match="不能续训"):
        validate_progress(invalid, 5, 2)


def test_zero_sdk_retry_window_does_not_resend_uncertain_post():
    calls = []

    async def request():
        calls.append("submitted")
        raise httpx.ReadTimeout("response lost after submission")

    with pytest.raises(httpx.ReadTimeout):
        asyncio.run(request_with_retry_timeout(request, retry_timeout=0, initial_delay=0,
                                              multiplier=2, max_delay=1, jitter=0))
    assert calls == ["submitted"]


def test_conflict_is_recoverable_only_by_checkpoint_rollback():
    error = ActorEventSubmitError("index already scheduled", code="conflict", status_code=409)
    assert recoverable_error(error)
    assert not recoverable_error(ValueError("invalid loss"))


def arguments(tmp_path, restarts):
    return SimpleNamespace(dataset=tmp_path, calibration=tmp_path / "calibration.json",
                           output=tmp_path, name="test", rank=32, learning_rate=1e-4,
                           batch_size=16, epochs=2, seed=42, checkpoint_every=25,
                           resume=False, max_restarts=restarts)


def test_supervisor_starts_new_process_with_resume(monkeypatch, tmp_path):
    commands = []

    def child(command, check):
        commands.append(list(command))
        if len(commands) == 1:
            atomic_json(tmp_path / "training-status.json", {"status": "interrupted", "recoverable": True})
            atomic_json(tmp_path / "training-progress.json", {"state_path": "trio://test/checkpoint"})
            return CompletedProcess(command, 1)
        return CompletedProcess(command, 0)

    monkeypatch.setattr("nemothello.training_recovery.subprocess.run", child)
    supervise_training(arguments(tmp_path, 2))
    assert "--resume" not in commands[0]
    assert "--resume" in commands[1]
    assert commands[1][commands[1].index("--max-restarts") + 1] == "0"


def test_supervisor_does_not_retry_stale_failure_report(monkeypatch, tmp_path):
    atomic_json(tmp_path / "training-status.json", {"status": "interrupted", "recoverable": True})
    atomic_json(tmp_path / "training-progress.json", {"state_path": "trio://test/checkpoint"})
    commands = []

    def child(command, check):
        commands.append(command)
        return CompletedProcess(command, 2)

    monkeypatch.setattr("nemothello.training_recovery.subprocess.run", child)
    with pytest.raises(SystemExit) as error:
        supervise_training(arguments(tmp_path, 2))
    assert error.value.code == 2
    assert len(commands) == 1


def test_missing_training_answers_are_rejected_before_optimizer():
    with pytest.raises(ValueError, match="答案数量不完整"):
        validate_training_output(SimpleNamespace(loss_fn_outputs=[], metrics={}), [85])


def test_supervisor_limits_restarts(monkeypatch, tmp_path):
    commands = []

    def child(command, check):
        commands.append(command)
        atomic_json(tmp_path / "training-status.json", {
            "status": "interrupted", "recoverable": True, "attempt": len(commands),
        })
        atomic_json(tmp_path / "training-progress.json", {"state_path": "trio://test/checkpoint"})
        return CompletedProcess(command, 1)

    monkeypatch.setattr("nemothello.training_recovery.subprocess.run", child)
    with pytest.raises(SystemExit):
        supervise_training(arguments(tmp_path, 1))
    assert len(commands) == 2
