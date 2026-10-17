import asyncio
import logging
from typing import Any

from nemothello.errors import AppError
from nemothello.games import Games
from nemothello.nemotron import Nemotron
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
            if task["kind"] == "branch":
                result = self.branch(owner, task)
            elif task["kind"] == "review":
                result = self.review(owner, task["game_id"])
            else:
                review = self.store.get("review", task["game_id"], owner)
                response = self.nemotron.explain(review, task["inputs"]["question"])
                result = {"answer": response["text"], "model_id": response["model_id"],
                          "usage": response["usage"]}
            task.update(status="succeeded", result=result, error=None)
        except Exception as exc:
            logger.exception("任务失败 task_id=%s", task["task_id"])
            task.update(status="failed", error={
                "code": exc.code if isinstance(exc, AppError) else "TASK_FAILED",
                "message": exc.message if isinstance(exc, AppError) else "任务执行失败，请检查服务日志后重试",
            })
        finally:
            with self.store.transaction() as db:
                if task["kind"] == "branch":
                    game = self.store.get("game", task["game_id"], owner, db)
                    game["auto_play"] = False
                    self.store.save(db, "game", game["game_id"], owner, game)
                self.store.save(db, "task", task["task_id"], owner, task)

    def branch(self, owner: str, task: dict[str, Any]) -> dict[str, Any]:
        game_id = task["game_id"]
        for step in range(61):
            if self.stop.is_set():
                raise AppError("SERVICE_STOPPING", "服务停止中断重演，可查看已保存的分支", 503)
            game = self.games.get(game_id, owner)
            if game["status"] == "finished":
                return {"game_id": game_id, "result": game["result"]}
            revision = game["revision"]
            move = None
            hint_id = None
            if game["turn"] == game["human_color"]:
                hint = self.games.hint(owner, game_id, revision, automated=True)
                move = hint["recommended_move"]
                hint_id = hint["hint_id"]
            self.games.move(
                owner, game_id, f"{task['task_id']}:{step}", revision, move,
                automated=True, hint_id=hint_id,
            )
        raise AppError("BRANCH_LENGTH", "分支超过合法对局步数，请检查棋规", 500)

    def review(self, owner: str, game_id: str) -> dict[str, Any]:
        self.nemotron.ensure_configured()
        game = self.store.get("game", game_id, owner)
        if game["status"] != "finished":
            raise AppError("REVIEW_REQUIRES_END", "对局未结束，不能生成复盘")
        hints = [hint for hint in self.store.list_records("hint", owner)
                 if hint["game_id"] == game_id and hint["displayed"]]
        position = Position(tuple(game["initial_board"]), game["initial_turn"])
        engine = self.games.review_engine_of(game)
        revision = 0
        evidence = []
        for event in game["history"]:
            if event["kind"] == "pass":
                revision = event["revision"]
                continue
            if self.stop.is_set():
                raise AppError("SERVICE_STOPPING", "服务停止中断复盘，请重新创建任务", 503)
            analysis = engine.analyze(position.board, position.turn)
            candidates = analysis["candidates"]
            actual = next(c for c in candidates if c["coordinate"] == event["coordinate"])
            best = max(candidates, key=lambda c: c["score"])
            shown = [hint for hint in hints if hint["revision"] == revision]
            evidence.append({
                "revision": revision, "actor": event["actor"], "actual_move": event["coordinate"],
                "recommended_move": best["coordinate"], "score_loss": best["score"] - actual["score"],
                "analysis": evidence_analysis(analysis),
                "shown_hint_ids": [hint["hint_id"] for hint in shown],
                "adopted_hint": any(hint["recommended_move"] == event["coordinate"] for hint in shown),
            })
            position, _ = position.play(event["coordinate"])
            revision = event["revision"]
        if list(position.board) != game["board"] or position.result() != game["result"]:
            raise AppError("REPLAY_MISMATCH", "棋谱回放与保存的终局不一致", 500)
        key_moves = sorted(evidence, key=lambda item: item["score_loss"], reverse=True)[:8]
        summary = {
            "game_id": game_id, "result": game["result"], "human_color": game["human_color"],
            "initial_board": game["initial_board"], "initial_turn": game["initial_turn"],
            "history": [
                {key: event[key] for key in ("event_index", "actor", "kind", "coordinate", "revision")}
                for event in game["history"]
            ],
            "parent_game_id": game["parent_game_id"], "parent_revision": game["parent_revision"],
            "opponent_config_id": game["opponent_config_id"], "key_moves": key_moves,
            "branch_mode": game.get("branch_mode"),
            "automatic_hint_moves": game.get("automatic_hint_moves", []),
            "hints": [{"hint_id": hint["hint_id"], "revision": hint["revision"],
                       "recommended_move": hint["recommended_move"],
                       "analysis_settings": hint["analysis"]["settings"]} for hint in hints],
            "hint_adoption": {"shown_turns": sum(bool(item["shown_hint_ids"]) for item in evidence),
                              "adopted_turns": sum(item["adopted_hint"] for item in evidence)},
        }
        response = self.nemotron.explain(summary)
        review = {**summary, "explanation": response["text"], "evidence": evidence,
                  "model_id": response["model_id"], "usage": response["usage"]}
        with self.store.transaction() as db:
            self.store.save(db, "review", game_id, owner, review)
        return review
