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
    with pytest.raises(AppError, match="不同操作"):
        store.mutate("session-1", "request-1", {"color": "O"}, operation)
    with pytest.raises(AppError) as error:
        store.get("game", "game-1", "session-2")
    assert error.value.status == 404


def test_failed_transaction_does_not_save_partial_state(tmp_path):
    store = Store(tmp_path / "games.sqlite3")

    def operation(db):
        store.save(db, "game", "game-1", "session-1", {"revision": 1})
        raise ValueError("真实事务失败")

    with pytest.raises(ValueError):
        store.mutate("session-1", "request-1", {}, operation)
    assert store.list_records("game", "session-1") == []
    assert store.cached("session-1", "request-1", {}) is None


def test_restart_preserves_games_and_marks_interrupted_branch(tmp_path):
    path = tmp_path / "games.sqlite3"
    store = Store(path)
    with store.transaction() as db:
        store.save(db, "game", "game-1", "session-1", {"revision": 7, "auto_play": True})
        store.save(db, "task", "task-1", "session-1", {
            "task_id": "task-1", "game_id": "game-1", "kind": "branch", "status": "running",
        })
    restarted = Store(path)
    restarted.recover_tasks()
    assert restarted.get("game", "game-1", "session-1") == {"revision": 7, "auto_play": False}
    assert restarted.get("task", "task-1", "session-1")["status"] == "failed"


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


def test_worker_ownership_is_exclusive_and_released(tmp_path):
    path = tmp_path / "games.sqlite3"
    first = Store(path)
    second = Store(path)
    with (
        first.exclusive_worker(),
        pytest.raises(RuntimeError, match="只允许一个后端 worker"),
        second.exclusive_worker(),
    ):
        pytest.fail("第二个 worker 不应获得同一数据库的执行权")
    with second.exclusive_worker(), second.transaction() as db:
        second.save(db, "game", "game-1", "session-1", {"revision": 0})
    assert first.get("game", "game-1", "session-1")["revision"] == 0
