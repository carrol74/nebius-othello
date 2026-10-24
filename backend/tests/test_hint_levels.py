import os
import time
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from nemothello.main import app
from nemothello.opponents import DIFFICULTY_LEVELS, HINT_LEVELS
from nemothello.position_lessons import analyze_position
from nemothello.rules import Position
from nemothello.storage import Store


@pytest.fixture
def client(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2]
    executable = Path(os.environ.get("TEST_EDAX_EXECUTABLE", root / "deploy/edax/edax"))
    weights = Path(os.environ.get("TEST_EDAX_EVAL_FILE", root / "deploy/edax/eval.dat"))
    if not executable.is_file() or not weights.is_file():
        pytest.skip("Native Edax and eval.dat are required; set TEST_EDAX_EXECUTABLE/TEST_EDAX_EVAL_FILE")
    for name, value in {
        "EDAX_EXECUTABLE": str(executable.resolve()), "EDAX_EVAL_FILE": str(weights.resolve()),
        "EDAX_VERSION": "4.6", "EDAX_LEVEL": "8", "EDAX_OPPONENT_LEVEL": "2",
        "DATABASE_PATH": str(tmp_path / "games.sqlite3"),
        "BACKEND_SERVICE_TOKEN": "local-hint-test", "TOKEN_FACTORY_API_KEY": "",
        "TOKEN_FACTORY_MODEL_ID": "",
    }.items():
        monkeypatch.setenv(name, value)
    with TestClient(app, headers={
        "Authorization": "Bearer local-hint-test", "X-Session-ID": "hint-test-owner",
    }) as connection:
        assert not app.state.games.difficulty_hints["hard"].process
        yield connection
    assert all(engine.process is None for engine in app.state.games.hint_engines.values())


def post(client, path, **payload):
    response = client.post(path, json={"request_id": str(uuid4()), **payload})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("difficulty", ["easy", "medium", "hard"])
def test_real_hint_routes_by_game_and_branch_keeps_saved_level(client, difficulty):
    game = post(client, "/games", human_color="X", difficulty=difficulty)
    level = HINT_LEVELS[difficulty]
    assert game["hint_level"] == level
    assert game["opponent_name"] == f"Edax level {DIFFICULTY_LEVELS[difficulty]}"
    hint = client.post(f"/games/{game['game_id']}/hint", json={"expected_revision": 0})
    assert hint.status_code == 200, hint.text
    hint = hint.json()
    assert hint["analysis"]["settings"]["level"] == level
    assert {item["coordinate"] for item in hint["analysis"]["candidates"]} == set(game["legal_moves"])
    assert hint["recommended_move"] in game["legal_moves"]
    review_engine = app.state.games.review_engine_of(game)
    assert review_engine.level == max(app.state.games.hint_engines)
    stored = app.state.store.get('game', game['game_id'], 'hint-test-owner')
    review_analysis = analyze_position(stored, 0, review_engine)['analysis']
    assert review_analysis['settings']['level'] == 10
    assert hint['analysis']['settings']['level'] == level
    assert app.state.games.edax.level == 8

    post(client, f"/games/{game['game_id']}/hint-displays", expected_revision=0,
         hint_id=hint["hint_id"])
    post(client, f"/games/{game['game_id']}/moves", expected_revision=0,
         coordinate=hint["recommended_move"])
    # Existing games and branches retain their saved hint level when defaults change.
    app.state.games.difficulty_hints[difficulty] = app.state.games.edax
    branch = post(client, f"/games/{game['game_id']}/branches", revision=0, mode="manual")
    assert branch["hint_level"] == level
    assert branch["opponent_config_id"] == game["opponent_config_id"]
    response = client.post(f"/games/{branch['game_id']}/hint", json={"expected_revision": 0})
    assert response.status_code == 200, response.text
    assert response.json()["analysis"]["settings"]["level"] == level
    assert client.get(f"/games/{game['game_id']}").json()["hint_level"] == level


@pytest.mark.parametrize("difficulty", ["easy", "medium", "hard"])
def test_real_follow_hints_replay_uses_inherited_level_to_terminal(client, difficulty):
    game = post(client, "/games", human_color="O", difficulty=difficulty)
    task = post(client, f"/games/{game['game_id']}/branches", revision=0, mode="follow_hints")
    deadline = time.monotonic() + 30
    while task["status"] in ("queued", "running") and time.monotonic() < deadline:
        time.sleep(1.2)
        response = client.get(f"/tasks/{task['task_id']}")
        assert response.status_code == 200, response.text
        task = response.json()
    assert task["status"] == "succeeded", task
    branch = app.state.store.get("game", task["game_id"], "hint-test-owner")
    assert branch["hint_level"] == HINT_LEVELS[difficulty]
    assert branch["opponent_config_id"] == game["opponent_config_id"]
    assert branch["status"] == "finished"
    assert branch["automatic_hint_moves"]
    assert {move["analysis_settings"]["level"] for move in branch["automatic_hint_moves"]} == {
        HINT_LEVELS[difficulty],
    }
    position = Position(tuple(branch["initial_board"]), branch["initial_turn"])
    for event in branch["history"]:
        if event["kind"] == "move":
            position, _ = position.play(event["coordinate"])
    assert list(position.board) == branch["board"]
    assert position.result() == task["result"]["result"]
    saved = client.get('/games')
    assert saved.status_code == 200
    assert saved.json() == [{
        'game_id': branch['game_id'], 'created_at': branch['created_at'],
        'human_color': branch['human_color'], 'parent_game_id': game['game_id'],
        'status': 'finished',
    }]
    assert Store(app.state.store.path).finished_games('hint-test-owner') == [branch]
    assert client.get('/games', headers={'X-Session-ID': 'different-owner'}).json() == []
    assert client.get(f"/games/{branch['game_id']}", headers={
        'X-Session-ID': 'different-owner',
    }).status_code == 404
    assert client.get('/games', headers={'Authorization': 'Bearer incorrect'}).status_code == 401


def test_saved_game_without_hint_level_keeps_original_analysis_level(client):
    game = post(client, "/games", human_color="X", difficulty="easy")
    with app.state.store.transaction() as db:
        stored = app.state.store.get("game", game["game_id"], "hint-test-owner", db)
        del stored["hint_level"]
        app.state.store.save(db, "game", game["game_id"], "hint-test-owner", stored)
    response = client.post(f"/games/{game['game_id']}/hint", json={"expected_revision": 0})
    assert response.status_code == 200, response.text
    assert response.json()["analysis"]["settings"]["level"] == 8
    branch = post(client, f"/games/{game['game_id']}/branches", revision=0, mode="manual")
    assert branch["hint_level"] == 8
