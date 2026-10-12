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
            raise ValueError("真实服务验证需要服务凭据和正的任务超时")
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
            "limits": "验证真实服务流程；未验证浏览器渲染和实际提示展示，不记录提示展示事实。",
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
            raise ValueError(f"{method} {path} 返回 {response.status_code}，期望 {expected}")
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
                raise ValueError(f"真实任务执行失败：{task['task_id']}")
            if time.monotonic() >= deadline:
                self.report["unfinished_task"] = task
                raise TimeoutError("任务观察超时，任务仍可能在后端运行；不得据此重复创建任务")
            time.sleep(1)
            task = self.request("GET", f"tasks/{task['task_id']}")

    def game(self, payload: dict[str, Any]) -> dict[str, Any]:
        game = GameState.model_validate(payload).model_dump(mode="json")
        initial = Position(tuple(game["initial_board"]), game["initial_turn"])
        position = replay([event["coordinate"] for event in game["history"]
                           if event["kind"] == "move"], initial)
        if (list(position.board) != game["board"] or position.turn != game["turn"]
                or list(position.moves) != game["legal_moves"] or position.result() != game["result"]):
            raise ValueError("服务棋盘、合法点或结果与保存棋谱的回放不同")
        return game

    def run(self) -> dict[str, Any]:
        try:
            create = {"human_color": "X", "request_id": str(uuid4())}
            original = self.game(self.request("POST", "games", create))
            game_id = original["game_id"]
            self.check(self.request("POST", "games", create) == original, "重复创建请求返回同一盘")
            self.request("GET", f"games/{game_id}", expected=404,
                         headers={"X-Session-ID": str(uuid4())})
            self.report["checks"].append("另一会话不能读取对局")
            hint = self.request("POST", f"games/{game_id}/hint", {"expected_revision": 0})
            self.check(
                {c["coordinate"] for c in hint["analysis"]["candidates"]} == set(original["legal_moves"])
                and hint["recommended_move"] in original["legal_moves"],
                "真实 Edax 分析覆盖全部合法候选",
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
                               "重复落子请求返回原结果")
                    stale = {**body, "request_id": str(uuid4())}
                    error = self.request("POST", path, stale, expected=409)
                    self.check(error["code"] == "STALE_REVISION", "旧版本的新请求被拒绝")
                original = next_game
            self.check(original["status"] == "finished", "真实对手完成完整对局")
            self.report["games"]["original"] = original
            review_task = self.request("POST", f"games/{game_id}/reviews", {"request_id": str(uuid4())})
            self.wait_task(review_task)
            review = Review.model_validate(self.request("GET", f"games/{game_id}/review"))
            self.check(bool(review.explanation.strip()) and bool(review.model_id), "真实复盘返回模型身份与讲解")
            self.check(review.hint_adoption.shown_turns == 0, "程序查询分析没有冒充提示已展示")
            self.report["review"] = review.model_dump(mode="json")
            question = self.wait_task(self.request("POST", f"games/{game_id}/review/questions", {
                "request_id": str(uuid4()), "question": "请引用一个具体局面版本，说明这盘的主要改进。",
            }))
            self.check(bool(question["result"]["answer"].strip()), "真实复盘追问返回回答")
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
                       "按提示重演保存真实终局并结束自动推进")
            self.check(branch["opponent_config_id"] == original["opponent_config_id"]
                       and branch["parent_game_id"] == game_id, "分支保留原盘与对手配置")
            self.check(self.request("GET", f"games/{game_id}") == original, "分支没有改写原棋谱")
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
