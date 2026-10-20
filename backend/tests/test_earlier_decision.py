import json
import subprocess
import sys
import time
from functools import cache
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from nemothello.board_features import capture_lines
from nemothello.coaching import review_context, verified_teaching_facts
from nemothello.earlier_decision import earlier_target, find_earlier_decision, threat_checker
from nemothello.edax import PV_MOVE, RESULT_LINE, Edax
from nemothello.games import Games, advance
from nemothello.main import app
from nemothello.nemotron import Nemotron
from nemothello.opponents import EdaxOpponent
from nemothello.position_lessons import lesson_context, position_at
from nemothello.rules import apply_move, legal_moves, opponent, square
from nemothello.schemas import EarlierDecisionResult
from nemothello.storage import Store
from nemothello.tasks import Tasks
from nemothello.teaching import compare_lesson

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = Path(__file__).parent / 'fixtures'


def source_game(filename):
    source = json.loads((DIRECTORY / filename).read_text())
    if 'game' in source:
        return source['game']
    review = source['review']
    game = {'initial_board': review['initial_board'], 'initial_turn': review['initial_turn'],
            'board': review['initial_board'], 'turn': review['initial_turn'], 'revision': 0,
            'history': [], 'result': None, 'human_color': review['human_color']}
    for event in review['history']:
        if event['kind'] == 'move':
            advance(game, event['coordinate'])
    assert game['result'] == review['result']
    return game


@cache
def exhaustive_corner(board, turn, attacker, target, remaining):
    row, column = square(target)
    if board[row][column] == attacker:
        return True
    if board[row][column] != '.' or turn is None or remaining == 0:
        return False
    moves = legal_moves(board, turn)
    if not moves and not legal_moves(board, opponent(turn)):
        return False
    outcomes = (exhaustive_corner(board if move == 'pass' else apply_move(board, turn, move),
                                 opponent(turn), attacker, target, remaining - (turn == attacker))
                for move in moves or ('pass',))
    return any(outcomes) if turn == attacker else all(outcomes)


def frozen_cases():
    return json.loads((DIRECTORY / 'earlier-decisions-native.json').read_text())['cases']


def test_every_connection_matches_the_complete_recorded_threat_episode_and_defensive_branch():
    passes = 0
    for case in frozen_cases():
        game = source_game(case['source_file'])
        result = EarlierDecisionResult.model_validate(case['result'])
        link = case['result']['link']
        assert result.status == 'verified'
        before = position_at(game, link['revision'])
        attacker = opponent(game['human_color'])
        assert link['evidence']['analysis']['board'] == list(before.board)
        assert link['evidence']['actor'] == game['human_color']
        scores = {item['coordinate']: item['score'] for item in link['evidence']['analysis']['candidates']}
        assert scores[link['recommended_move']] == max(scores.values()) > scores[link['recorded_move']]
        actual = apply_move(before.board, before.turn, link['recorded_move'])
        defensive = apply_move(before.board, before.turn, link['recommended_move'])
        assert exhaustive_corner(actual, attacker, attacker, link['target'], 2)
        assert not exhaustive_corner(defensive, attacker, attacker, link['target'], 2)
        assert not exhaustive_corner(before.board, before.turn, attacker, link['target'], 2)
        assert link['recorded_proof']['forced'] and not link['recommended_proof']['forced']
        assert [step['revision'] for step in link['continuity']] == list(range(link['revision'] + 1, case['revision'] + 2))
        threatened, _ = threat_checker(game['human_color'], link['target'])
        for step in link['continuity']:
            position = position_at(game, step['revision'])
            event = game['history'][step['revision'] - 1]
            passes += event['kind'] == 'pass'
            assert step['turn'] == position.turn
            assert step['max_plies'] == (3 if position.turn == attacker else 4)
            assert threatened(position.board, position.turn)
            assert exhaustive_corner(position.board, position.turn, attacker, link['target'], 2)
        comparison = compare_lesson({'evidence': [case['evidence']]}, case['revision'], case['evidence']['actual_move'])
        assert earlier_target(game, case['evidence'], comparison) == link['target']
    assert passes > 0
    forced = next(case for case in frozen_cases() if case['revision'] == 58)
    assert forced['result']['link']['revision'] == 12
    assert forced['result']['link']['revision'] != 42


def test_a_current_defensive_choice_or_a_branch_without_earlier_history_does_not_get_a_link():
    source = json.loads((DIRECTORY / 'review-native-positions.json').read_text())['review']
    game = source_game('review-native-positions.json')
    item = next(item for item in source['evidence'] if item['revision'] == 16)
    comparison = compare_lesson({'evidence': [item]}, 16, item['actual_move'])
    engine = Edax(ROOT / 'deploy/edax/edax', ROOT / 'deploy/edax/eval.dat', '4.6', 8)
    assert earlier_target(game, item, comparison) is None
    assert find_earlier_decision(game, item, comparison, engine)['status'] == 'not_applicable'
    case = frozen_cases()[0]
    position = position_at(game, case['revision'])
    branch = {'initial_board': list(position.board), 'initial_turn': position.turn,
              'board': list(position.board), 'turn': position.turn, 'revision': 0, 'history': [],
              'human_color': game['human_color'], 'result': None}
    advance(branch, case['evidence']['actual_move'])
    branch_evidence = {**case['evidence'], 'revision': 0}
    branch_comparison = compare_lesson({'evidence': [branch_evidence]}, 0, branch_evidence['actual_move'])
    assert earlier_target(branch, branch_evidence, branch_comparison)
    result = find_earlier_decision(branch, branch_evidence, branch_comparison, engine)
    assert result['status'] == 'not_found' and result['link'] is None
    assert engine.process is None


def test_questions_receive_only_a_verified_connection_with_its_local_limits():
    case = frozen_cases()[1]
    game = source_game(case['source_file'])
    context = lesson_context(game, case['evidence'], [])
    absent = review_context(context, 'Could I have defended this corner earlier?', revision=58)
    assert not any(fact['id'].endswith(':earlier_decision') for fact in absent['positions'][0]['facts'])
    context['earlier_decision'] = case['result']
    verified = review_context(context, 'Could I have defended this corner earlier?', revision=58)
    fact = next(fact for fact in verified['positions'][0]['facts'] if fact['id'].endswith(':earlier_decision'))
    assert fact['topic'] == 'forced_move'
    assert all(text in fact['text'] for text in ('g7', 'd7', 'h8', 'next two opponent turns', 'not proof'))
    context['earlier_decision'] = {'status': 'not_found', 'scope': case['result']['scope'], 'link': None}
    assert not any(fact['id'].endswith(':earlier_decision') for fact in review_context(context, None, revision=58)['positions'][0]['facts'])


def test_defensive_demonstrations_keep_the_comparison_goal_and_retain_other_corner_risks():
    source = json.loads((DIRECTORY / 'review-native-positions.json').read_text())['review']
    evidence = [*source['evidence'], *(case['result']['link']['evidence'] for case in frozen_cases())]
    checked, other_threats = 0, 0
    for item in evidence:
        comparison = compare_lesson({'evidence': [item]}, item['revision'], item['actual_move'])
        insight = comparison['insight']
        if insight['kind'] != 'corner_defense':
            continue
        checked += 1
        better = next(choice for choice in comparison['choices'] if choice['coordinate'] == insight['better_move'])
        if insight['example']:
            assert better['kind'] == 'corner_defense' and better['target'] == insight['target']
            assert [frame['coordinate'] for frame in better['frames'][1:]] == insight['example']
            assert better['corner_proof'] == insight['proof'] and not better['corner_proof']['forced']
            assert better['capture_lines'] == better['defense_lines'] == []
            assert len(better['frames']) <= 4
            last = better['frames'][-1]
            assert insight['target'] not in legal_moves(tuple(last['board']), opponent(item['actor']))
        facts = verified_teaching_facts(comparison, item['revision'])
        assert not any(fact['id'] == f"p{item['revision']}:proof_{better['coordinate']}" for fact in facts)
        board = tuple(better['frames'][1]['board'])
        for threat in insight['other_threats']:
            other_threats += 1
            assert threat['target'] != insight['target'] and threat['forced']
            assert exhaustive_corner(board, opponent(item['actor']), opponent(item['actor']), threat['target'], 2)
            assert any(threat['target'] in fact['text'] for fact in facts if fact['id'].endswith(':other_corners'))
    assert checked >= 2 and other_threats > 0


def test_corner_comparison_witnesses_replay_the_same_legal_sequence_on_both_boards():
    snapshots = json.loads((DIRECTORY / 'teaching-native-cases.json').read_text())
    checked = 0
    for comparison in snapshots.values():
        witness = comparison['insight'].get('witness')
        if not witness:
            continue
        checked += 1
        opportunity = witness['opportunity']
        states = {}
        for move in (opportunity['available_after'], opportunity['blocked_after']):
            choice = next(choice for choice in comparison['choices'] if choice['coordinate'] == move)
            board, actor = tuple(choice['frames'][1]['board']), choice['frames'][1]['turn']
            for coordinate in witness['prefix']:
                moves = legal_moves(board, actor)
                if coordinate == 'pass':
                    assert not moves and legal_moves(board, opponent(actor))
                else:
                    assert coordinate in moves
                    board = apply_move(board, actor, coordinate)
                actor = opponent(actor)
            assert list(board) == choice['frames'][len(witness['prefix']) + 1]['board']
            states[move] = board
        available, blocked = (states[opportunity[key]] for key in ('available_after', 'blocked_after'))
        actor, coordinate = opportunity['actor'], opportunity['coordinate']
        assert coordinate in legal_moves(available, actor)
        assert coordinate not in legal_moves(blocked, actor)
        assert opportunity['capture_line'] in capture_lines(available, actor, coordinate)
        expected = []
        for coordinate in opportunity['capture_line']:
            row, col = square(coordinate)
            if available[row][col] != blocked[row][col]:
                expected.append({'coordinate': coordinate, 'available': available[row][col], 'blocked': blocked[row][col]})
        assert expected == opportunity['changes']
        facts = verified_teaching_facts(comparison, comparison['revision'])
        assert any(fact['id'].endswith(':corner_contrast') and 'out of turn' in fact['text'] for fact in facts)
    assert checked >= 4


def test_real_api_verifies_and_caches_the_forced_history_link_without_a_model(tmp_path, monkeypatch):
    executable, weights = ROOT / 'deploy/edax/edax', ROOT / 'deploy/edax/eval.dat'
    if not executable.is_file() or not weights.is_file():
        pytest.skip('Native Edax and eval.dat are required')
    for name, value in {
        'EDAX_EXECUTABLE': str(executable), 'EDAX_EVAL_FILE': str(weights), 'EDAX_VERSION': '4.6',
        'DATABASE_PATH': str(tmp_path / 'earlier.sqlite3'), 'BACKEND_SERVICE_TOKEN': 'local-earlier-test',
        'TOKEN_FACTORY_API_KEY': '', 'TOKEN_FACTORY_MODEL_ID': '',
    }.items():
        monkeypatch.setenv(name, value)
    with TestClient(app, headers={'Authorization': 'Bearer local-earlier-test', 'X-Session-ID': 'earlier-owner'}) as connection:
        original = source_game('forced-move-native.json')
        game = app.state.games.new_game(original['human_color'])
        for event in original['history']:
            if event['kind'] == 'move':
                advance(game, event['coordinate'])
        with app.state.store.transaction() as db:
            app.state.store.save(db, 'game', game['game_id'], 'earlier-owner', game)
        path = f"/games/{game['game_id']}/lessons"
        response = connection.post(path, json={'request_id': str(uuid4()), 'revision': 58})
        assert response.status_code == 200, response.text
        task = response.json()
        deadline = time.monotonic() + 10
        while task['status'] in ('queued', 'running') and time.monotonic() < deadline:
            time.sleep(0.1)
            task = connection.get(f"/tasks/{task['task_id']}").json()
        assert task['status'] == 'succeeded', task
        assert task['result']['model_id'] is None and task['result']['usage'] is None
        lesson = connection.get(path, params={'revision': 58}).json()
        assert lesson['earlier_eligible'] and 'previous_decision_revision' not in lesson
        question = connection.post(path, json={'request_id': str(uuid4()), 'revision': 58,
                                               'question': 'Could I have defended this corner earlier?'}).json()
        deadline = time.monotonic() + 10
        while question['status'] in ('queued', 'running') and time.monotonic() < deadline:
            time.sleep(0.1)
            question = connection.get(f"/tasks/{question['task_id']}").json()
        assert question['status'] == 'failed' and question['error']['code'] == 'REVIEW_NOT_CONFIGURED'
        cached = connection.get(path, params={'revision': 58}).json()['earlier_decision']
        assert cached['status'] == 'verified'
        engine = app.state.games.review_engine_of(game)
        engine.close()
        response = connection.get(path + '/earlier', params={'revision': 58})
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['status'] == 'verified' and result['link']['revision'] == 12
        assert [result['link'][key] for key in ('recorded_move', 'recommended_move', 'target')] == ['g7', 'd7', 'h8']
        assert len(result['link']['continuity']) == 47
        assert engine.process is None
        assert connection.get(path + '/earlier', params={'revision': 58}).json() == result
        assert engine.process is None
        assert connection.get(path, params={'revision': 58}).json()['earlier_decision'] == result
        prepared = connection.get(path, params={'revision': 12}).json()
        assert prepared['coaching_status'] == 'not_requested'
        assert prepared['coaching'] == [] and prepared['model_id'] is None and prepared['task_id'] is None
        assert [choice['coordinate'] for choice in prepared['comparison']['choices']] == ['g7', 'd7']
        assert not any(task['inputs'].get('revision') == 12 for task in app.state.store.list_records('task', 'earlier-owner'))
        assert connection.get(path + '/earlier', params={'revision': 58}, headers={'X-Session-ID': 'another-owner'}).status_code == 404
        assert connection.get(path + '/earlier', params={'revision': 59}).status_code == 422
        assert app.state.store.get('game', game['game_id'], 'earlier-owner') == game
        independent, evidence = tmp_path / 'independent.json', tmp_path / 'evidence.json'
        subprocess.run([sys.executable, str(ROOT / 'scripts/export_teaching_cases.py'), '--database',
                        str(app.state.store.path), '--output', str(independent), '--evidence-output', str(evidence)], check=True)
        assert 'earlier_decision' not in json.loads(independent.read_text())['cases'][0]
        exported = json.loads(evidence.read_text())['cases'][0]['earlier_decision']
        assert EarlierDecisionResult.model_validate(exported).model_dump() == result
        assert not app.state.settings.token_factory_api_key.get_secret_value()


def test_a_planned_move_becomes_recorded_history_before_its_evidence_is_reused(tmp_path):
    executable, weights = ROOT / 'deploy/edax/edax', ROOT / 'deploy/edax/eval.dat'
    if not executable.is_file() or not weights.is_file():
        pytest.skip('Native Edax and eval.dat are required')
    original = source_game('forced-move-native.json')
    engine = Edax(executable, weights, '4.6', 8)
    model = Nemotron('', 'https://unused.invalid/v1', '')
    store = Store(tmp_path / 'planned.sqlite3')
    games = Games(store, EdaxOpponent(engine), engine, 3)
    tasks = Tasks(store, games, model)
    game = games.new_game(original['human_color'])
    for event in original['history']:
        if event['revision'] <= 12 and event['kind'] == 'move':
            advance(game, event['coordinate'])
    with store.transaction() as db:
        store.save(db, 'game', game['game_id'], 'owner', game)
    try:
        task = games.create_position_lesson_task('owner', game['game_id'], 'unplayed-lesson', 12,
                                                 reflection='I want to place a disc near h8.')
        tasks.process('owner', store.get('task', task['task_id'], 'owner'))
        original_lesson = store.get('lesson', f"{game['game_id']}:12", 'owner')
        assert not original_lesson['evidence']['is_played']
        assert original_lesson['coaching_status'] == 'failed'
        reflection = original_lesson['reflection']
        game = games.move('owner', game['game_id'], 'actual-g7', 12, 'g7')
        for event in original['history']:
            if event['revision'] > 13 and event['kind'] == 'move':
                advance(game, event['coordinate'])
        assert game['result'] == original['result']
        with store.transaction() as db:
            store.save(db, 'game', game['game_id'], 'owner', game)
        current = games.create_position_lesson_task('owner', game['game_id'], 'forced-later', 58)
        tasks.process('owner', store.get('task', current['task_id'], 'owner'))
        engine.close()
        result = games.earlier_decision('owner', game['game_id'], 58)
        assert result['status'] == 'verified' and result['link']['revision'] == 12
        revised = games.position_lesson('owner', game['game_id'], 12)
        assert revised['evidence']['is_played'] and revised['evidence']['actual_move'] == 'g7'
        assert revised['evidence']['analysis'] == original_lesson['evidence']['analysis']
        assert revised['reflection'] == reflection and reflection['source'] == 'review_plan'
        assert revised['coaching_status'] == 'not_requested' and revised['model_id'] is None
        assert [choice['coordinate'] for choice in revised['comparison']['choices']] == ['g7', 'd7']
        assert store.get('task', task['task_id'], 'owner')['error']['code'] == 'REVIEW_NOT_CONFIGURED'
        assert engine.process is None
        assert store.get('game', game['game_id'], 'owner') == game
    finally:
        engine.close()
        model.close()


def test_native_edax_checks_both_earlier_corner_certificates():
    executable, weights = ROOT / 'deploy/edax/edax', ROOT / 'deploy/edax/eval.dat'
    if not executable.is_file() or not weights.is_file():
        pytest.skip('Native Edax and eval.dat are required')
    engine = Edax(executable, weights, '4.6', 1)

    def native_moves(board, actor):
        engine._exchange(f"setboard {''.join(board)} {actor}")
        output = engine._exchange('hint 64')
        result = set()
        for line in output.splitlines():
            match = RESULT_LINE.match(line)
            if match and not match.group(3):
                pv = PV_MOVE.findall(match.group(5))
                if pv and pv[0].lower() != 'pa':
                    result.add(pv[0].lower())
        return result

    try:
        engine._start()
        snapshots = json.loads((DIRECTORY / 'teaching-native-cases.json').read_text())
        for comparison in snapshots.values():
            witness = comparison['insight'].get('witness')
            if not witness:
                continue
            opportunity = witness['opportunity']
            for key, available in (('available_after', True), ('blocked_after', False)):
                choice = next(choice for choice in comparison['choices'] if choice['coordinate'] == opportunity[key])
                board = tuple(choice['frames'][len(witness['prefix']) + 1]['board'])
                moves = native_moves(board, opportunity['actor'])
                assert moves == set(legal_moves(board, opportunity['actor']))
                assert (opportunity['coordinate'] in moves) == available
        for case in frozen_cases():
            link = case['result']['link']
            board = tuple(link['evidence']['analysis']['board'])
            defender, attacker, target = link['actor'], opponent(link['actor']), link['target']
            assert native_moves(board, defender) == {item['coordinate'] for item in link['evidence']['analysis']['candidates']}
            comparison = compare_lesson({'evidence': [link['evidence']]}, link['revision'], link['recorded_move'])
            certificates = [(link['recorded_move'], link['recorded_proof']),
                            (link['recommended_move'], link['recommended_proof'])]
            certificates += [(link['recommended_move'], proof) for proof in comparison['insight']['other_threats']]
            for move, proof in certificates:
                target = proof['target']
                after = apply_move(board, defender, move)
                attacks = native_moves(after, attacker)
                if proof['forced']:
                    assert proof['attack'] in attacks or proof['attack'] == 'pass' and not attacks
                    if proof['attack'] == target:
                        continue
                    attacked = after if proof['attack'] == 'pass' else apply_move(after, attacker, proof['attack'])
                    defenses = native_moves(attacked, defender)
                    assert set(proof['defenses']) == (defenses or {'pass'})
                    for defense in proof['defenses']:
                        defended = attacked if defense == 'pass' else apply_move(attacked, defender, defense)
                        assert target in native_moves(defended, attacker)
                else:
                    assert target not in attacks
                    assert {item['attack'] for item in proof['refutations']} == (attacks or {'pass'})
                    for refutation in proof['refutations']:
                        attacked = after if refutation['attack'] == 'pass' else apply_move(after, attacker, refutation['attack'])
                        defense = refutation['defense']
                        if defense is None:
                            assert not native_moves(attacked, attacker) and not native_moves(attacked, defender)
                        else:
                            defenses = native_moves(attacked, defender)
                            assert defense in defenses or defense == 'pass' and not defenses
                            defended = attacked if defense == 'pass' else apply_move(attacked, defender, defense)
                            assert target not in native_moves(defended, attacker)
    finally:
        engine.close()
