import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from pytrio.errors.base import PyTrioError


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def validate_progress(progress: dict[str, Any], batches: int, epochs: int) -> None:
    epoch, batch = progress.get("next_epoch"), progress.get("next_batch")
    history, updates = progress.get("history", []), progress.get("updates", [])
    if (progress.get("version") != 1 or type(epoch) is not int or type(batch) is not int
            or not 0 <= epoch <= epochs or not 0 <= batch <= batches
            or (epoch == epochs and batch != 0)
            or len(history) != epoch or len(updates) != batch
            or [item.get("epoch") for item in history] != list(range(1, epoch + 1))
            or [item.get("batch") for item in updates] != list(range(batch))
            or not str(progress.get("state_path", "")).startswith("trio://")):
        raise ValueError("训练检查点的轮次、批次或更新记录不一致，不能续训")
    for item in history:
        loss = item.get("validation_answer_loss")
        if (type(loss) not in (int, float) or not math.isfinite(loss) or loss < 0
                or not str(item.get("state_path", "")).startswith("trio://")
                or not str(item.get("sampler_path", "")).startswith("trio://")):
            raise ValueError("完整轮次的验证结果或检查点无效")


def recoverable_error(error: Exception) -> bool:
    if not isinstance(error, PyTrioError):
        return False
    # Roll back into a new run, never resubmit the uncertain operation on this client.
    return ((error.status_code == 409 and error.code == "conflict")
            or error.status_code in (408, 429, 500, 502, 503, 504)
            or (error.status_code == 0 and error.retryable))


def supervise_training(args: Any) -> None:
    command = [sys.executable, "-m", "nemothello.cli", "train",
               "--dataset", str(args.dataset), "--calibration", str(args.calibration),
               "--output", str(args.output), "--name", args.name,
               "--rank", str(args.rank), "--learning-rate", str(args.learning_rate),
               "--batch-size", str(args.batch_size), "--epochs", str(args.epochs),
               "--seed", str(args.seed), "--checkpoint-every", str(args.checkpoint_every),
               "--max-restarts", "0"]
    if args.resume:
        command.append("--resume")
    status_path = args.output / "training-status.json"
    for attempt in range(args.max_restarts + 1):
        previous = status_path.stat().st_mtime_ns if status_path.exists() else None
        result = subprocess.run(command, check=False)
        if result.returncode == 0:
            return
        if (attempt == args.max_restarts or not status_path.exists()
                or status_path.stat().st_mtime_ns == previous):
            raise SystemExit(result.returncode)
        status = json.loads(status_path.read_text())
        if (status.get("status") != "interrupted" or status.get("recoverable") is not True
                or not (args.output / "training-progress.json").exists()):
            raise SystemExit(result.returncode)
        if "--resume" not in command:
            command.append("--resume")
        print(f"训练客户端已停止；从确认的检查点启动新进程恢复 {attempt + 1}/{args.max_restarts}",
              flush=True)
