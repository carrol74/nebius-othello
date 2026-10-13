import pytest

from nemothello.artifacts import matches_peft_base


@pytest.mark.parametrize("reference", ["Qwen/Qwen3.5-4B", "/data/models/Qwen/Qwen3.5-4B"])
def test_supported_export_reference_matches_canonical_base(reference):
    assert matches_peft_base(reference, "Qwen/Qwen3.5-4B")


@pytest.mark.parametrize("reference", [None, "Qwen3.5-4B", "/other/Qwen/Qwen3.5-4B",
                                      "/data/models/other/Qwen3.5-4B",
                                      "/data/models/Qwen/Qwen3.5-9B"])
def test_wrong_or_unverified_base_reference_rejected(reference):
    assert not matches_peft_base(reference, "Qwen/Qwen3.5-4B")
