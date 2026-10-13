import json

import pytest
import pytrio as trio

from nemothello.training import validate_loss
from nemothello.validation_cache import validate_cache, validation_signature


def datum(token=3):
    return trio.Datum(model_input=trio.ModelInput.from_ints([1, 2]),
                      loss_fn_inputs={"target_tokens": [2, token], "weights": [0.0, 1.0]})


class NoCloudCalls:
    model_id = "test-model"

    def forward(self, *args, **kwargs):
        raise AssertionError("Complete or invalid caches must not call the model")


def test_cache_signature_binds_weights_and_encoded_targets():
    original = validation_signature([datum()], 16, "trio://test/a", "test-model")
    assert original != validation_signature([datum()], 16, "trio://test/b", "test-model")
    assert original != validation_signature([datum(4)], 16, "trio://test/a", "test-model")
    assert original != validation_signature([datum()], 8, "trio://test/a", "test-model")


@pytest.mark.parametrize("failure", ["signature", "index", "count", "nan"])
def test_invalid_validation_cache_rejected(failure):
    # Bookkeeping fixtures only; these values do not represent measured model quality.
    record = {"version": 1, "signature": "bound", "batches": [
        {"batch": 0, "positions": 1, "answer_loss_sum": 2.0},
    ]}
    if failure == "signature":
        record["signature"] = "other-checkpoint"
    elif failure == "index":
        record["batches"][0]["batch"] = 1
    elif failure == "count":
        record["batches"][0]["positions"] = 2
    else:
        record["batches"][0]["answer_loss_sum"] = float("nan")
    with pytest.raises(ValueError):
        validate_cache(record, "bound", 1, 16)


def test_complete_cache_avoids_repeating_model_requests(tmp_path):
    datums = [datum()]
    path = tmp_path / "cache.json"
    signature = validation_signature(datums, 16, "trio://test/a", "test-model")
    path.write_text(json.dumps({"version": 1, "signature": signature,
                               "batches": [{"batch": 0, "positions": 1, "answer_loss_sum": 2.0}]}))
    assert validate_loss(NoCloudCalls(), datums, 16, path, "trio://test/a") == 2.0
    with pytest.raises(ValueError, match="不能复用"):
        validate_loss(NoCloudCalls(), datums, 16, path, "trio://test/b")
