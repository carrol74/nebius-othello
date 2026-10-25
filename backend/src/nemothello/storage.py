import fcntl
import json
import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Any

from nemothello.errors import AppError


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.lock = RLock()
        with self.transaction() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS records (
                    kind TEXT NOT NULL, id TEXT NOT NULL, owner TEXT NOT NULL,
                    status TEXT NOT NULL, document TEXT NOT NULL,
                    PRIMARY KEY(kind, id)
                );
                CREATE INDEX IF NOT EXISTS records_owner ON records(kind, owner, status);
                CREATE TABLE IF NOT EXISTS requests (
                    owner TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL,
                    response TEXT NOT NULL, PRIMARY KEY(owner, id)
                );
                CREATE TABLE IF NOT EXISTS request_limits (
                    bucket TEXT PRIMARY KEY, window_start REAL NOT NULL,
                    request_count INTEGER NOT NULL
                );
            """)

    @contextmanager
    def exclusive_worker(self) -> Iterator[None]:
        with self.path.with_suffix(".worker.lock").open("a") as lock_file:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("Only one backend worker may use a database; use --workers 1") from exc
            try:
                yield
            finally:
                fcntl.flock(lock_file, fcntl.LOCK_UN)

    def admit_request(self, owner: str, session_limit: int, global_limit: int, window: int) -> None:
        now = time.time()
        with self.transaction() as db:
            db.execute("DELETE FROM request_limits WHERE window_start < ?", (now - window,))
            for bucket, limit in (("global", global_limit), ("session:" + owner, session_limit)):
                row = db.execute(
                    "SELECT window_start,request_count FROM request_limits WHERE bucket=?", (bucket,)
                ).fetchone()
                start, count = (row["window_start"], row["request_count"]) if row else (now, 0)
                if count >= limit:
                    raise AppError("REQUEST_LIMIT", "Too many requests. Please try again later", 429, True)
                db.execute(
                    "INSERT INTO request_limits VALUES (?,?,?) ON CONFLICT(bucket) DO UPDATE "
                    "SET window_start=excluded.window_start, request_count=excluded.request_count",
                    (bucket, start, count + 1),
                )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.lock:
            db = sqlite3.connect(self.path, timeout=10)
            db.row_factory = sqlite3.Row
            try:
                db.execute("BEGIN IMMEDIATE")
                with db:
                    yield db
            finally:
                db.close()

    def get(
        self, kind: str, item_id: str, owner: str, db: sqlite3.Connection | None = None
    ) -> dict[str, Any]:
        if db is None:
            with self.transaction() as connection:
                return self.get(kind, item_id, owner, connection)
        row = db.execute(
            "SELECT document FROM records WHERE kind=? AND id=? AND owner=?",
            (kind, item_id, owner),
        ).fetchone()
        if row is None:
            raise AppError("NOT_FOUND", "Record not found", 404)
        return json.loads(row["document"])

    def save(
        self, db: sqlite3.Connection, kind: str, item_id: str, owner: str,
        document: dict[str, Any],
    ) -> None:
        db.execute(
            "INSERT INTO records VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(kind,id) DO UPDATE SET status=excluded.status, document=excluded.document",
            (kind, item_id, owner, document.get("status", ""), json.dumps(document)),
        )

    def cached(
        self, owner: str, request_id: str, payload: dict[str, Any],
        db: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        if db is None:
            with self.transaction() as connection:
                return self.cached(owner, request_id, payload, connection)
        row = db.execute(
            "SELECT payload,response FROM requests WHERE owner=? AND id=?", (owner, request_id)
        ).fetchone()
        if row is None:
            return None
        if json.loads(row["payload"]) != payload:
            raise AppError("REQUEST_CONFLICT", "A request ID cannot be reused for different operations")
        return json.loads(row["response"])

    def mutate(
        self, owner: str, request_id: str, payload: dict[str, Any],
        operation: Callable[[sqlite3.Connection], dict[str, Any]],
    ) -> dict[str, Any]:
        with self.transaction() as db:
            cached = self.cached(owner, request_id, payload, db)
            if cached is not None:
                return cached
            response = operation(db)
            db.execute(
                "INSERT INTO requests VALUES (?,?,?,?)",
                (owner, request_id, json.dumps(payload), json.dumps(response)),
            )
            return response

    def list_records(
        self, kind: str, owner: str, db: sqlite3.Connection | None = None
    ) -> list[dict[str, Any]]:
        if db is None:
            with self.transaction() as connection:
                return self.list_records(kind, owner, connection)
        rows = db.execute(
            "SELECT document FROM records WHERE kind=? AND owner=? ORDER BY rowid", (kind, owner)
        ).fetchall()
        return [json.loads(row["document"]) for row in rows]

    def queued_tasks(self) -> list[tuple[str, dict[str, Any]]]:
        with self.transaction() as db:
            rows = db.execute(
                "SELECT owner,document FROM records WHERE kind='task' AND status='queued' "
                "ORDER BY rowid LIMIT 1"
            ).fetchall()
            return [(row["owner"], json.loads(row["document"])) for row in rows]

    def finished_games(self, owner: str) -> list[dict[str, Any]]:
        with self.transaction() as db:
            rows = db.execute(
                "SELECT document FROM records WHERE kind='game' AND owner=? "
                "AND status='finished' ORDER BY rowid DESC LIMIT 20", (owner,)
            ).fetchall()
            return [json.loads(row["document"]) for row in rows]

    def recover_tasks(self) -> None:
        with self.transaction() as db:
            rows = db.execute(
                "SELECT owner,id,document FROM records WHERE kind='task' AND status='running'"
            ).fetchall()
            for row in rows:
                task = json.loads(row["document"])
                task.update(status="failed", error={
                    "code": "SERVICE_RESTARTED", "message": "Service restart interrupted this task. Create a new task",
                })
                if task["kind"] == "branch":
                    game = self.get("game", task["game_id"], row["owner"], db)
                    game["auto_play"] = False
                    self.save(db, "game", task["game_id"], row["owner"], game)
                self.save(db, "task", row["id"], row["owner"], task)
