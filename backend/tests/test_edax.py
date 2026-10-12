import json
from pathlib import Path

import pytest

from nemothello.edax import parse_results
from nemothello.rules import INITIAL_BOARD


@pytest.mark.parametrize("filename", [
    "edax-4.6-macos-initial-hint.txt",
    "edax-4.6-macos-quiet-initial-hint.txt",
])
def test_parse_real_edax_initial_hint(filename):
    output = (Path(__file__).parent / "fixtures" / filename).read_text(
        encoding="utf-8"
    )
    candidates = parse_results(output, INITIAL_BOARD, "X")

    assert [
        (item["coordinate"], item["score"], item["depth"], item["score_kind"])
        for item in candidates
    ] == [
        ("d3", -3, 8, "estimate"),
        ("c4", -3, 8, "estimate"),
        ("f5", -3, 8, "estimate"),
        ("e6", -3, 8, "estimate"),
    ]
    assert [item["principal_variation"] for item in candidates] == [
        ["d3", "e3", "f3", "e2", "f4", "g3"],
        ["c4", "c5", "c6", "b5", "d6", "c7"],
        ["f5", "f4", "f3", "g4", "e3", "f2"],
        ["e6", "d6", "c6", "d7", "c5", "b6"],
    ]


@pytest.mark.parametrize("case_name", [
    "initial_black", "after_d3_white", "forced_pass_endgame", "after_forced_pass",
])
def test_parse_real_edax_adapter_output(case_name):
    path = Path(__file__).parent / "fixtures" / "edax-4.6-macos-adapter-check.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    analysis = next(case["analysis"] for case in report["cases"] if case["name"] == case_name)

    assert parse_results(
        analysis["raw_output"], tuple(analysis["board"]), analysis["turn"]
    ) == analysis["candidates"]
