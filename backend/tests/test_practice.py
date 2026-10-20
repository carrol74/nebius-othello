import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from nemothello.edax import PV_MOVE, RESULT_LINE
from nemothello.games import advance
from nemothello.main import app
from nemothello.practice import answer_lines, case_position, grade_practice, position_key, practice_bank, practice_position, select_practice
from nemothello.rules import INITIAL_BOARD, apply_move, legal_moves, opponent, square
from nemothello.schemas import PracticeFeedback, PracticeQuestion


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def client(tmp_path, monkeypatch):
    executable, weights = ROOT / 'deploy/edax/edax', ROOT / 'deploy/edax/eval.dat'
    if not executable.is_file() or not weights.is_file():
        pytest.skip('Native Edax and eval.dat are required')
    for name, value in {
        'EDAX_EXECUTABLE': str(executable), 'EDAX_EVAL_FILE': str(weights), 'EDAX_VERSION': '4.6',
        'DATABASE_PATH': str(tmp_path / 'practice.sqlite3'), 'BACKEND_SERVICE_TOKEN': 'local-practice-test',
        'TOKEN_FACTORY_API_KEY': '', 'TOKEN_FACTORY_MODEL_ID': '',
    }.items():
        monkeypatch.setenv(name, value)
    with TestClient(app, headers={'Authorization': 'Bearer local-practice-test', 'X-Session-ID': 'practice-owner'}) as connection:
        case = json.loads((Path(__file__).parent / 'fixtures/ordinary-move-native.json').read_text())
        game = app.state.games.new_game('X')
        for event in case['history']:
            if event['kind'] == 'move':
                advance(game, event['coordinate'])
        advance(game, case['evidence']['actual_move'])
        with app.state.store.transaction() as db:
            app.state.store.save(db, 'game', game['game_id'], 'practice-owner', game)
            app.state.store.save(db, 'lesson', f"{game['game_id']}:8", 'practice-owner', {
                'game_id': game['game_id'], 'revision': 8, 'evidence': case['evidence'],
            })
        yield connection, game


def test_frozen_games_replay_to_terminal_and_cases_are_distinct_from_teaching_samples():
    bank = practice_bank()
    teaching = json.loads((Path(__file__).parent / 'fixtures/review-native-positions.json').read_text())['review']
    ordinary = json.loads((Path(__file__).parent / 'fixtures/ordinary-move-native.json').read_text())
    excluded = {position_key(item['analysis']['board']) for item in [*teaching['evidence'], ordinary['evidence']]}
    seen, counts = set(), {}
    for game in bank['games']:
        position, _ = practice_position(game['moves'], len(game['moves']))
        assert position.turn is None and position.result() == game['result']
    for case in bank['cases']:
        position, context = case_position(case, bank)
        key = position_key(position.board)
        assert key not in seen and key not in excluded
        seen.add(key)
        lines = answer_lines(position, context, case['objective'])
        assert lines and len(position.moves) >= 3
        if case['objective'] != 'reply':
            assert len({line[0] for line in lines}) < len(position.moves)
        counts[case['objective']] = counts.get(case['objective'], 0) + 1
    assert counts == {'anchor': 4, 'recapture': 4, 'reply': 4}


def test_grading_accepts_every_matching_capture_and_rejects_wrong_anchors():
    bank = practice_bank()
    for case in bank['cases']:
        position, context = case_position(case, bank)
        question = PracticeQuestion.model_validate({
            'question_id': case['id'], 'objective': case['objective'], 'board': list(position.board),
            'turn': position.turn, 'context': context, 'rubric_version': bank['rubric_version'],
        }).model_dump()
        lines = answer_lines(position, context, case['objective'])
        pairs = {(line[0], line[-1]) for line in lines}
        own = [f'{chr(97+c)}{r+1}' for r in range(8) for c in range(8) if position.board[r][c] == position.turn]
        for move in position.moves:
            for anchor in own:
                feedback = PracticeFeedback.model_validate(grade_practice(question, move, anchor))
                assert feedback.legal
                assert feedback.move_matches_goal == any(line[0] == move for line in lines)
                assert feedback.anchor_matches == ((move, anchor) in pairs)
                assert feedback.reason_reviewed is False
                ray = feedback.capture_line
                after = apply_move(position.board, position.turn, ray[0])
                for coordinate in ray[1:-1]:
                    r, c = square(coordinate)
                    assert position.board[r][c] == opponent(position.turn) and after[r][c] == position.turn
        occupied = own[0]
        assert not grade_practice(question, occupied, occupied)['legal']


def test_selection_excludes_current_game_replays_symmetries_and_used_questions():
    game = {'initial_board': list(INITIAL_BOARD), 'history': []}
    first = select_practice('anchor', game, set())
    rotated = tuple(''.join(first['board'][7-c][r] for c in range(8)) for r in range(8))
    swapped = [row.translate(str.maketrans('XO', 'OX')) for row in rotated]
    excluded = select_practice('anchor', {**game, 'history': [{'board': swapped}]}, set())
    assert excluded['question_id'] != first['question_id']
    assert select_practice('anchor', game, {first['question_id']})['question_id'] != first['question_id']
    assert select_practice('anchor', game, {case['id'] for case in practice_bank()['cases']}) is None


def test_real_api_saves_first_attempt_and_reason_idempotently_without_touching_game(client, tmp_path):
    connection, game = client
    path = f"/games/{game['game_id']}/lessons/practice"
    response = connection.get(path, params={'revision': 8, 'move': 'f5'})
    assert response.status_code == 200, response.text
    question = response.json()
    assert set(question) == {'question_id', 'objective', 'board', 'turn', 'context', 'rubric_version'}
    position, context = case_position(next(case for case in practice_bank()['cases'] if case['id'] == question['question_id']), practice_bank())
    answers = answer_lines(position, context, question['objective'])
    payload = {'request_id': str(uuid4()), 'revision': 8, 'lesson_move': 'f5',
               'question_id': question['question_id'], 'move': answers[0][0], 'anchor': answers[0][-1],
               'reason': 'The two friendly ends surround the opposing discs.'}
    first = connection.post(path, json=payload)
    assert first.status_code == 200, first.text
    assert first.json()['anchor_matches'] and not first.json()['reason_reviewed']
    assert connection.post(path, json=payload).json() == first.json()
    attempts = app.state.store.list_records('practice_attempt', 'practice-owner')
    assert len(attempts) == 1 and attempts[0]['answer']['reason'] == payload['reason']
    assert app.state.store.get('game', game['game_id'], 'practice-owner') == game
    assert connection.get(path, params={'revision': 8, 'move': 'f5'}).json()['question_id'] != question['question_id']
    assert connection.get(path, params={'revision': 8, 'move': 'f5'}, headers={'X-Session-ID': 'another-owner'}).status_code == 404
    assert connection.post(path, json={**payload, 'request_id': str(uuid4()), 'reason': ' '}).status_code == 422
    assert all(engine.process is None for engine in app.state.games.hint_engines.values())
    output = tmp_path / 'human-review.json'
    subprocess.run([sys.executable, str(ROOT / 'scripts/export_practice_attempts.py'),
                    '--database', str(app.state.store.path), '--output', str(output)], check=True)
    exported = json.loads(output.read_text())
    assert exported['attempts'][0]['answer']['reason'] == payload['reason']
    assert exported['attempts'][0]['human_review']['reason_score'] is None
    assert 'owner' not in output.read_text() and game['game_id'] not in output.read_text()


def test_native_edax_checks_legal_moves_in_every_frozen_practice_position(client):
    engine = app.state.games.edax
    engine._start()
    bank = practice_bank()
    for case in bank['cases']:
        position, _ = case_position(case, bank)
        engine._exchange(f"setboard {''.join(position.board)} {position.turn}")
        output = engine._exchange('hint 64')
        moves = set()
        for line in output.splitlines():
            match = RESULT_LINE.match(line)
            if match and not match.group(3):
                pv = PV_MOVE.findall(match.group(5))
                if pv and pv[0].lower() != 'pa':
                    moves.add(pv[0].lower())
        assert moves == set(legal_moves(position.board, position.turn))
