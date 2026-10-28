import asyncio
import logging
from typing import Any

from nemothello.coaching import REVIEW_VERSION, enrich_evidence, select_key_moves
from nemothello.errors import AppError
from nemothello.game_summary import SUMMARY_VERSION
from nemothello.games import Games, review_summary, summary_key
from nemothello.lesson_view import resolve_lesson_view
from nemothello.nemotron import Nemotron
from nemothello.position_lessons import (
    analyze_position,
    lesson_context,
    lesson_document,
    lesson_key,
    opponent_replies,
)
from nemothello.rules import Position
from nemothello.storage import Store

logger = logging.getLogger(__name__)


def evidence_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in analysis.items() if key != "raw_output"}


class Tasks:
    def __init__(self, store: Store, games: Games, nemotron: Nemotron) -> None:
        self.store = store
        self.games = games
        self.nemotron = nemotron
        self.stop = asyncio.Event()

    async def run(self) -> None:
        while not self.stop.is_set():
            queued = await asyncio.to_thread(self.store.queued_tasks)
            if queued:
                owner, task = queued[0]
                await asyncio.to_thread(self.process, owner, task)
            else:
                try:
                    await asyncio.wait_for(self.stop.wait(), timeout=0.5)
                except TimeoutError:
                    continue

    def process(self, owner: str, task: dict[str, Any]) -> None:
        with self.store.transaction() as db:
            current = self.store.get("task", task["task_id"], owner, db)
            if current["status"] != "queued":
                return
            task["status"] = "running"
            self.store.save(db, "task", task["task_id"], owner, task)
        try:
            if task["kind"] == "review":
                result = self.review(owner, task["game_id"])
            elif task["kind"] == "summary":
                result = self.summary(owner, task["game_id"], task["task_id"], task["inputs"]["language"])
            elif task["kind"] == "lesson":
                result = self.lesson(owner, task["game_id"], task["inputs"]["revision"], task["task_id"],
                                     task["inputs"].get("language", "en"))
            else:
                self.nemotron.ensure_configured()
                revision = task["inputs"]["revision"]
                language = task['inputs'].get('language', 'en')
                lesson = self.games.position_lesson(owner, task["game_id"], revision, language)
                if lesson.get('earlier_eligible') and lesson.get('earlier_decision') is None:
                    lesson['earlier_decision'] = self.games.earlier_decision(owner, task['game_id'], revision, language)
                game = self.store.get("game", task["game_id"], owner)
                review = lesson_context(game, lesson["evidence"], self.store.list_records("hint", owner))
                review['earlier_decision'] = lesson.get('earlier_decision')
                review["teaching_view"] = resolve_lesson_view(lesson["evidence"], task["inputs"].get("view"))
                response = self.nemotron.explain(review, task["inputs"]["question"], revision=revision,
                                                 language=task["inputs"].get("language", "en"))
                result = {"answer": response["answer"], "model_id": response["model_id"],
                          'language': language,
                          "usage": response["usage"], "coaching": response["coaching"],
                          "format_version": REVIEW_VERSION, "answer_facts": response["answer_facts"],
                          "topic": response["topic"], "view": task["inputs"].get("view"),
                          "tool_calls": response["tool_calls"],
                          'earlier_decision': review.get('earlier_decision')}
            task.update(status="succeeded", result=result, error=None, usage=result.get("usage"))
        except Exception as exc:
            logger.exception("Task failed task_id=%s", task["task_id"])
            task.update(status="failed", error={
                "code": exc.code if isinstance(exc, AppError) else "TASK_FAILED",
                "message": exc.message if isinstance(exc, AppError) else "Task failed. Check service logs before retrying",
            })
            task["usage"] = getattr(exc, "usage", None)
        finally:
            with self.store.transaction() as db:
                self.store.save(db, "task", task["task_id"], owner, task)

    def lesson(self, owner: str, game_id: str, revision: int, task_id: str,
               language: str = "en") -> dict[str, Any]:
        game = self.store.get("game", game_id, owner)
        saved = self.games.position_lesson(owner, game_id, revision, language)
        evidence = saved.get("evidence")
        if evidence is None:
            reviews = self.store.list_records("review", owner)
            evidence = next((item for review in reviews if review["game_id"] == game_id
                             and review.get("format_version") == REVIEW_VERSION
                             for item in review["evidence"] if item["revision"] == revision), None)
        if evidence is None:
            evidence = analyze_position(game, revision, self.games.review_engine_of(game), self.games.opponent_of(game))
        context = lesson_context(game, evidence, self.store.list_records("hint", owner))
        lesson = lesson_document(context, evidence, language)
        lesson.update(task_id=task_id, coaching_status='pending')
        key = lesson_key(game_id, revision, language)
        with self.store.transaction() as db:
            self.store.save(db, "lesson", key, owner, lesson)
        try:
            response = self.nemotron.explain(context, revision=revision, language=language)
        except Exception as exc:
            lesson.update(coaching_status="failed", coaching_error=(exc.message if isinstance(exc, AppError)
                          else "Coaching failed. Retry teaching this position"),
                          coaching_error_code=exc.code if isinstance(exc, AppError) else "TASK_FAILED",
                          usage=getattr(exc, "usage", None))
            with self.store.transaction() as db:
                self.store.save(db, "lesson", key, owner, lesson)
            raise
        lesson.update(coaching_status="ready", coaching=response["coaching"], answer=response["answer"],
                      tool_calls=response["tool_calls"], model_id=response["model_id"], usage=response["usage"])
        with self.store.transaction() as db:
            self.store.save(db, "lesson", key, owner, lesson)
        return lesson

    def review(self, owner: str, game_id: str) -> dict[str, Any]:
        # Whole-game review is engine analysis only; coaching happens per position
        existing = next((item for item in self.store.list_records("review", owner)
                         if item["game_id"] == game_id and item.get("format_version") == REVIEW_VERSION), None)
        if existing:
            return review_summary(existing)
        review = self.analyze_review(owner, game_id)
        with self.store.transaction() as db:
            self.store.save(db, "review", game_id, owner, review)
        return review_summary(review)

    def summary(self, owner: str, game_id: str, task_id: str, language: str) -> dict[str, Any]:
        game = self.store.get("game", game_id, owner)
        review = self.games.saved_review(owner, game_id)
        revisions = [move["revision"] for move in review["key_moves"]]
        items = review["evidence"]
        context = {**lesson_context(game, items[0], self.store.list_records("hint", owner)),
                   "evidence": items, "key_moves": review["key_moves"]}
        key = summary_key(game_id, language)
        document = {"game_id": game_id, "language": language, "task_id": task_id, "status": "pending",
                    "format_version": SUMMARY_VERSION,
                    "text": None, "facts": [], "tool_calls": [], "model_id": None, "usage": None,
                    "error": None, "error_code": None}
        with self.store.transaction() as db:
            self.store.save(db, "summary", key, owner, document)
        try:
            response = self.nemotron.summarize(context, revisions, language)
        except Exception as exc:
            document.update(status="failed", usage=getattr(exc, "usage", None),
                            tool_calls=getattr(exc, "tool_calls", []),
                            error=exc.message if isinstance(exc, AppError) else "Summary failed. Retry the summary",
                            error_code=exc.code if isinstance(exc, AppError) else "TASK_FAILED")
            with self.store.transaction() as db:
                self.store.save(db, "summary", key, owner, document)
            raise
        document.update(status="ready", text=response["answer"], facts=response["answer_facts"],
                        tool_calls=response["tool_calls"], model_id=response["model_id"], usage=response["usage"])
        with self.store.transaction() as db:
            self.store.save(db, "summary", key, owner, document)
        return document

    def analyze_review(self, owner: str, game_id: str) -> dict[str, Any]:
        game = self.store.get("game", game_id, owner)
        if game["status"] != "finished":
            raise AppError("REVIEW_REQUIRES_END", "Review requires a finished game")
        hints = [hint for hint in self.store.list_records("hint", owner)
                 if hint["game_id"] == game_id and hint["displayed"]]
        position = Position(tuple(game["initial_board"]), game["initial_turn"])
        engine = self.games.review_engine_of(game)
        game_opponent = self.games.opponent_of(game)
        revision = 0
        evidence = []
        for event in game["history"]:
            if event["kind"] == "pass":
                revision = event["revision"]
                continue
            if self.stop.is_set():
                raise AppError("SERVICE_STOPPING", "Service shutdown interrupted review. Create a new task", 503)
            if event["actor"] != game["human_color"]:
                position, _ = position.play(event["coordinate"])
                revision = event["revision"]
                continue
            analysis = engine.analyze(position.board, position.turn)
            candidates = analysis["candidates"]
            actual = next(c for c in candidates if c["coordinate"] == event["coordinate"])
            best = max(candidates, key=lambda c: c["score"])
            shown = [hint for hint in hints if hint["revision"] == revision]
            evidence.append(enrich_evidence({
                "revision": revision, "actor": event["actor"], "actual_move": event["coordinate"],
                "recommended_move": best["coordinate"], "score_loss": best["score"] - actual["score"],
                "analysis": evidence_analysis(analysis),
                "shown_hint_ids": [hint["hint_id"] for hint in shown],
                "adopted_hint": any(hint["recommended_move"] == event["coordinate"] for hint in shown),
                "opponent_replies": opponent_replies(position.board, position.turn, game_opponent),
            }))
            position, _ = position.play(event["coordinate"])
            revision = event["revision"]
        if list(position.board) != game["board"] or position.result() != game["result"]:
            raise AppError("REPLAY_MISMATCH", "History replay does not match the saved final position", 500)
        key_moves = select_key_moves(evidence, game["human_color"])
        return {"game_id": game_id, "format_version": REVIEW_VERSION, "evidence": evidence,
                "key_moves": [{"revision": item["revision"], "actual_move": item["actual_move"]} for item in key_moves]}
