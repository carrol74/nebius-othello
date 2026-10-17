import math
import time
from dataclasses import dataclass
from threading import Lock
from typing import Any

import numpy as np
import pytrio as trio

from nemothello.errors import AppError
from nemothello.policy_spec import (
    FEATURE_TEMPLATE_VERSION,
    GENERATION_MODE,
    GENERATION_SETTINGS,
    POLICY_MODES,
    SCORING_MODE,
    SYMBOLS,
    TEMPLATE_VERSION,
    TEMPLATE_VERSIONS,
)
from nemothello.rules import Board, Color, legal_moves

__all__ = [
    "FEATURE_TEMPLATE_VERSION",
    "GENERATION_MODE",
    "GENERATION_SETTINGS",
    "POLICY_MODES",
    "SCORING_MODE",
    "SYMBOLS",
    "TEMPLATE_VERSION",
    "TEMPLATE_VERSIONS",
    "EncodedPosition",
    "GenerationPolicy",
    "PytrioPolicy",
    "SamplingPolicy",
    "complete_scores",
    "create_policy",
    "encode_position",
    "generated_coordinate",
    "position_encoder",
    "scoring_datums",
    "training_datum",
]


@dataclass(frozen=True)
class EncodedPosition:
    prefix: list[int]
    coordinates: tuple[str, ...]
    symbols: tuple[str, ...]
    symbol_tokens: tuple[int, ...]
    rendered: str


def encode_position(
    tokenizer: Any, board: Board, turn: Color, order: tuple[str, ...] | None = None
) -> EncodedPosition:
    moves = legal_moves(board, turn)
    coordinates = moves if order is None else order
    if not moves or len(coordinates) != len(moves) or set(coordinates) != set(moves):
        raise ValueError("Encoding must contain all legal moves without duplicates")
    if len(moves) > len(SYMBOLS):
        raise ValueError("Candidate count exceeds the symbol table capacity")
    symbols = tuple(SYMBOLS[:len(moves)])
    message = "Board:\n" + "\n".join(board) + f"\nTurn: {turn}\nCandidates: "
    message += " ".join(f"{symbol}={move}" for symbol, move in zip(symbols, coordinates, strict=True))
    rendered = tokenizer.apply_chat_template(
        [{"role": "system", "content": "Choose the best Othello move. Return one candidate symbol."},
         {"role": "user", "content": message}],
        tokenize=False, add_generation_prompt=True, enable_thinking=False,
    )
    prefix = tokenizer.encode(rendered, add_special_tokens=False)
    token_ids = []
    for symbol in symbols:
        tokens = tokenizer.encode(symbol, add_special_tokens=False)
        if len(tokens) != 1 or tokenizer.encode(rendered + symbol, add_special_tokens=False) != prefix + tokens:
            raise ValueError(f"Candidate {symbol} is not a standalone token at the answer position")
        token_ids.append(tokens[0])
    if len(set(token_ids)) != len(token_ids):
        raise ValueError("Different candidate symbols map to the same token")
    return EncodedPosition(prefix, coordinates, symbols, tuple(token_ids), rendered)


def scoring_datums(encoded: EncodedPosition) -> list[trio.Datum]:
    return [training_datum(encoded, coordinate) for coordinate in encoded.coordinates]


def position_encoder(template_version: str):
    if template_version == TEMPLATE_VERSION:
        return encode_position
    if template_version == FEATURE_TEMPLATE_VERSION:
        from nemothello.rule_features import encode_feature_position

        return encode_feature_position
    raise ValueError("Unknown move input template")


def training_datum(encoded: EncodedPosition, target: str) -> trio.Datum:
    token = encoded.symbol_tokens[encoded.coordinates.index(target)]
    targets = encoded.prefix[1:] + [token]
    weights = [0.0] * (len(targets) - 1) + [1.0]
    return trio.Datum(
        model_input=trio.ModelInput.from_ints(encoded.prefix),
        loss_fn_inputs={"target_tokens": targets, "weights": weights},
    )


def complete_scores(output: Any, encoded: EncodedPosition) -> dict[str, float]:
    if len(output.loss_fn_outputs) != len(encoded.coordinates):
        raise AppError("SCORE_SHAPE", "Returned score count differs from the legal candidate count", 502)
    scores = {}
    for coordinate, loss_output in zip(encoded.coordinates, output.loss_fn_outputs, strict=True):
        values = np.asarray(loss_output["logprobs"].to_numpy())
        expected = (len(encoded.prefix),)
        if values.shape != expected:
            raise AppError("SCORE_SHAPE", f"Incomplete candidate score shape; expected {expected}", 502)
        score = float(values[-1])
        if not math.isfinite(score) or score > 1e-5:
            raise AppError("SCORE_INVALID", "Candidate score is not a valid finite logprob", 502)
        scores[coordinate] = score
    return scores


class PytrioPolicy:
    def __init__(self, api_key: str, base_model: str, model_path: str) -> None:
        self.api_key = api_key
        self.base_model = base_model
        self.model_path = model_path
        self.lock = Lock()
        self.service: Any = None
        self.training: Any = None
        self.tokenizer: Any = None
        self.config_id = f"{base_model}|{model_path}|{TEMPLATE_VERSION}|{SCORING_MODE}|argmax-row-major"

    def connect(self) -> None:
        if self.training is None:
            trio.configure(request_timeout_seconds=90, actor_event_polling_timeout_seconds=90,
                           actor_event_submit_timeout_seconds=90)
            if self.service is None:
                self.service = trio.ServiceClient(api_key=self.api_key)
            training = self.service.create_training_client_from_state(self.model_path)
            if training.model_id != self.base_model:
                raise AppError("MODEL_MISMATCH", "Restored base model does not match the game configuration", 502)
            tokenizer = training.get_tokenizer()
            self.training, self.tokenizer = training, tokenizer

    def score(self, board: Board, turn: Color) -> dict[str, Any]:
        started = time.monotonic()
        with self.lock:
            self.connect()
            encoded = encode_position(self.tokenizer, board, turn)
            output = self.training.forward(
                scoring_datums(encoded), loss_fn="cross_entropy", auto_shift=False,
            ).result()
            scores = complete_scores(output, encoded)
        return {
            "scores": scores, "coordinate": max(scores, key=scores.get),
            "input_tokens": len(encoded.prefix) * len(scores),
            "logical_input_tokens": len(encoded.prefix), "candidate_sequences": len(scores),
            "candidate_count": len(scores), "scoring_mode": SCORING_MODE,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
            "metrics": output.metrics, "opponent_config_id": self.config_id,
        }


class SamplingPolicy:
    def __init__(self, api_key: str, base_model: str, model_path: str | None = None) -> None:
        self.base_model, self.model_path = base_model, model_path
        self.service = trio.ServiceClient(api_key=api_key)
        self.sampler = self.service.create_sampling_client(base_model=base_model, model_path=model_path)
        self.tokenizer = self.sampler.get_tokenizer()

    def score_encoded(self, encoded: EncodedPosition) -> dict[str, float]:
        scores = {}
        for move, token in zip(encoded.coordinates, encoded.symbol_tokens, strict=True):
            tokens = encoded.prefix + [token]
            values = self.sampler.compute_logprobs(trio.ModelInput.from_ints(tokens)).result()
            if (len(values) != len(tokens) or values[-1] is None
                    or not math.isfinite(values[-1]) or values[-1] > 1e-5):
                raise AppError("REFERENCE_INCOMPLETE", "Per-candidate API did not return the target token score", 502)
            scores[move] = float(values[-1])
        return scores

    def score(self, board: Board, turn: Color) -> dict[str, Any]:
        started = time.monotonic()
        encoded = encode_position(self.tokenizer, board, turn)
        scores = self.score_encoded(encoded)
        return {"scores": scores, "coordinate": max(scores, key=scores.get),
                "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
                "input_tokens": len(scores) * (len(encoded.prefix) + 1),
                "logical_input_tokens": len(encoded.prefix),
                "candidate_requests": len(scores), "candidate_count": len(scores)}


def generated_coordinate(tokens: list[int], encoded: EncodedPosition) -> str:
    if (len(tokens) != 1 or type(tokens[0]) is not int
            or tokens[0] not in encoded.symbol_tokens):
        raise AppError("POLICY_ILLEGAL_OUTPUT", "Model did not return one legal candidate symbol", 502, True)
    return encoded.coordinates[encoded.symbol_tokens.index(tokens[0])]


class GenerationPolicy:
    """Choose one legal candidate from one sampling request; invalid outputs fail closed."""

    def __init__(
        self, api_key: str, base_model: str, model_path: str | None = None,
        *, template_version: str = TEMPLATE_VERSION,
    ) -> None:
        self.api_key, self.base_model, self.model_path = api_key, base_model, model_path
        self.template_version = template_version
        self.encoder = position_encoder(template_version)
        self.lock = Lock()
        self.service: Any = None
        self.sampler: Any = None
        self.tokenizer: Any = None
        self.config_id = f"{base_model}|{model_path}|{template_version}|{GENERATION_MODE}|seed42"

    def connect(self) -> None:
        if self.sampler is None:
            trio.configure(request_timeout_seconds=90, actor_event_polling_timeout_seconds=90,
                           actor_event_submit_timeout_seconds=90)
            if self.service is None:
                self.service = trio.ServiceClient(api_key=self.api_key)
            sampler = self.service.create_sampling_client(
                base_model=self.base_model, model_path=self.model_path,
            )
            if sampler.model_id != self.base_model:
                raise AppError("MODEL_MISMATCH", "Restored base model does not match the game configuration", 502)
            self.sampler, self.tokenizer = sampler, sampler.get_tokenizer()

    def _generate(self, encoded: EncodedPosition) -> dict[str, Any]:
        response = self.sampler.sample(
            trio.ModelInput.from_ints(encoded.prefix), num_samples=1,
            sampling_params=trio.SamplingParams(**GENERATION_SETTINGS), return_text=False,
        ).result()
        if len(response.sequences) != 1:
            raise AppError("POLICY_OUTPUT_SHAPE", "Model returned a different number of sequences than requested", 502, True)
        tokens = response.sequences[0].tokens
        coordinate = generated_coordinate(tokens, encoded)
        return {"coordinate": coordinate, "generated_token": tokens[0],
                "input_tokens": response.input_tokens, "output_tokens": response.output_tokens,
                "logical_input_tokens": len(encoded.prefix), "candidate_requests": 1,
                "candidate_count": len(encoded.coordinates), "scoring_mode": GENERATION_MODE,
                "generation_settings": dict(GENERATION_SETTINGS),
                "opponent_config_id": self.config_id}

    def score_encoded(self, encoded: EncodedPosition) -> dict[str, Any]:
        started = time.monotonic()
        with self.lock:
            self.connect()
            result = self._generate(encoded)
        return {**result, "elapsed_ms": round((time.monotonic() - started) * 1000, 2)}

    def score(self, board: Board, turn: Color) -> dict[str, Any]:
        started = time.monotonic()
        with self.lock:
            self.connect()
            result = self._generate(self.encoder(self.tokenizer, board, turn))
        return {**result, "elapsed_ms": round((time.monotonic() - started) * 1000, 2)}


def create_policy(
    api_key: str, base_model: str, model_path: str | None, mode: str = GENERATION_MODE,
    template_version: str = TEMPLATE_VERSION,
) -> GenerationPolicy | PytrioPolicy | SamplingPolicy:
    if mode == GENERATION_MODE:
        return GenerationPolicy(api_key, base_model, model_path, template_version=template_version)
    if template_version != TEMPLATE_VERSION:
        raise ValueError("Rule feature template supports only single-token generation")
    if mode == SCORING_MODE:
        return (PytrioPolicy(api_key, base_model, model_path) if model_path
                else SamplingPolicy(api_key, base_model))
    raise ValueError("Unknown PyTRIO move mode")
