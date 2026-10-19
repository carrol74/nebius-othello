from collections import defaultdict
from datetime import UTC, datetime
from sqlite3 import Connection
from threading import RLock
from typing import Any
from uuid import uuid4

from nemothello.coaching import REVIEW_VERSION, summary_facts
from nemothello.edax import Edax
from nemothello.errors import AppError
from nemothello.opponents import Difficulty, EdaxOpponent
from nemothello.position_lessons import check_teachable, previous_decision_revision
from nemothello.rules import Position, opponent
from nemothello.schemas import GameState
from nemothello.teaching import compare_lesson
from nemothello.storage import Store


def public_game(game: dict[str, Any]) -> dict[str, Any]:
    return GameState.model_validate(game).model_dump(mode="json")


def position_of(game: dict[str, Any]) -> Position:
    return Position(tuple(game["board"]), game["turn"])


def advance(game: dict[str, Any], move: str) -> dict[str, Any]:
    before = position_of(game)
    try:
        after, passed = before.play(move)
    except ValueError as exc:
        raise AppError("ILLEGAL_MOVE", str(exc), 422) from exc
    game["revision"] += 1
    game["history"].append({
        "event_index": len(game["history"]), "actor": before.turn, "kind": "move",
        "coordinate": move, "revision": game["revision"], "board": list(after.board),
        "turn": passed if passed else after.turn,
    })
    if passed:
        game["revision"] += 1
        game["history"].append({
            "event_index": len(game["history"]), "actor": passed, "kind": "pass",
            "coordinate": None, "revision": game["revision"], "board": list(after.board),
            "turn": after.turn,
        })
    game.update(
        board=list(after.board), turn=after.turn, legal_moves=list(after.moves),
        status="active" if after.turn else "finished", result=after.result(),
    )
    return game


class Games:
    def __init__(
        self, store: Store, opponent: EdaxOpponent,
        edax: Edax, task_limit: int,
        task_queue_limit: int = 16,
        difficulty_opponents: dict[Difficulty, EdaxOpponent] | None = None,
        difficulty_hints: dict[Difficulty, Edax] | None = None,
    ) -> None:
        self.store = store
        self.opponent = opponent
        self.difficulty_opponents = difficulty_opponents or {}
        self.opponents_by_id = {
            item.config_id: item for item in [opponent, *self.difficulty_opponents.values()]
        }
        self.edax = edax
        self.difficulty_hints = difficulty_hints or {}
        self.hint_engines = {
            engine.level: engine for engine in [edax, *self.difficulty_hints.values()]
        }
        self.task_limit = task_limit
        self.task_queue_limit = task_queue_limit
        self.locks: defaultdict[str, RLock] = defaultdict(RLock)

    def get(self, game_id: str, owner: str) -> dict[str, Any]:
        return public_game(self.store.get("game", game_id, owner))

    def create(
        self, owner: str, request_id: str, human_color: str, difficulty: Difficulty | None = None,
    ) -> dict[str, Any]:
        selected = self.opponent
        if difficulty is not None:
            if difficulty not in self.difficulty_opponents:
                raise AppError("DIFFICULTY_UNAVAILABLE", "Selected difficulty is unavailable", 422)
            selected = self.difficulty_opponents[difficulty]
        payload = {"operation": "create_game", "human_color": human_color,
                   "difficulty": difficulty}

        def operation(db: Connection) -> dict[str, Any]:
            game = self.new_game(human_color, selected=selected, difficulty=difficulty)
            self.store.save(db, "game", game["game_id"], owner, game)
            return public_game(game)

        return self.store.mutate(owner, request_id, payload, operation)

    def new_game(
        self, human_color: str, initial: Position | None = None,
        selected: EdaxOpponent | None = None, difficulty: Difficulty | None = None,
        hint_level: int | None = None,
    ) -> dict[str, Any]:
        selected = selected or self.opponent
        if initial is None:
            initial = Position()
        if initial.turn is None or not initial.moves:
            raise AppError("BRANCH_POSITION", "A branch must start from an unfinished position with legal moves", 422)
        return {
            "game_id": str(uuid4()), "revision": 0, "board": list(initial.board),
            "created_at": datetime.now(UTC).isoformat(),
            "turn": initial.turn, "human_color": human_color, "status": "active",
            "legal_moves": list(initial.moves), "history": [], "result": None,
            "initial_board": list(initial.board), "initial_turn": initial.turn,
            "opponent_config_id": selected.config_id,
            "opponent_name": selected.name, "difficulty": difficulty,
            "hint_level": (hint_level if hint_level is not None
                           else self.difficulty_hints.get(difficulty, self.edax).level),
            "opponent_config": dict(selected.configuration),
            "parent_game_id": None, "parent_revision": None,
        }

    def opponent_of(self, game: dict[str, Any]) -> EdaxOpponent:
        selected = self.opponents_by_id.get(game["opponent_config_id"])
        if selected is None:
            raise AppError("OPPONENT_CHANGED", "The original opponent is unavailable. This game cannot continue or replay with a replacement", 503)
        return selected

    def hint_engine_of(self, game: dict[str, Any]) -> Edax:
        level = game.get("hint_level") or self.edax.level
        engine = self.hint_engines.get(level)
        if engine is None:
            raise AppError("HINT_ENGINE_CHANGED", "The saved hint level is unavailable", 503)
        return engine

    def review_engine_of(self, game: dict[str, Any]) -> Edax:
        hint_engine = self.hint_engine_of(game)
        return hint_engine if hint_engine.level > self.edax.level else self.edax

    def check_turn(self, game: dict[str, Any], revision: int, human: bool) -> None:
        if game["revision"] != revision:
            raise AppError("STALE_REVISION", "The board has changed. Refresh the game")
        if game["status"] != "active":
            raise AppError("GAME_FINISHED", "This game has finished")
        expected = game["human_color"] if human else opponent(game["human_color"])
        if game["turn"] != expected:
            raise AppError("WRONG_TURN", "It is not the requested player's turn")

    def move(
        self, owner: str, game_id: str, request_id: str, revision: int,
        coordinate: str | None = None, automated: bool = False, hint_id: str | None = None,
    ) -> dict[str, Any]:
        human = coordinate is not None
        payload = {"operation": "move" if human else "ai_move", "game_id": game_id,
                   "revision": revision, "coordinate": coordinate, "hint_id": hint_id}
        with self.locks[game_id]:
            cached = self.store.cached(owner, request_id, payload)
            if cached is not None:
                return cached
            game = self.store.get("game", game_id, owner)
            if game.get("auto_play") and not automated:
                raise AppError("BRANCH_RUNNING", "Hint replay is running. Wait for it to finish")
            self.check_turn(game, revision, human)
            decision = None
            if not human:
                selected = self.opponent_of(game)
                moves = position_of(game).moves
                if len(moves) == 1:
                    coordinate = moves[0]
                else:
                    decision = selected.score(tuple(game["board"]), game["turn"])
                    coordinate = decision["coordinate"]

            def operation(db: Connection) -> dict[str, Any]:
                current = self.store.get("game", game_id, owner, db)
                self.check_turn(current, revision, human)
                updated = advance(current, coordinate)
                if automated and human:
                    hint = self.store.get("hint", hint_id, owner, db)
                    if (hint["game_id"] != game_id or hint["revision"] != revision
                            or hint["recommended_move"] != coordinate):
                        raise AppError("HINT_STRATEGY_MISMATCH", "Replay move does not match the hint evidence", 500)
                    updated.setdefault("automatic_hint_moves", []).append({
                        "revision": revision, "hint_id": hint_id, "coordinate": coordinate,
                        "analysis_settings": hint["analysis"]["settings"],
                    })
                if decision:
                    updated.setdefault("decisions", []).append({"revision": revision, **decision})
                self.store.save(db, "game", game_id, owner, updated)
                return public_game(updated)

            return self.store.mutate(owner, request_id, payload, operation)

    def hint(
        self, owner: str, game_id: str, revision: int, *, automated: bool = False,
    ) -> dict[str, Any]:
        with self.locks[game_id]:
            game = self.store.get("game", game_id, owner)
            if game.get("auto_play") and not automated:
                raise AppError("BRANCH_RUNNING", "Hint replay is running. Wait for it to finish")
            self.check_turn(game, revision, True)
            analysis = self.hint_engine_of(game).analyze(tuple(game["board"]), game["turn"])
            hint = {
                "hint_id": str(uuid4()), "game_id": game_id, "revision": revision,
                "recommended_move": analysis["recommended_move"], "analysis": analysis,
                "displayed": False,
            }
            with self.store.transaction() as db:
                self.check_turn(self.store.get("game", game_id, owner, db), revision, True)
                self.store.save(db, "hint", hint["hint_id"], owner, hint)
            return {**hint, "analysis": {
                key: value for key, value in analysis.items() if key != "raw_output"
            }}

    def display_hint(
        self, owner: str, game_id: str, request_id: str, revision: int, hint_id: str
    ) -> dict[str, Any]:
        payload = {"operation": "display_hint", "game_id": game_id,
                   "revision": revision, "hint_id": hint_id}

        def operation(db: Connection) -> dict[str, Any]:
            hint = self.store.get("hint", hint_id, owner, db)
            if hint["game_id"] != game_id or hint["revision"] != revision:
                raise AppError("STALE_HINT", "Hint does not match the requested board")
            game = self.store.get("game", game_id, owner, db)
            if game.get("branch_mode") == "follow_hints":
                raise AppError("AUTOMATIC_HINT", "Automatic replay hints are recorded by the worker, not as human displays")
            known_revisions = {0, *(event["revision"] for event in game["history"])}
            if revision not in known_revisions:
                raise AppError("STALE_HINT", "Hint position does not exist")
            hint["displayed"] = True
            self.store.save(db, "hint", hint_id, owner, hint)
            return {"hint_id": hint_id, "displayed": True}

        return self.store.mutate(owner, request_id, payload, operation)

    def branch(
        self, owner: str, game_id: str, request_id: str, revision: int, mode: str
    ) -> dict[str, Any]:
        payload = {"operation": "branch", "game_id": game_id, "revision": revision, "mode": mode}

        def operation(db: Connection) -> dict[str, Any]:
            parent = self.store.get("game", game_id, owner, db)
            selected = self.opponent_of(parent)
            if revision == 0:
                initial = Position(tuple(parent["initial_board"]), parent["initial_turn"])
            else:
                events = [event for event in parent["history"] if event["revision"] == revision]
                if not events:
                    raise AppError("BRANCH_REVISION", "Branch starting position was not found", 422)
                initial = Position(tuple(events[0]["board"]), events[0]["turn"])
            branch = self.new_game(parent["human_color"], initial, selected,
                                   parent.get("difficulty"),
                                   parent.get("hint_level") or self.edax.level)
            branch.update(parent_game_id=game_id, parent_revision=revision)
            branch["auto_play"] = mode == "follow_hints"
            branch["branch_mode"] = mode
            self.store.save(db, "game", branch["game_id"], owner, branch)
            if mode == "manual":
                return public_game(branch)
            task = self.make_task(db, owner, branch["game_id"], "branch", {})
            return self.public_task(task)

        return self.store.mutate(owner, request_id, payload, operation)

    def make_task(
        self, db: Connection, owner: str, game_id: str, kind: str, inputs: dict[str, Any]
    ) -> dict[str, Any]:
        tasks = self.store.list_records("task", owner, db)
        if sum(task["status"] in ("queued", "running") for task in tasks) >= self.task_limit:
            raise AppError("TASK_LIMIT", "Tasks are already running. Please try again later", 429, True)
        active = db.execute(
            "SELECT COUNT(*) FROM records WHERE kind='task' AND status IN ('queued','running')"
        ).fetchone()[0]
        if active >= self.task_queue_limit:
            raise AppError("TASK_QUEUE_FULL", "Task queue is full. Please try again later", 429, True)
        task = {
            "task_id": str(uuid4()), "game_id": game_id, "kind": kind,
            "status": "queued", "inputs": inputs, "result": None, "error": None,
        }
        self.store.save(db, "task", task["task_id"], owner, task)
        return task

    @staticmethod
    def public_task(task: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in task.items() if key != "inputs"}

    def create_review_task(
        self, owner: str, game_id: str, request_id: str, question: str | None = None
    ) -> dict[str, Any]:
        kind = "question" if question else "review"
        payload = {"operation": kind, "game_id": game_id, "question": question}

        def operation(db: Connection) -> dict[str, Any]:
            game = self.store.get("game", game_id, owner, db)
            if game["status"] != "finished":
                raise AppError("REVIEW_REQUIRES_END", "Explanations require a finished game")
            if question:
                self.store.get("review", game_id, owner, db)
            else:
                saved = next((item for item in self.store.list_records("review", owner, db)
                              if item["game_id"] == game_id), None)
                existing = [t for t in self.store.list_records("task", owner, db)
                            if t["game_id"] == game_id and t["kind"] == "review"
                            and (t["status"] in ("queued", "running")
                                 or (t["status"] == "succeeded" and saved
                                     and saved.get("format_version") == REVIEW_VERSION
                                     and saved.get("coaching_status") == "ready"))]
                if existing:
                    return self.public_task(existing[-1])
            task = self.make_task(db, owner, game_id, kind, {"question": question})
            return self.public_task(task)

        return self.store.mutate(owner, request_id, payload, operation)

    def review(self, owner: str, game_id: str) -> dict[str, Any]:
        self.store.get("game", game_id, owner)
        with self.store.transaction() as db:
            reviews = self.store.list_records("review", owner, db)
            for review in reviews:
                if review["game_id"] == game_id:
                    if review.get("format_version") == REVIEW_VERSION:
                        review["branch_results"] = [
                            {key: item[key] for key in ("game_id", "parent_revision", "result")}
                            for item in self.store.list_records("game", owner, db)
                            if item.get("parent_game_id") == game_id and item["status"] == "finished"
                            and item.get("branch_mode") == "follow_hints"
                            and item["opponent_config_id"] == review["opponent_config_id"]
                        ]
                        review["summary_facts"] = summary_facts(review)
                    return review
            tasks = [t for t in self.store.list_records("task", owner, db)
                     if t["game_id"] == game_id and t["kind"] == "review"]
            return {"task": self.public_task(tasks[-1]) if tasks else None}

    def position_lesson(self, owner: str, game_id: str, revision: int) -> dict[str, Any]:
        game = self.store.get("game", game_id, owner)
        check_teachable(game, revision)
        with self.store.transaction() as db:
            saved = next((item for item in self.store.list_records("lesson", owner, db)
                          if item["game_id"] == game_id and item["revision"] == revision), None)
            if saved:
                comparison = compare_lesson({"evidence": [saved["evidence"]]}, revision,
                                            saved["evidence"]["actual_move"])
                return {**saved, "comparison": comparison,
                        "evidence": {**saved["evidence"], "recommended_move": comparison["recommended_move"],
                                     "score_loss": comparison["choices"][0]["assessment"]["score_loss"]},
                        "previous_decision_revision": previous_decision_revision(game, revision)}
            tasks = [item for item in self.store.list_records("task", owner, db)
                     if item["game_id"] == game_id and item["kind"] == "lesson"
                     and item["inputs"]["revision"] == revision]
            return {"task": self.public_task(tasks[-1]) if tasks else None}

    def create_position_lesson_task(
        self, owner: str, game_id: str, request_id: str, revision: int,
        question: str | None = None,
    ) -> dict[str, Any]:
        payload = {"operation": "position_lesson", "game_id": game_id,
                   "revision": revision, "question": question}

        def operation(db: Connection) -> dict[str, Any]:
            game = self.store.get("game", game_id, owner, db)
            check_teachable(game, revision)
            saved = next((item for item in self.store.list_records("lesson", owner, db)
                          if item["game_id"] == game_id and item["revision"] == revision), None)
            if question:
                if not saved:
                    raise AppError("LESSON_NOT_FOUND", "Teach this position before asking a question", 409)
            else:
                existing = [item for item in self.store.list_records("task", owner, db)
                            if item["game_id"] == game_id and item["kind"] == "lesson"
                            and item["inputs"]["revision"] == revision
                            and (item["status"] in ("queued", "running")
                                 or (item["status"] == "succeeded" and saved
                                     and saved["coaching_status"] == "ready"))]
                if existing:
                    return self.public_task(existing[-1])
            task = self.make_task(db, owner, game_id, "question" if question else "lesson",
                                  {"revision": revision, "question": question})
            return self.public_task(task)

        return self.store.mutate(owner, request_id, payload, operation)
