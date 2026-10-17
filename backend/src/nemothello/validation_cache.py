import hashlib
import json
import math
from typing import Any


def validation_signature(
    datums: list[Any], batch_size: int, state_path: str, base_model: str,
) -> str:
    if not state_path.startswith("trio://") or not datums or batch_size < 1:
        raise ValueError("Validation cache requires nonempty data, a valid batch size, and an immutable checkpoint")
    payload = {"state_path": state_path, "base_model": base_model,
               "batch_size": batch_size, "loss_fn": "cross_entropy", "auto_shift": False,
               "data": [datum.model_dump(mode="json") for datum in datums]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()


def validate_cache(
    record: dict[str, Any], signature: str, positions: int, batch_size: int,
) -> list[dict[str, Any]]:
    batches = record.get("batches")
    if (record.get("version") != 1 or record.get("signature") != signature
            or not isinstance(batches, list)
            or len(batches) > (positions + batch_size - 1) // batch_size):
        raise ValueError("Validation cache differs in checkpoint, encoding, or data and cannot be reused")
    for index, batch in enumerate(batches):
        count = min(batch_size, positions - index * batch_size)
        loss = batch.get("answer_loss_sum")
        if (batch.get("batch") != index or batch.get("positions") != count
                or type(loss) not in (int, float) or not math.isfinite(loss) or loss < 0):
            raise ValueError("Validation cache has invalid batches, counts, or losses")
    return batches
