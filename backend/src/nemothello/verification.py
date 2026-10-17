import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from nemothello.data import write_json
from nemothello.rules import Position, replay
from nemothello.schemas import GameState, Review, Task


class DemoVerification:
    def __init__(self, base_url: str, service_token: str, output: Path, task_timeout: float):
        if not service_token.strip() or task_timeout <= 0:
            raise ValueError("Live verification requires a service token and a positive task timeout")
        self.owner = str(uuid4())
        self.output, self.task_timeout = output, task_timeout
        self.http = httpx.Client(
            base_url=base_url.rstrip("/") + "/", timeout=240,
            headers={"Authorization": "Bearer " + service_token, "X-Session-ID": self.owner},
        )
        self.report: dict[str, Any] = {
            "status": "running", "source": "live-backend-api", "session_id": self.owner,
            "requests": [],
            "games": {}, "checks": [],
            "limits": "Verifies live service flows; does not verify browser rendering or actual hint display, and does not record hint displays.",
        }

    def request(self, method: str, path: str, body: dict | None = None, expected: int = 200, **kwargs):
        started = time.monotonic()
        response = self.http.request(method, path, json=body, **kwargs)
        self.report["requests"].append({
            "method": method, "path": path, "status": response.status_code,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
        })
        write_json(self.output, self.report)
        if response.status_code != expected:
            raise ValueError(f"{method} {path} returned {response.status_code}, expected {expected}")
        return response.json()

    def check(self, condition: bool, name: str) -> None:
        if not condition:
            raise ValueError(name)
        self.report["checks"].append(name)
        write_json(self.output, self.report)

    def wait_task(self, task: dict[str, Any]) -> dict[str, Any]:
        deadline = time.monotonic() + self.task_timeout
        while True:
            task = Task.model_validate(task).model_dump(mode="json")
            if task["status"] == "succeeded":
                return task
            if task["status"] == "failed":
                self.report["failed_task"] = task
                raise ValueError(f"Live task failed: {task['task_id']}")
            if time.monotonic() >= deadline:
                self.report["unfinished_task"] = task
                raise TimeoutError("Task observation timed out. The task may still be running; do not submit a duplicate")
            time.sleep(1)
            task = self.request("GET", f"tasks/{task['task_id']}")

    def game(self, payload: dict[str, Any]) -> dict[str, Any]:
        game = GameState.model_validate(payload).model_dump(mode="json")
        initial = Position(tuple(game["initial_board"]), game["initial_turn"])
        position = replay([event["coordinate"] for event in game["history"]
                           if event["kind"] == "move"], initial)
        if (list(position.board) != game["board"] or position.turn != game["turn"]
                or list(position.moves) != game["legal_moves"] or position.result() != game["result"]):
            raise ValueError("Service board, legal moves, or result differs from history replay")
        return game

    def run(self) -> dict[str, Any]:
        try:
            create = {"human_color": "X", "request_id": str(uuid4())}
            original = self.game(self.request("POST", "games", create))
            game_id = original["game_id"]
            self.check(self.request("POST", "games", create) == original, "Repeated creation returns the same game")
            self.request("GET", f"games/{game_id}", expected=404,
                         headers={"X-Session-ID": str(uuid4())})
            self.report["checks"].append("Another session cannot read the game")
            hint = self.request("POST", f"games/{game_id}/hint", {"expected_revision": 0})
            self.check(
                {c["coordinate"] for c in hint["analysis"]["candidates"]} == set(original["legal_moves"])
                and hint["recommended_move"] in original["legal_moves"],
                "Live Edax analysis covers all legal moves",
            )
            for step in range(61):
                if original["status"] == "finished":
                    break
                revision = original["revision"]
                body = {"expected_revision": revision, "request_id": str(uuid4())}
                human = original["turn"] == original["human_color"]
                route = "moves" if human else "ai-move"
                if human:
                    body["coordinate"] = original["legal_moves"][0]
                path = f"games/{game_id}/{route}"
                next_game = self.game(self.request("POST", path, body))
                if step == 0:
                    self.check(self.request("POST", path, body) == next_game,
                               "Repeated move request returns the original result")
                    stale = {**body, "request_id": str(uuid4())}
                    error = self.request("POST", path, stale, expected=409)
                    self.check(error["code"] == "STALE_REVISION", "New request with a stale revision is rejected")
                original = next_game
            self.check(original["status"] == "finished", "Live opponent completes a full game")
            self.report["games"]["original"] = original
            review_task = self.request("POST", f"games/{game_id}/reviews", {"request_id": str(uuid4())})
            self.wait_task(review_task)
            review = Review.model_validate(self.request("GET", f"games/{game_id}/review"))
            self.check(bool(review.explanation.strip()) and bool(review.model_id), "Live review returns model identity and explanation")
            self.check(review.hint_adoption.shown_turns == 0, "Programmatic analysis does not claim hints were displayed")
            self.report["review"] = review.model_dump(mode="json")
            question = self.wait_task(self.request("POST", f"games/{game_id}/review/questions", {
                "request_id": str(uuid4()), "question": "Reference a specific position revision and explain the main improvement for this game.",
            }))
            self.check(bool(question["result"]["answer"].strip()), "Live review question returns an answer")
            self.report["question"] = question["result"]
            manual = self.game(self.request("POST", f"games/{game_id}/branches", {
                "request_id": str(uuid4()), "revision": 0, "mode": "manual",
            }))
            manual = self.game(self.request("POST", f"games/{manual['game_id']}/moves", {
                "request_id": str(uuid4()), "expected_revision": 0,
                "coordinate": manual["legal_moves"][0],
            }))
            self.report["games"]["manual_branch"] = manual
            branch_task = self.wait_task(self.request("POST", f"games/{game_id}/branches", {
                "request_id": str(uuid4()), "revision": 0, "mode": "follow_hints",
            }))
            branch = self.game(self.request("GET", f"games/{branch_task['game_id']}"))
            self.check(branch["status"] == "finished" and not branch["auto_play"],
                       "Hint replay saves the actual result and finishes automatic play")
            self.check(branch["opponent_config_id"] == original["opponent_config_id"]
                       and branch["parent_game_id"] == game_id, "Branch retains its parent game and opponent configuration")
            self.check(self.request("GET", f"games/{game_id}") == original, "Branch does not change the original history")
            self.report["games"]["hint_branch"] = branch
            self.report["status"] = "completed"
            return self.report
        except Exception as exc:
            self.report.update(status="failed", error_type=type(exc).__name__, error=str(exc))
            raise
        finally:
            write_json(self.output, self.report)
            self.http.close()


def verify_demo(base_url: str, service_token: str, output: Path, task_timeout: float) -> dict[str, Any]:
    return DemoVerification(base_url, service_token, output, task_timeout).run()
