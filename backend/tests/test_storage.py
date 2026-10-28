import pytest

from nemothello.errors import AppError
from nemothello.storage import Store


def test_idempotency_and_owner_isolation(tmp_path):
    store = Store(tmp_path / "games.sqlite3")

    def operation(db):
        record = {"game_id": "game-1", "revision": 0, "status": "active"}
        store.save(db, "game", "game-1", "session-1", record)
        return record

    first = store.mutate("session-1", "request-1", {"color": "X"}, operation)
    second = store.mutate("session-1", "request-1", {"color": "X"}, operation)
    assert first == second
    assert len(store.list_records("game", "session-1")) == 1
    with pytest.raises(AppError, match="different operations"):
        store.mutate("session-1", "request-1", {"color": "O"}, operation)
    with pytest.raises(AppError) as error:
        store.get("game", "game-1", "session-2")
    assert error.value.status == 404


def test_failed_transaction_does_not_save_partial_state(tmp_path):
    store = Store(tmp_path / "games.sqlite3")

    def operation(db):
        store.save(db, "game", "game-1", "session-1", {"revision": 1})
        raise ValueError("Actual transaction failure")

    with pytest.raises(ValueError):
        store.mutate("session-1", "request-1", {}, operation)
    assert store.list_records("game", "session-1") == []
    assert store.cached("session-1", "request-1", {}) is None


def test_restart_preserves_games_and_marks_interrupted_tasks(tmp_path):
    path = tmp_path / "games.sqlite3"
    store = Store(path)
    with store.transaction() as db:
        store.save(db, "game", "game-1", "session-1", {"revision": 7})
        store.save(db, "task", "task-1", "session-1", {
            "task_id": "task-1", "game_id": "game-1", "kind": "lesson", "status": "running",
        })
    restarted = Store(path)
    restarted.recover_tasks()
    assert restarted.get("game", "game-1", "session-1") == {"revision": 7}
    task = restarted.get("task", "task-1", "session-1")
    assert task["status"] == "failed" and task["error"]["code"] == "SERVICE_RESTARTED"


def test_request_limits_persist_and_rejection_rolls_back_global_count(tmp_path):
    path = tmp_path / "games.sqlite3"
    store = Store(path)
    store.admit_request("session-1", session_limit=1, global_limit=2, window=3600)
    restarted = Store(path)
    with pytest.raises(AppError) as rejected:
        restarted.admit_request("session-1", session_limit=1, global_limit=2, window=3600)
    assert rejected.value.status == 429
    restarted.admit_request("session-2", session_limit=1, global_limit=2, window=3600)
    with pytest.raises(AppError) as global_rejection:
        restarted.admit_request("session-3", session_limit=1, global_limit=2, window=3600)
    assert global_rejection.value.code == "REQUEST_LIMIT"


@pytest.mark.parametrize("task_status", ["running", "failed"])
def test_restart_marks_pending_summary_failed_without_touching_other_summaries(tmp_path, task_status):
    store = Store(tmp_path / "summary.sqlite3")
    with store.transaction() as db:
        for language, status in (("en", task_status), ("zh", "queued")):
            store.save(db, "task", language, "owner", {
                "task_id": language, "kind": "summary", "status": status,
                "error": {"code": "SERVICE_RESTARTED", "message": "Generation was interrupted"}
                if status == "failed" else None,
            })
            store.save(db, "summary", language, "owner", {
                "task_id": language, "language": language, "status": "pending", "usage": {"requests": 1},
            })
        store.save(db, "summary", "ready", "owner", {"status": "ready", "text": "Saved explanation"})
    Store(store.path).recover_tasks()
    summary = store.get("summary", "en", "owner")
    assert summary["status"] == "failed"
    assert summary["error_code"] == "SERVICE_RESTARTED"
    assert summary["usage"] == {"requests": 1}
    assert store.get("summary", "zh", "owner")["status"] == "pending"
    assert store.get("task", "zh", "owner")["status"] == "queued"
    assert store.get("summary", "ready", "owner")["text"] == "Saved explanation"
    store.recover_tasks()
    assert store.get("summary", "en", "owner") == summary


def test_worker_ownership_is_exclusive_and_released(tmp_path):
    path = tmp_path / "games.sqlite3"
    first = Store(path)
    second = Store(path)
    with (
        first.exclusive_worker(),
        pytest.raises(RuntimeError, match="Only one backend worker"),
        second.exclusive_worker(),
    ):
        pytest.fail("A second worker must not acquire ownership of the same database")
    with second.exclusive_worker(), second.transaction() as db:
        second.save(db, "game", "game-1", "session-1", {"revision": 0})
    assert first.get("game", "game-1", "session-1")["revision"] == 0
