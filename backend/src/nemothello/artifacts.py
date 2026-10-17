import json
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytrio as trio

from nemothello.data import write_json


def matches_peft_base(declared: str | None, expected: str) -> bool:
    # PyTRIO's observed export root; do not accept arbitrary matching basenames.
    return declared in (expected, f"/data/models/{expected}")


def find_checkpoint(rest: Any, model_path: str):
    offset = 0
    while True:
        page = rest.list_user_checkpoints(limit=100, offset=offset).result()
        for checkpoint in page.checkpoints:
            if checkpoint.path == model_path:
                if checkpoint.checkpoint_type != "sampler":
                    raise ValueError("Deployment backup requires a sampler adapter, not a full optimizer checkpoint")
                return checkpoint
        if not page.checkpoints or page.cursor is None:
            break
        offset = page.cursor.offset + page.cursor.limit
        if offset >= page.cursor.total_count:
            break
    raise ValueError("Sampler checkpoint specified by metadata was not found in the account")


def backup_adapter(
    api_key: str, metadata_path: Path, destination: Path, temporary_root: Path,
) -> dict[str, Any]:
    metadata = json.loads(metadata_path.read_text())
    if (metadata.get("artifact_kind") != "trained-policy"
            or not metadata.get("model_path") or not metadata.get("sampler_path")):
        raise ValueError("Backup requires adapter-metadata.json from actual training output")
    if destination.exists():
        raise ValueError("Backup directory already exists. Choose a new output directory")
    temporary_root.mkdir(parents=True, exist_ok=True)
    service = trio.ServiceClient(api_key=api_key)
    rest = service.create_rest_client()
    checkpoint = find_checkpoint(rest, metadata["sampler_path"])
    source = urlsplit(checkpoint.path)
    if source.scheme != "trio" or not source.netloc:
        raise ValueError("Sampler checkpoint has no verifiable training task source")
    training_run = rest.get_training_run(source.netloc).result()
    if training_run.base_model != metadata["base_model"] or not training_run.is_lora:
        raise ValueError("Checkpoint base model or LoRA type differs from training metadata")
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
            raise ValueError("Download is not a recognized ZIP or TAR weights archive")
        configs = list(extracted.rglob("adapter_config.json"))
        if len(configs) != 1:
            raise ValueError("Downloaded archive must contain exactly one PEFT adapter_config.json")
        adapter_root = configs[0].parent
        if not (adapter_root / "adapter_model.safetensors").is_file():
            raise ValueError("Downloaded archive lacks adapter_model.safetensors")
        config = json.loads(configs[0].read_text())
        original_base = config.get("base_model_name_or_path")
        if not matches_peft_base(original_base, metadata["base_model"]):
            raise ValueError("PEFT base model differs from training metadata")
        if config.get("peft_type") != "LORA" or config.get("r") != training_run.lora_rank:
            raise ValueError("PEFT type or rank differs from the platform training task")
        shutil.copytree(adapter_root, destination / "adapter")
        if original_base != metadata["base_model"]:
            shutil.copy2(configs[0], destination / "adapter" / "adapter_config.original.json")
            config["base_model_name_or_path"] = metadata["base_model"]
            write_json(destination / "adapter" / "adapter_config.json", config)
        shutil.copy2(archive, destination / "checkpoint.archive")
        shutil.copy2(metadata_path, destination / "adapter-metadata.json")
        report = {
            "status": "downloaded-and-structure-checked",
            "base_model": metadata["base_model"], "model_path": metadata["model_path"],
            "sampler_path": metadata["sampler_path"],
            "checkpoint_id": checkpoint.checkpoint_id,
            "archive_bytes": result.file_size_bytes,
            "training_run_base_model": training_run.base_model,
            "lora_rank": training_run.lora_rank,
            "original_peft_base_model_reference": original_base,
            "portable_peft_base_model_reference": metadata["base_model"],
            "adapter_directory": str((destination / "adapter").resolve()),
            "files": sorted(str(path.relative_to(destination)) for path in destination.rglob("*")
                            if path.is_file()),
            "limits": "Archive and PEFT file structure checked; local loading and hosted restored scoring require separate verification.",
        }
        write_json(destination / "backup-metadata.json", report)
    return report
