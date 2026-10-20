import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from nemothello.edax import PV_MOVE, RESULT_LINE, Edax
from nemothello.errors import AppError
from nemothello.games import advance
from nemothello.main import app
from nemothello.practice import case_position, grade_practice, practice_bank, select_practice
from nemothello.reply_practice import reply_options
from nemothello.rules import INITIAL_BOARD, apply_move, legal_moves, opponent, square
from nemothello.schemas import ReplyPracticeFeedback, ReplyPracticeQuestion

ROOT = Path(__file__).resolve().parents[2]


def reply_cases():
    bank = practice_bank()
    for case in bank['cases']:
        if case['objective'] == 'reply_access':
            position, context = case_position(case, bank)
            yield ReplyPracticeQuestion.model_validate({
                'question_id': case['id'], 'objective': 'reply_access', 'board': list(position.board),
                'turn': position.turn, 'context': context, 'target': case['target'],
                'rubric_version': 'reply-access-v1',
            }).model_dump()


def test_all_legal_comparison_pairs_are_graded_by_complete_reply_sets():
    count = 0
    for question in reply_cases():
        count += 1
        options = reply_options(tuple(question['board']), question['turn'])
        for move in options:
            for alternative in options:
                result = ReplyPracticeFeedback.model_validate(grade_practice(question, move, None, alternative))
                assert result.legal and result.alternative_legal
                assert result.move_matches_goal == (question['target'] not in options[move])
                assert result.alternative_matches == (question['target'] in options[alternative])
                assert not result.reason_reviewed
                for frame, replies in ((result.blocking_frame, result.replies_after_blocking),
                                       (result.allowing_frame, result.replies_after_allowing)):
                    assert replies == list(legal_moves(tuple(frame.board), opponent(question['turn'])))
                assert question['target'] not in result.replies_after_blocking
                assert question['target'] in result.replies_after_allowing
                witness = result.witness
                assert witness.coordinate == question['target']
                assert witness.available_after == result.allowing_frame.coordinate
                assert witness.blocked_after == result.blocking_frame.coordinate
                ray = witness.capture_line
                available, blocked = result.allowing_frame.board, result.blocking_frame.board
                after = apply_move(tuple(available), opponent(question['turn']), question['target'])
                for coordinate in ray[1:-1]:
                    row, col = square(coordinate)
                    assert available[row][col] == question['turn']
                    assert after[row][col] == opponent(question['turn'])
                assert witness.changes
                for change in witness.changes:
                    row, col = square(change.coordinate)
                    assert change.available == available[row][col] and change.blocked == blocked[row][col]
                if result.added_reply:
                    target = result.added_reply.coordinate
                    assert target in result.replies_after_blocking and target not in result.replies_after_allowing
        result = grade_practice(question, 'd4', None, 'd4')
        assert not result['legal'] and not result['alternative_legal']
        with pytest.raises(AppError) as error:
            grade_practice(question, next(iter(options)), None)
        assert error.value.code == 'PRACTICE_PAIR'
    assert count == 4


def test_reply_questions_expose_no_answers_or_ranking_before_submission():
    game = {'initial_board': list(INITIAL_BOARD), 'history': []}
    question = select_practice('reply_access', game, set())
    assert set(question) == {'question_id', 'objective', 'board', 'turn', 'context', 'target', 'rubric_version'}
    assert select_practice('reply_access', game, {question['question_id']})['question_id'] != question['question_id']
    assert select_practice('reply_access', {**game, 'history': [{'board': question['board']}]}, set())['question_id'] != question['question_id']


def test_frontend_feedback_fixtures_reproduce_the_frozen_rule_results():
    fixture = json.loads((Path(__file__).parent / 'fixtures/reply-practice-native.json').read_text())
    questions = {item['question_id']: item for item in reply_cases()}
    for entry in fixture['cases']:
        question = entry['question']
        assert question == questions[question['question_id']]
        assert grade_practice(question, entry['move'], None, entry['alternative']) == entry['feedback']
    assert len(fixture['cases']) == len(questions) == 4


def test_real_api_connects_a_native_comparison_to_an_independent_first_attempt(tmp_path, monkeypatch):
    executable, weights = ROOT / 'deploy/edax/edax', ROOT / 'deploy/edax/eval.dat'
    if not executable.is_file() or not weights.is_file():
        pytest.skip('Native Edax and eval.dat are required')
    for name, value in {
        'EDAX_EXECUTABLE': str(executable), 'EDAX_EVAL_FILE': str(weights), 'EDAX_VERSION': '4.6',
        'DATABASE_PATH': str(tmp_path / 'reply.sqlite3'), 'BACKEND_SERVICE_TOKEN': 'local-reply-test',
        'TOKEN_FACTORY_API_KEY': '', 'TOKEN_FACTORY_MODEL_ID': '',
    }.items():
        monkeypatch.setenv(name, value)
    with TestClient(app, headers={'Authorization': 'Bearer local-reply-test', 'X-Session-ID': 'reply-owner'}) as connection:
        source = json.loads((Path(__file__).parent / 'fixtures/review-native-positions.json').read_text())['review']
        game = app.state.games.new_game(source['human_color'])
        for event in source['history']:
            if event['kind'] == 'move':
                advance(game, event['coordinate'])
        item = next(item for item in source['evidence'] if item['revision'] == 2)
        with app.state.store.transaction() as db:
            app.state.store.save(db, 'game', game['game_id'], 'reply-owner', game)
            app.state.store.save(db, 'lesson', f"{game['game_id']}:2", 'reply-owner', {
                'game_id': game['game_id'], 'revision': 2, 'evidence': item,
            })
        path = f"/games/{game['game_id']}/lessons/practice"
        response = connection.get(path, params={'revision': 2, 'move': 'b6'})
        assert response.status_code == 200, response.text
        question = response.json()
        assert question['objective'] == 'reply_access'
        options = reply_options(tuple(question['board']), question['turn'])
        move = next(move for move, replies in options.items() if question['target'] not in replies)
        alternative = next(move for move, replies in options.items() if question['target'] in replies)
        payload = {'request_id': str(uuid4()), 'revision': 2, 'lesson_move': 'b6',
                   'question_id': question['question_id'], 'move': move, 'alternative': alternative,
                   'reason': 'I checked how the two moves change the opponent capture line.'}
        first = connection.post(path, json=payload)
        assert first.status_code == 200, first.text
        assert first.json()['move_matches_goal'] and first.json()['alternative_matches']
        assert connection.post(path, json=payload).json() == first.json()
        attempts = app.state.store.list_records('practice_attempt', 'reply-owner')
        assert len(attempts) == 1 and attempts[0]['answer']['alternative'] == alternative
        assert attempts[0]['feedback']['rubric_version'] == 'reply-access-v1'
        assert app.state.store.get('game', game['game_id'], 'reply-owner') == game
        assert connection.get(path, params={'revision': 2, 'move': 'b6'}).json()['question_id'] != question['question_id']
        assert connection.get(path, params={'revision': 2, 'move': 'b6'}, headers={'X-Session-ID': 'another-owner'}).status_code == 404
        output = tmp_path / 'reasons.json'
        subprocess.run([sys.executable, str(ROOT / 'scripts/export_practice_attempts.py'), '--database',
                        str(app.state.store.path), '--output', str(output)], check=True)
        exported = json.loads(output.read_text())
        assert exported['protocols'] == ['reply-access-v1']
        assert exported['attempts'][0]['answer']['reason'] == payload['reason']
        assert exported['attempts'][0]['human_review']['reason_score'] is None
        assert not app.state.settings.token_factory_api_key.get_secret_value()
        assert not app.state.settings.token_factory_model_id
        assert all(engine.process is None for engine in app.state.games.hint_engines.values())


def test_native_edax_checks_every_root_reply_set_in_the_fixed_exercises():
    executable, weights = ROOT / 'deploy/edax/edax', ROOT / 'deploy/edax/eval.dat'
    if not executable.is_file() or not weights.is_file():
        pytest.skip('Native Edax and eval.dat are required')
    engine = Edax(executable, weights, '4.6', 1)
    try:
        engine._start()
        engine._exchange('verbose 1')
        for question in reply_cases():
            for move, expected in reply_options(tuple(question['board']), question['turn']).items():
                board = apply_move(tuple(question['board']), question['turn'], move)
                engine._exchange(f"setboard {''.join(question['board'])} {question['turn']}")
                replay = engine._exchange(f'play {move}')
                native_board = []
                for line in replay.splitlines():
                    fields = line.split()
                    if len(fields) >= 10 and fields[0] in '12345678' and fields[9] == fields[0]:
                        native_board.append(''.join(fields[1:9]).translate(str.maketrans('*O-.', 'XO..')))
                assert native_board == list(board)
                engine._exchange(f"setboard {''.join(board)} {opponent(question['turn'])}")
                output = engine._exchange('hint 64')
                actual = set()
                for line in output.splitlines():
                    match = RESULT_LINE.match(line)
                    if match and not match.group(3):
                        pv = PV_MOVE.findall(match.group(5))
                        if pv and pv[0].lower() != 'pa':
                            actual.add(pv[0].lower())
                assert actual == set(expected)
    finally:
        engine.close()
