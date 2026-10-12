from nemothello.games import advance, public_game
from nemothello.rules import Position, replay


def test_history_pass_and_terminal_replay():
    initial = Position((".OXXXXXX", "XXXXXXXX", "XXXXXXXX", "XXXXXXXX",
                        "XXXXXXXX", "XXXXXXXX", "XXXXXXXX", "XX.OXXXX"), "X")
    game = {
        "game_id": "game-1", "revision": 0, "board": list(initial.board), "turn": "X",
        "human_color": "X", "status": "active", "legal_moves": list(initial.moves),
        "history": [], "initial_board": list(initial.board), "initial_turn": "X",
        "opponent_config_id": "test-rules-only", "result": None,
    }
    advance(game, "a1")
    assert game["revision"] == 2
    assert [event["kind"] for event in game["history"]] == ["move", "pass"]
    assert game["history"][0]["turn"] == "O"
    assert game["history"][1]["turn"] == "X"
    advance(game, "c8")
    assert game["status"] == "finished"
    assert public_game(game)["result"]["winner"] == "X"
    moves = [event["coordinate"] for event in game["history"] if event["kind"] == "move"]
    assert list(replay(moves, initial).board) == game["board"]
