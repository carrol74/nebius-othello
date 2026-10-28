import json
from pathlib import Path

import pytest

from nemothello.edax import Edax
from nemothello.errors import AppError
from nemothello.games import Games, advance
from nemothello.opponents import EdaxOpponent
from nemothello.rules import Position, opponent
from nemothello.schemas import BranchRequest
from nemothello.storage import Store

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def games(tmp_path):
    root = Path(__file__).resolve().parents[2]
    executable, weights = root / "deploy/edax/edax", root / "deploy/edax/eval.dat"
    if not executable.is_file() or not weights.is_file():
        pytest.skip("Native Edax and eval.dat are required")
    engine = Edax(executable, weights, "4.6", 4)
    service = Games(Store(tmp_path / "branches.sqlite3"), EdaxOpponent(engine), engine, 3)
    try:
        yield service
    finally:
        engine.close()


def save(games, game):
    with games.store.transaction() as db:
        games.store.save(db, "game", game["game_id"], "owner", game)


def test_every_native_displayed_frame_becomes_the_branch_start(games):
    cases = json.loads((FIXTURES / "teaching-native-cases.json").read_text())
    checked = 0
    for name, comparison in cases.items():
        initial = comparison["choices"][0]["frames"][0]
        parent = games.new_game(comparison["actor"], Position(tuple(initial["board"]), initial["turn"]))
        save(games, parent)
        before = games.get(parent["game_id"], "owner")
        for choice in comparison["choices"]:
            for index, frame in enumerate(choice["frames"]):
                if frame["turn"] is None:
                    continue
                line = [step["coordinate"] for step in choice["frames"][1:index + 1]]
                request = BranchRequest(request_id=f"branch-{name}-{choice['coordinate']}-{index}", revision=0, line=line)
                branch = games.branch("owner", parent["game_id"], request.request_id, request.revision, request.line)
                assert branch["initial_board"] == frame["board"] == branch["board"]
                position = Position(tuple(frame["board"]), frame["turn"])
                expected_turn = position.turn if position.moves else opponent(position.turn)
                assert branch["initial_turn"] == branch["turn"] == expected_turn
                assert branch["human_color"] == parent["human_color"]
                assert branch["opponent_config_id"] == parent["opponent_config_id"]
                assert branch["revision"] == 0 and not branch["history"]
                assert games.branch("owner", parent["game_id"], request.request_id, 0, line) == branch
                checked += 1
        assert games.get(parent["game_id"], "owner") == before
    assert checked > 50


def test_historical_and_alternative_continuations_use_the_saved_revision(games):
    source = json.loads((FIXTURES / "review-native-positions.json").read_text())["review"]
    parent = games.new_game("X")
    for event in source["history"]:
        if event["kind"] == "move":
            parent = advance(parent, event["coordinate"])
    save(games, parent)
    cases = json.loads((FIXTURES / "teaching-native-cases.json").read_text())
    for choice in cases["16"]["choices"]:
        line = [frame["coordinate"] for frame in choice["frames"][1:3]]
        branch = games.branch("owner", parent["game_id"], f"line-{choice['coordinate']}", 16, line)
        assert branch["board"] == choice["frames"][2]["board"]
        assert branch["turn"] == choice["frames"][2]["turn"]
    passed = next(event for event in parent["history"] if event["kind"] == "pass")
    before_pass = games.branch("owner", parent["game_id"], "before-pass", passed["revision"] - 1)
    after_pass = games.branch("owner", parent["game_id"], "after-pass", passed["revision"])
    assert before_pass["board"] == after_pass["board"] == passed["board"]
    assert before_pass["turn"] == after_pass["turn"] == passed["turn"]
    assert games.get(parent["game_id"], "owner")["history"] == parent["history"]


def test_invalid_or_finished_continuations_create_no_branch(games):
    parent = games.new_game("X")
    save(games, parent)
    for line in (["a1"], ["pass"], ["d3", "d3"]):
        with pytest.raises(AppError) as error:
            games.branch("owner", parent["game_id"], f"bad-{line}", 0, line)
        assert error.value.code == "BRANCH_LINE"
    assert len(games.store.list_records("game", "owner")) == 1
    position = Position((".OXXXXXX", "XXXXXXXX", "XXXXXXXX", "XXXXXXXX",
                         "XXXXXXXX", "XXXXXXXX", "XXXXXXXX", "XX.OXXXX"), "X")
    ending = games.new_game("X", position)
    save(games, ending)
    with pytest.raises(AppError) as error:
        games.branch("owner", ending["game_id"], "finished-line", 0, ["a1", "pass", "c8"])
    assert error.value.code == "BRANCH_POSITION"
    assert len(games.store.list_records("game", "owner")) == 2
