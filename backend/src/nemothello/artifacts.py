import json
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import pytrio as trio

from nemothello.data import write_json


def find_checkpoint(rest: Any, model_path: str):
    offset = 0
    while True:
        page = rest.list_user_checkpoints(limit=100, offset=offset).result()
        for checkpoint in page.checkpoints:
            if checkpoint.path == model_path:
                if checkpoint.checkpoint_type != "sampler":
                    raise ValueError("部署备份需要 sampler adapter，不能使用完整优化器检查点")
                return checkpoint
        if not page.checkpoints or page.cursor is None:
            break
        offset = page.cursor.offset + page.cursor.limit
        if offset >= page.cursor.total_count:
            break
    raise ValueError("账户中未找到元数据指定的 sampler checkpoint")


def backup_adapter(
    api_key: str, metadata_path: Path, destination: Path, temporary_root: Path,
) -> dict[str, Any]:
    metadata = json.loads(metadata_path.read_text())
    if (metadata.get("artifact_kind") != "trained-policy"
            or not metadata.get("model_path") or not metadata.get("sampler_path")):
        raise ValueError("备份需要真实训练产物的 adapter-metadata.json")
    if destination.exists():
        raise ValueError("备份目录已经存在，请选择新的输出目录")
    temporary_root.mkdir(parents=True, exist_ok=True)
    service = trio.ServiceClient(api_key=api_key)
    rest = service.create_rest_client()
    checkpoint = find_checkpoint(rest, metadata["sampler_path"])
    with tempfile.TemporaryDirectory(prefix="adapter-", dir=temporary_root) as directory:
        work = Path(directory)
        archive = work / "checkpoint.archive"
        result = rest.download_checkpoint(
            checkpoint.checkpoint_id, archive, resume=False,
        ).result()
        extracted = work / "extracted"
        extracted.mkdir()
        if zipfile.is_zipfile(archive):
            with zipfile.ZipFile(archive) as source:
                source.extractall(extracted)
        elif tarfile.is_tarfile(archive):
            with tarfile.open(archive) as source:
                source.extractall(extracted, filter="data")
        else:
            raise ValueError("下载结果不是可识别的 ZIP 或 TAR 权重归档")
        configs = list(extracted.rglob("adapter_config.json"))
        if len(configs) != 1:
            raise ValueError("下载归档必须包含一份 PEFT adapter_config.json")
        adapter_root = configs[0].parent
        if not (adapter_root / "adapter_model.safetensors").is_file():
            raise ValueError("下载归档缺少 adapter_model.safetensors")
        config = json.loads(configs[0].read_text())
        if config.get("base_model_name_or_path") != metadata["base_model"]:
            raise ValueError("PEFT 配置中的基座与训练元数据不同")
        shutil.copytree(adapter_root, destination / "adapter")
        shutil.copy2(archive, destination / "checkpoint.archive")
        shutil.copy2(metadata_path, destination / "adapter-metadata.json")
        report = {
            "status": "downloaded-and-structure-checked",
            "base_model": metadata["base_model"], "model_path": metadata["model_path"],
            "sampler_path": metadata["sampler_path"],
            "checkpoint_id": checkpoint.checkpoint_id,
            "archive_bytes": result.file_size_bytes,
            "adapter_directory": str((destination / "adapter").resolve()),
            "files": sorted(str(path.relative_to(destination)) for path in destination.rglob("*")
                            if path.is_file()),
            "limits": "归档与 PEFT 文件结构已检查；本地加载与托管恢复评分须独立验证。",
        }
        write_json(destination / "backup-metadata.json", report)
    return report
