from collections import defaultdict
from datetime import UTC, datetime
from sqlite3 import Connection
from threading import RLock
from typing import Any
from uuid import uuid4

from nemothello.coaching import COACH_VERSION, REVIEW_VERSION
from nemothello.earlier_decision import earlier_target, find_earlier_decision
from nemothello.edax import Edax
from nemothello.errors import AppError
from nemothello.game_summary import SUMMARY_VERSION, display_saved_summary
from nemothello.lesson_view import resolve_lesson_view
from nemothello.opponents import Difficulty, EdaxOpponent
from nemothello.position_lessons import (
    check_teachable,
    lesson_context,
    lesson_document,
    lesson_key,
    opponent_replies,
    reply_scores,
)
from nemothello.rules import Position, opponent
from nemothello.schemas import GameState
from nemothello.storage import Store
from nemothello.summary_validation import POSITION_REFERENCE
from nemothello.teaching import compare_lesson, variation_frames


def review_summary(review: dict[str, Any]) -> dict[str, Any]:
    evidence = {item["revision"]: item for item in review["evidence"]}
    return {"game_id": review["game_id"], "key_moves": [
        {**move, "reason": compare_lesson({"evidence": [evidence[move["revision"]]]}, move["revision"],
                                          move["actual_move"])["reason"]}
        for move in review["key_moves"]]}


def summary_key(game_id: str, language: str) -> str:
    return f"{game_id}:{language}"


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


# Task kinds that call Nemotron and spend Token Factory credit
MODEL_TASKS = ("lesson", "question", "summary")


class Games:
    def __init__(
        self, store: Store, opponent: EdaxOpponent,
        edax: Edax, task_limit: int,
        task_queue_limit: int = 16,
        difficulty_opponents: dict[Difficulty, EdaxOpponent] | None = None,
        difficulty_hints: dict[Difficulty, Edax] | None = None,
        model_tasks_per_day: int = 300,
        model_tasks_per_session_per_day: int = 30,
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
        self.model_tasks_per_day = model_tasks_per_day
        self.model_tasks_per_session_per_day = model_tasks_per_session_per_day
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
        # Reviews teach at the game's level, matching the hints shown during play
        return self.hint_engine_of(game)

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
        coordinate: str | None = None,
    ) -> dict[str, Any]:
        human = coordinate is not None
        payload = {"operation": "move" if human else "ai_move", "game_id": game_id,
                   "revision": revision, "coordinate": coordinate}
        with self.locks[game_id]:
            cached = self.store.cached(owner, request_id, payload)
            if cached is not None:
                return cached
            game = self.store.get("game", game_id, owner)
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
                if decision:
                    updated.setdefault("decisions", []).append({"revision": revision, **decision})
                self.store.save(db, "game", game_id, owner, updated)
                return public_game(updated)

            return self.store.mutate(owner, request_id, payload, operation)

    def hint(self, owner: str, game_id: str, revision: int) -> dict[str, Any]:
        with self.locks[game_id]:
            game = self.store.get("game", game_id, owner)
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
            known_revisions = {0, *(event["revision"] for event in game["history"])}
            if revision not in known_revisions:
                raise AppError("STALE_HINT", "Hint position does not exist")
            hint["displayed"] = True
            self.store.save(db, "hint", hint_id, owner, hint)
            return {"hint_id": hint_id, "displayed": True}

        return self.store.mutate(owner, request_id, payload, operation)

    def branch(self, owner: str, game_id: str, request_id: str, revision: int,
               line: list[str] | None = None) -> dict[str, Any]:
        line = line or []
        payload = {"operation": "branch", "game_id": game_id, "revision": revision, "line": line}

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
            try:
                frame = variation_frames(initial.board, initial.turn, line)[-1]
            except AppError as exc:
                raise AppError("BRANCH_LINE", "Continue from a legal line of the saved position", 422) from exc
            initial = Position(tuple(frame["board"]), frame["turn"])
            if initial.turn is not None and not initial.moves:
                initial = Position(initial.board, opponent(initial.turn))
            branch = self.new_game(parent["human_color"], initial, selected,
                                   parent.get("difficulty"),
                                   parent.get("hint_level") or self.edax.level)
            branch.update(parent_game_id=game_id, parent_revision=revision, parent_line=line)
            self.store.save(db, "game", branch["game_id"], owner, branch)
            return public_game(branch)

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
        now = datetime.now(UTC)
        if kind in MODEL_TASKS:
            # Sessions are free to create, so the service-wide count is what caps spending
            owners = [row[0] for row in db.execute(
                "SELECT owner FROM records WHERE kind='task' AND json_extract(document, '$.kind') IN (?, ?, ?) "
                "AND substr(json_extract(document, '$.created_at'), 1, 10) = ?",
                (*MODEL_TASKS, now.date().isoformat()))]
            if (len(owners) >= self.model_tasks_per_day
                    or owners.count(owner) >= self.model_tasks_per_session_per_day):
                raise AppError("MODEL_DAILY_LIMIT", "Today's coaching limit has been reached. Try again tomorrow", 429)
        task = {
            "task_id": str(uuid4()), "game_id": game_id, "kind": kind, "created_at": now.isoformat(),
            "status": "queued", "inputs": inputs, "result": None, "error": None,
        }
        self.store.save(db, "task", task["task_id"], owner, task)
        return task

    @staticmethod
    def public_task(task: dict[str, Any]) -> dict[str, Any]:
        return {**{key: value for key, value in task.items() if key != "inputs"},
                'language': task.get('inputs', {}).get('language', 'en')}

    def create_review_task(self, owner: str, game_id: str, request_id: str) -> dict[str, Any]:
        payload = {"operation": "review", "game_id": game_id}

        def operation(db: Connection) -> dict[str, Any]:
            game = self.store.get("game", game_id, owner, db)
            if game["status"] != "finished":
                raise AppError("REVIEW_REQUIRES_END", "Finish this game before reviewing it")
            saved = next((item for item in self.store.list_records("review", owner, db)
                          if item["game_id"] == game_id), None)
            existing = [t for t in self.store.list_records("task", owner, db)
                        if t["game_id"] == game_id and t["kind"] == "review"
                        and (t["status"] in ("queued", "running")
                             or (t["status"] == "succeeded" and saved
                                 and saved.get("format_version") == REVIEW_VERSION))]
            if existing:
                return self.public_task(existing[-1])
            task = self.make_task(db, owner, game_id, "review", {})
            return self.public_task(task)

        return self.store.mutate(owner, request_id, payload, operation)

    def saved_review(self, owner: str, game_id: str, db: Connection | None = None) -> dict[str, Any] | None:
        return next((item for item in self.store.list_records("review", owner, db)
                     if item["game_id"] == game_id and item.get("format_version") == REVIEW_VERSION), None)

    def saved_summary(self, owner: str, game_id: str, language: str,
                      db: Connection | None = None) -> dict[str, Any] | None:
        summary = next((item for item in self.store.list_records("summary", owner, db)
                        if item["game_id"] == game_id and item["language"] == language
                        and item.get("format_version") == SUMMARY_VERSION), None)
        if summary and summary["status"] == "ready" and POSITION_REFERENCE.search(summary["text"]):
            review = self.saved_review(owner, game_id, db)
            if review is not None:
                return display_saved_summary(summary, review)
        return summary

    def queue_summary(self, db: Connection, owner: str, game_id: str, language: str) -> dict[str, Any]:
        review = self.saved_review(owner, game_id, db)
        if review is None or not review["evidence"]:
            raise AppError("SUMMARY_UNAVAILABLE", "A summary requires a reviewed game with played human moves", 409)
        saved = self.saved_summary(owner, game_id, language, db)
        existing = [task for task in self.store.list_records("task", owner, db)
                    if task["game_id"] == game_id and task["kind"] == "summary"
                    and task["inputs"]["language"] == language
                    and (task["status"] in ("queued", "running")
                         or (task["status"] == "succeeded" and saved and saved["status"] == "ready"))]
        if existing:
            return existing[-1]
        return self.make_task(db, owner, game_id, "summary", {"language": language})

    def create_summary_task(self, owner: str, game_id: str, request_id: str, language: str = "en") -> dict[str, Any]:
        payload = {"operation": "summary", "game_id": game_id, "language": language}

        def operation(db: Connection) -> dict[str, Any]:
            self.store.get("game", game_id, owner, db)
            return self.public_task(self.queue_summary(db, owner, game_id, language))

        return self.store.mutate(owner, request_id, payload, operation)

    def summary(self, owner: str, game_id: str, language: str = "en") -> dict[str, Any]:
        self.store.get("game", game_id, owner)
        with self.store.transaction() as db:
            saved = self.saved_summary(owner, game_id, language, db)
            if saved:
                return saved
            tasks = [task for task in self.store.list_records("task", owner, db)
                     if task["game_id"] == game_id and task["kind"] == "summary"
                     and task["inputs"]["language"] == language and task["status"] in ("queued", "running")]
            return {"task": self.public_task(tasks[-1]) if tasks else None}

    def review(self, owner: str, game_id: str) -> dict[str, Any]:
        self.store.get("game", game_id, owner)
        with self.store.transaction() as db:
            review = self.saved_review(owner, game_id, db)
            if review:
                return review_summary(review)
            tasks = [t for t in self.store.list_records("task", owner, db)
                     if t["game_id"] == game_id and t["kind"] == "review"]
            return {"task": self.public_task(tasks[-1]) if tasks else None}

    def _lesson_at(self, db, owner, game, revision, language='en'):
        candidates = [item for item in self.store.list_records('lesson', owner, db)
                      if item['game_id'] == game['game_id'] and item['revision'] == revision]
        saved = next((item for item in candidates if item.get('language') == language
                      and item.get('coaching_version') == COACH_VERSION), None)
        if saved and 'reply_scores' in saved['evidence']:
            return saved
        # Without a saved lesson, build the rules lesson from the whole-game analysis; no model call
        review = next((item for item in self.store.list_records('review', owner, db)
                       if item['game_id'] == game['game_id'] and item.get('format_version') == REVIEW_VERSION), None)
        source = saved or (candidates[-1] if candidates else None)
        evidence = next((item for item in review['evidence'] if item['revision'] == revision), None) if review else None
        if source:
            evidence = source['evidence']
        if evidence is None:
            return None
        if 'reply_scores' not in evidence:
            board = tuple(evidence['analysis']['board'])
            evidence = {**evidence, 'opponent_replies': opponent_replies(board, evidence['actor'], self.opponent_of(game)),
                        'reply_scores': reply_scores(board, evidence['actor'], evidence['actual_move'],
                                                     evidence['score_loss'], self.review_engine_of(game))}
        document = lesson_document(lesson_context(game, evidence, self.store.list_records('hint', owner, db)), evidence, language)
        if source:
            self.store.save(db, 'lesson', lesson_key(game['game_id'], revision, language), owner, document)
        return document

    def position_lesson(self, owner: str, game_id: str, revision: int, language: str = 'en') -> dict[str, Any]:
        game = self.store.get("game", game_id, owner)
        check_teachable(game, revision)
        with self.store.transaction() as db:
            saved = self._lesson_at(db, owner, game, revision, language)
            if saved:
                comparison = compare_lesson({"evidence": [saved["evidence"]]}, revision,
                                            saved["evidence"]["actual_move"])
                return {**saved, "comparison": comparison,
                        "evidence": {**saved["evidence"], "recommended_move": comparison["recommended_move"],
                                     "score_loss": comparison["choices"][0]["assessment"]["score_loss"]},
                        "earlier_eligible": earlier_target(game, saved['evidence'], comparison) is not None}
            tasks = [item for item in self.store.list_records("task", owner, db)
                     if item["game_id"] == game_id and item["kind"] == "lesson"
                     and item['inputs'].get('language', 'en') == language
                     and item["inputs"]["revision"] == revision]
            return {"task": self.public_task(tasks[-1]) if tasks else None}

    def earlier_decision(self, owner, game_id, revision, language='en'):
        saved = self.position_lesson(owner, game_id, revision, language)
        if 'evidence' not in saved:
            raise AppError('LESSON_NOT_FOUND', 'Teach this position before checking earlier choices', 409)
        game = self.store.get('game', game_id, owner)
        result = saved.get('earlier_decision')
        if result is None:
            known = {item['revision']: item['evidence']
                     for item in self.store.list_records('lesson', owner) if item['game_id'] == game_id
                     and 'reply_scores' in item['evidence']}
            result = find_earlier_decision(game, saved['evidence'], saved['comparison'], self.review_engine_of(game),
                                           self.opponent_of(game), known)
        with self.store.transaction() as db:
            current = self._lesson_at(db, owner, game, revision, language)
            if any(current['evidence'][key] != saved['evidence'][key]
                   for key in ('revision', 'actor', 'actual_move', 'analysis')):
                raise AppError('LESSON_CHANGED', 'Reload the position before checking earlier choices', 409)
            current['earlier_decision'] = result
            self.store.save(db, 'lesson', lesson_key(game_id, revision, language), owner, current)
            if result['link'] is not None:
                earlier_revision = result['link']['revision']
                existing = self._lesson_at(db, owner, game, earlier_revision, language)
                if not existing:
                    context = lesson_context(game, result['link']['evidence'], self.store.list_records('hint', owner, db))
                    self.store.save(db, 'lesson', lesson_key(game_id, earlier_revision, language), owner,
                                    lesson_document(context, result['link']['evidence'], language))
        return result

    def create_position_lesson_task(
        self, owner: str, game_id: str, request_id: str, revision: int,
        question: str | None = None,
        view: dict[str, Any] | None = None,
        language: str = "en",
    ) -> dict[str, Any]:
        payload = {"operation": "position_lesson", "game_id": game_id,
                   "revision": revision, "question": question, "view": view, "language": language}

        def operation(db: Connection) -> dict[str, Any]:
            game = self.store.get("game", game_id, owner, db)
            check_teachable(game, revision)
            saved = self._lesson_at(db, owner, game, revision, language)
            if question:
                if not saved:
                    raise AppError("LESSON_NOT_FOUND", "Teach this position before asking a question", 409)
                resolved = resolve_lesson_view(saved["evidence"], view)
                question_view = {key: resolved[key] for key in ("selected_move", "line")}
            else:
                previous = [item for item in self.store.list_records("task", owner, db)
                            if item["game_id"] == game_id and item["kind"] == "lesson"
                            and item["inputs"]["revision"] == revision]
                existing = [item for item in previous
                            if item['inputs'].get('language', 'en') == language
                            and item['inputs'].get('coaching_version') == COACH_VERSION
                            and (item["status"] in ("queued", "running")
                                 or (item["status"] == "succeeded" and saved
                                     and saved["coaching_status"] == "ready"))]
                if existing:
                    return self.public_task(existing[-1])
            task = self.make_task(db, owner, game_id, "question" if question else "lesson",
                                  {"revision": revision, "question": question, "language": language, 'coaching_version': COACH_VERSION,
                                   "view": question_view if question else None})
            return self.public_task(task)

        return self.store.mutate(owner, request_id, payload, operation)
