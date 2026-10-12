import os
import re
import selectors
import subprocess
import time
from collections import OrderedDict
from pathlib import Path
from threading import Lock
from typing import Any

from nemothello.errors import AppError
from nemothello.rules import Board, Color, legal_moves

RESULT_LINE = re.compile(r"^\s*(\d+)(?:@(\d+)%)?\s+([<>?]?)([+-]\d+)\s+(.*)$")
PV_MOVE = re.compile(r"\b(?:[a-h][1-8]|pa)\b", re.IGNORECASE)


def parse_results(output: str, board: Board, turn: Color) -> list[dict[str, Any]]:
    expected = legal_moves(board, turn)
    empties = sum(row.count(".") for row in board)
    found = {}
    for line in output.splitlines():
        match = RESULT_LINE.match(line)
        if not match or match.group(3):
            continue
        pv = [move.lower() for move in PV_MOVE.findall(match.group(5))]
        if not pv or pv[0] not in expected:
            continue
        depth = int(match.group(1))
        candidate = {
            "coordinate": pv[0], "score": int(match.group(4)),
            "principal_variation": ["pass" if move == "pa" else move for move in pv],
            "depth": depth,
            "score_kind": "exact" if depth >= empties and match.group(2) is None else "estimate",
        }
        if pv[0] not in found or depth >= found[pv[0]]["depth"]:
            found[pv[0]] = candidate
    if set(found) != set(expected):
        raise AppError("EDAX_INCOMPLETE", "Edax 没有返回所有合法候选的有效评分", 502)
    return [found[move] for move in expected]


class Edax:
    def __init__(
        self, executable: Path, eval_file: Path, version: str, level: int = 8,
        timeout: float = 60,
    ) -> None:
        self.executable = executable.resolve()
        self.eval_file = eval_file.resolve()
        self.version = version
        if not 1 <= level <= 10:
            raise ValueError("当前适配只支持非选择性搜索的 Edax level 1–10")
        self.level = level
        self.timeout = timeout
        self.lock = Lock()
        self.cache: OrderedDict[tuple[Any, ...], dict[str, Any]] = OrderedDict()
        self.process: subprocess.Popen | None = None

    def close(self) -> None:
        if self.process is not None:
            if self.process.poll() is None:
                self.process.kill()
            self.process.wait()
            self.process.stdin.close()
            self.process.stdout.close()
            self.process = None

    def _read_prompt(self) -> str:
        deadline = time.monotonic() + self.timeout
        chunks = bytearray()
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise AppError("EDAX_TIMEOUT", "Edax 分析超时，请重试", 503, True)
                data = os.read(self.process.stdout.fileno(), 65536)
                if not data:
                    raise AppError("EDAX_EXITED", "Edax 进程意外结束", 502)
                chunks.extend(data)
                if chunks == b">" or chunks.endswith(b"\n>"):
                    return bytes(chunks[:-1]).decode("utf-8", errors="replace")

    def _exchange(self, command: str) -> str:
        self.process.stdin.write((command + "\n").encode())
        self.process.stdin.flush()
        return self._read_prompt()

    def _start(self) -> None:
        if self.process is None:
            self.process = subprocess.Popen(
                [str(self.executable), "-eval-file", str(self.eval_file),
                 "-level", str(self.level),
                 "-n-tasks", "1", "-book-usage", "off", "-ponder", "off",
                 "-auto-store", "off", "-mode", "3", "-verbose", "0", "-width", "250"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                bufsize=0,
            )
            self._read_prompt()
            version_text = self._exchange("version")
            if not re.search(r"\bEdax\b[^\n]*\b" + re.escape(self.version) + r"\b", version_text):
                raise AppError("EDAX_VERSION", "Edax 版本输出与配置不一致", 502)

    def analyze(self, board: Board, turn: Color) -> dict[str, Any]:
        moves = legal_moves(board, turn)
        if not moves:
            raise AppError("NO_LEGAL_MOVES", "该局面无需落子分析", 422)
        key = (board, turn, self.version, str(self.eval_file), self.level)
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                return self.cache[key]
            started = time.monotonic()
            try:
                self._start()
                self._exchange(f"setboard {''.join(board)} {turn}")
                output = self._exchange(f"hint {len(moves)}")
            except AppError:
                self.close()
                raise
            except OSError as exc:
                self.close()
                raise AppError("EDAX_FAILED", "Edax 程序执行失败，请检查服务日志", 502) from exc
            candidates = parse_results(output, board, turn)
            empties = sum(row.count(".") for row in board)
            required_depth = empties if empties <= 2 * self.level else self.level
            if any(item["depth"] < required_depth for item in candidates):
                raise AppError("EDAX_DEPTH", "Edax 搜索未达到配置深度", 502)
            best = max(candidates, key=lambda item: item["score"])
            analysis = {
                "board": list(board), "turn": turn, "candidates": candidates,
                "recommended_move": best["coordinate"], "score_perspective": turn,
                "score_kind": best["score_kind"], "engine_version": self.version,
                "eval_file": str(self.eval_file),
                "depth": min(c["depth"] for c in candidates),
                "settings": {"level": self.level, "minimum_depth": required_depth,
                             "threads": 1, "book": False,
                             "selectivity": 5},
                "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
                "raw_output": output,
            }
            self.cache[key] = analysis
            if len(self.cache) > 512:
                self.cache.popitem(last=False)
            return analysis
