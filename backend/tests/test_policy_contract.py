from pytrio.client.training_batch import plan_training_batch
from pytrio.model.limits import TrainingLimits

from nemothello.policy import EncodedPosition, scoring_datums, training_datum


def test_candidate_batch_passes_actual_sdk_planner():
    encoded = EncodedPosition(
        prefix=list(range(85)), coordinates=("d3", "c4", "f5", "e6"),
        symbols=("A", "B", "C", "D"), symbol_tokens=(90, 91, 92, 93), rendered="",
    )
    plan = plan_training_batch(
        scoring_datums(encoded), loss_fn="cross_entropy", auto_shift=False,
        limits=TrainingLimits(max_batch_size=2, max_tokens_per_request=200, max_seq_len=128),
        tokenizer_vocab_size=100,
    )

    assert plan.totals.total_samples == 4
    assert plan.totals.total_active_tokens == 4
    assert [chunk.input_tokens for chunk in plan.chunks] == [170, 170]
    samples = [sample for chunk in plan.chunks for sample in chunk.samples]
    assert [sample.target_tokens[-1] for sample in samples] == [90, 91, 92, 93]
    assert all(sample.target_tokens[:-1] == tuple(range(1, 85)) for sample in samples)
    assert all(sample.weights == (0.0,) * 84 + (1.0,) for sample in samples)


def test_training_answer_passes_actual_sdk_planner():
    encoded = EncodedPosition(
        prefix=list(range(85)), coordinates=("d3", "c4"), symbols=("A", "B"),
        symbol_tokens=(90, 91), rendered="",
    )
    plan = plan_training_batch(
        [training_datum(encoded, "c4")], loss_fn="cross_entropy", auto_shift=False,
        limits=TrainingLimits(max_batch_size=None, max_tokens_per_request=None, max_seq_len=128),
        tokenizer_vocab_size=100,
    )
    assert plan.totals.total_active_tokens == 1
    assert plan.chunks[0].samples[0].target_tokens[-1] == 91
