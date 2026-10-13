import hashlib
import json
import math
from typing import Any


def validation_signature(
    datums: list[Any], batch_size: int, state_path: str, base_model: str,
) -> str:
    if not state_path.startswith("trio://") or not datums or batch_size < 1:
        raise ValueError("验证缓存需要非空数据、有效批大小与不可变检查点")
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
        raise ValueError("验证缓存与检查点、编码或数据不同，不能复用")
    for index, batch in enumerate(batches):
        count = min(batch_size, positions - index * batch_size)
        loss = batch.get("answer_loss_sum")
        if (batch.get("batch") != index or batch.get("positions") != count
                or type(loss) not in (int, float) or not math.isfinite(loss) or loss < 0):
            raise ValueError("验证缓存的批次、数量或损失无效")
    return batches
