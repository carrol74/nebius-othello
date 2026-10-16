import hashlib
import json
import time
from pathlib import Path
from typing import Any, Literal

from nemothello.edax import Edax
from nemothello.rules import Board, Color

Difficulty = Literal["easy", "medium", "hard"]
DIFFICULTY_LEVELS: dict[Difficulty, int] = {"easy": 1, "medium": 4, "hard": 8}


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class EdaxOpponent:
    """A fixed engine configuration, distinct from the hint/review engine."""

    def __init__(self, engine: Edax) -> None:
        self.engine = engine
        self.name = f"Edax level {engine.level}"
        self.configuration = {
            "kind": "edax", "version": engine.version, "level": engine.level,
            "executable_sha256": file_digest(engine.executable),
            "eval_sha256": file_digest(engine.eval_file),
            "threads": 1, "book": False, "selectivity": 5,
            "tie_break": "legal-coordinate-order",
        }
        identity = json.dumps(self.configuration, sort_keys=True).encode()
        self.config_id = "edax:" + hashlib.sha256(identity).hexdigest()

    def score(self, board: Board, turn: Color) -> dict[str, Any]:
        started = time.monotonic()
        analysis = self.engine.analyze(board, turn)
        return {
            "coordinate": analysis["recommended_move"],
            "opponent_config_id": self.config_id,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
        }
