import json
import math
import random
from collections import Counter
from pathlib import Path
from typing import Any
from uuid import uuid4

from nemothello.edax import Edax
from nemothello.rules import Board, Position, legal_moves, validate_board
from nemothello.schemas import Analysis


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open() as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def validate_sample(sample: dict[str, Any]) -> None:
    moves = legal_moves(tuple(sample["board"]), sample["turn"])
    if sample["candidates"] != list(moves) or sample["target"] not in moves:
        raise ValueError("样本候选或老师目标与合法点不同")
    analysis = Analysis.model_validate(sample["analysis"])
    if (analysis.board != sample["board"] or analysis.turn != sample["turn"]
            or analysis.score_perspective != sample["turn"]
            or [c.coordinate for c in analysis.candidates] != list(moves)):
        raise ValueError("老师完整评分与样本局面不同")
    scores = {c.coordinate: c.score for c in analysis.candidates}
    if (any(not math.isfinite(v) for v in scores.values())
            or analysis.recommended_move != sample["target"]
            or scores[sample["target"]] != max(scores.values())):
        raise ValueError("老师目标与真实最高候选评分不同")


def canonical_board(board: Board) -> str:
    variants = []
    cells = board
    for _ in range(4):
        variants.append("".join(cells))
        variants.append("".join(row[::-1] for row in cells))
        cells = tuple("".join(cells[7 - col][row] for col in range(8)) for row in range(8))
    return min(variants)


def generate_openings(count: int, plies: int, seed: int) -> list[dict[str, Any]]:
    if count < 1 or plies < 4 or plies > 20:
        raise ValueError("开局数量必须为正，开局步数须为 4–20")
    rng = random.Random(seed)
    openings, seen = [], set()
    for _ in range(count * 1000):
        position, moves = Position(), []
        for _ in range(plies):
            if position.turn is None:
                break
            move = rng.choice(position.moves)
            moves.append(move)
            position, _ = position.play(move)
        key = (canonical_board(position.board), position.turn)
        if position.turn and key not in seen:
            seen.add(key)
            openings.append({"opening_id": f"opening-{len(openings) + 1:03}",
                             "moves": moves, "board": list(position.board), "turn": position.turn})
            if len(openings) == count:
                return openings
    raise ValueError("无法生成足够的非对称重复开局，请增加开局步数")


def generate_games(
    edax: Edax, count: int, seed: int, excluded_openings: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if count < 10:
        raise ValueError("至少生成十盘，以便按整盘划分三组")
    excluded = {(canonical_board(tuple(o["board"])), o["turn"]) for o in excluded_openings}
    rng = random.Random(seed)
    games, seen_games = [], set()
    for _ in range(count * 100):
        position, samples, moves = Position(), [], []
        overlap = False
        while position.turn:
            if (canonical_board(position.board), position.turn) in excluded:
                overlap = True
                break
            analysis = edax.analyze(position.board, position.turn)
            target = analysis["recommended_move"]
            samples.append({"board": list(position.board), "turn": position.turn,
                            "candidates": list(position.moves), "target": target,
                            "analysis": analysis})
            move = rng.choice(position.moves) if len(moves) < 8 else target
            moves.append(move)
            position, _ = position.play(move)
        if overlap:
            continue
        game_key = tuple(moves)
        if game_key in seen_games:
            continue
        seen_games.add(game_key)
        games.append({"game_id": str(uuid4()), "moves": moves, "positions": samples,
                      "result": position.result(), "seed": seed,
                      "strategy": "random-first-8-then-edax"})
        if len(games) == count:
            return games
    raise ValueError("排除评测开局后未能生成足够对局")


def prepare_dataset(games: list[dict[str, Any]], output: Path, seed: int) -> dict[str, Any]:
    if len(games) < 10 or len({game["game_id"] for game in games}) != len(games):
        raise ValueError("需要至少十盘且 game_id 不能重复")
    if len({tuple(game["moves"]) for game in games}) != len(games):
        raise ValueError("完整棋谱重复，不能通过不同 game_id 跨集合使用同一盘")
    shuffled = list(games)
    random.Random(seed).shuffle(shuffled)
    train_end, validation_end = int(len(games) * 0.8), int(len(games) * 0.9)
    groups = {"train": shuffled[:train_end], "validation": shuffled[train_end:validation_end],
              "test": shuffled[validation_end:]}
    summary, keys = {}, {}
    for name, group in groups.items():
        records = []
        for game in group:
            position = Position()
            if len(game["positions"]) != len(game["moves"]):
                raise ValueError("局面样本数量与原始棋谱不一致")
            for ply, (sample, actual) in enumerate(zip(game["positions"], game["moves"], strict=True)):
                validate_sample(sample)
                validate_board(tuple(sample["board"]))
                if tuple(sample["board"]) != position.board or sample["turn"] != position.turn:
                    raise ValueError("原始局面与棋谱回放不一致")
                if sample["candidates"] != list(position.moves) or sample["target"] not in position.moves:
                    raise ValueError("候选或老师目标与合法点不一致")
                if len(position.moves) > 1:
                    records.append({"game_id": game["game_id"], "ply": ply,
                                    "board": sample["board"], "turn": sample["turn"],
                                    "target": sample["target"], "candidates": sample["candidates"],
                                    "analysis": sample["analysis"]})
                position, _ = position.play(actual)
            if position.result() != game["result"]:
                raise ValueError("原始棋谱终局结果不一致")
        write_jsonl(output / f"{name}.jsonl", records)
        keys[name] = Counter((tuple(item["board"]), item["turn"]) for item in records)
        summary[name] = {"games": len(group), "positions": len(records),
                         "game_ids": [g["game_id"] for g in group],
                         "duplicate_positions": len(records) - len(keys[name]),
                         "candidate_counts": dict(Counter(len(r["candidates"]) for r in records))}
    summary["cross_split_shared_positions"] = {
        f"{a}_{b}": len(keys[a].keys() & keys[b].keys())
        for a, b in (("train", "validation"), ("train", "test"), ("validation", "test"))
    }
    summary["seed"] = seed
    summary["status"] = "actual-dataset-statistics"
    write_json(output / "split-metadata.json", summary)
    return summary
