import subprocess
import sys

import pytest

from nemothello.config import Settings
from nemothello.edax import Edax
from nemothello.errors import AppError
from nemothello.games import Games
from nemothello.nemotron import Nemotron
from nemothello.opponents import EdaxOpponent
from nemothello.rules import INITIAL_BOARD
from nemothello.storage import Store


def resources(tmp_path):
    executable, weights = tmp_path / "edax", tmp_path / "eval.dat"
    executable.write_bytes(b"test-executable-identity")
    weights.write_bytes(b"test-evaluation-identity")
    return executable, weights


def test_product_imports_and_cli_do_not_require_research_packages():
    script = '''
import importlib.abc
import sys
class NoResearch(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in {'pytrio', 'torch', 'numpy', 'transformers', 'modelscope'}:
            raise AssertionError('Product imported research dependency: ' + fullname)
sys.meta_path.insert(0, NoResearch())
from nemothello.main import app
from nemothello.cli import main
assert app.openapi()['info']['title'] == 'Nemothello'
sys.argv = ['nemothello', '--help']
main()
'''
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_product_settings_need_no_pytrio_or_review_credentials(tmp_path):
    executable, weights = resources(tmp_path)
    settings = Settings(
        _env_file=None, edax_executable=executable, edax_eval_file=weights,
        edax_version="4.6", backend_service_token="test-only",
    )
    settings.validate_resources()
    assert settings.edax_opponent_level == 2
    assert settings.edax_level == 8
    settings.token_factory_model_id = "test-model"
    with pytest.raises(ValueError, match="同时配置"):
        settings.validate_resources()


def test_unconfigured_review_fails_before_http(monkeypatch):
    client = Nemotron("", "https://unused.invalid/v1", "")

    def unexpected(*args, **kwargs):
        pytest.fail("Unconfigured review attempted HTTP")

    monkeypatch.setattr(client.http, "post", unexpected)
    try:
        with pytest.raises(AppError) as error:
            client.explain({})
        assert error.value.code == "REVIEW_NOT_CONFIGURED"
    finally:
        client.close()


def test_opponent_identity_binds_strength_and_resource_content(tmp_path):
    executable, weights = resources(tmp_path)
    first = EdaxOpponent(Edax(executable, weights, "4.6", 2))
    same = EdaxOpponent(Edax(executable, weights, "4.6", 2))
    stronger = EdaxOpponent(Edax(executable, weights, "4.6", 8))
    assert first.config_id == same.config_id
    assert first.config_id != stronger.config_id
    weights.write_bytes(b"different-test-evaluation-identity")
    changed = EdaxOpponent(Edax(executable, weights, "4.6", 2))
    assert first.config_id != changed.config_id


def test_game_uses_engine_and_does_not_replace_historical_opponent(tmp_path, monkeypatch):
    executable, weights = resources(tmp_path)
    engine = Edax(executable, weights, "4.6", 2)
    opponent = EdaxOpponent(engine)
    games = Games(Store(tmp_path / "games.sqlite3"), opponent, engine, 3)
    game = games.create("owner", "create", "O")
    assert game["opponent_name"] == "Edax level 2"
    calls = []

    def analyze(board, turn):
        calls.append((board, turn))
        return {"recommended_move": "d3"}

    monkeypatch.setattr(engine, "analyze", analyze)
    updated = games.move("owner", game["game_id"], "ai-move", 0)
    assert updated["history"][0]["coordinate"] == "d3"
    assert calls == [(INITIAL_BOARD, "X")]
    assert games.move("owner", game["game_id"], "ai-move", 0) == updated
    assert len(calls) == 1
    with games.store.transaction() as db:
        stored = games.store.get("game", game["game_id"], "owner", db)
        stored["opponent_config_id"] = "historical-trained-opponent"
        games.store.save(db, "game", game["game_id"], "owner", stored)
    with pytest.raises(AppError) as error:
        games.branch("owner", game["game_id"], "branch", 0, "manual")
    assert error.value.code == "OPPONENT_CHANGED"


def test_engine_failure_preserves_board(tmp_path, monkeypatch):
    executable, weights = resources(tmp_path)
    engine = Edax(executable, weights, "4.6", 2)
    games = Games(Store(tmp_path / "games.sqlite3"), EdaxOpponent(engine), engine, 3)
    game = games.create("owner", "create", "O")

    def fail(*args):
        raise AppError("EDAX_TIMEOUT", "test-only", 503)

    monkeypatch.setattr(engine, "analyze", fail)
    with pytest.raises(AppError):
        games.move("owner", game["game_id"], "ai-move", 0)
    assert games.get(game["game_id"], "owner") == game
