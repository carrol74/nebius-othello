import json
import subprocess
import sys
from collections import Counter
from copy import deepcopy
from pathlib import Path

import pytest

from nemothello.assessment import (
    CONDITIONS,
    OBJECTIVES,
    allocation_schedule,
    freeze_assessment,
    game_positions,
    grade_assessment,
)
from nemothello.edax import PV_MOVE, RESULT_LINE, Edax
from nemothello.practice import practice_bank
from nemothello.rules import apply_move, legal_moves, opponent

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope='module')
def packets(tmp_path_factory):
    if not all((ROOT / path).is_file() for path in ('deploy/edax/edax', 'deploy/edax/eval.dat')):
        pytest.skip('Native Edax and eval.dat are required')
    output = tmp_path_factory.mktemp('assessment') / 'frozen'
    command = [sys.executable, str(ROOT / 'scripts/teaching_assessment.py'), 'prepare',
               '--output', str(output), '--source-seed', '20261021']
    subprocess.run(command, check=True)
    yield (json.loads((output / 'participant-forms.json').read_text()),
           json.loads((output / 'private-answer-key.json').read_text()), output, command)


def source_bank(key):
    return {'source': key['source'], 'games': key['games'],
            'cases': [case['source'] for case in key['cases']], 'rubric_version': 'capture-lines-v1'}


def test_native_assessment_forms_are_frozen_balanced_and_have_no_answer_fields(packets):
    public, key, output, command = packets
    assert len(key['games']) == 4 and len(key['cases']) == 16
    assert key['expert_review'] == key['study_status'] == 'not_run'
    assert key['form_equivalence'] == 'unvalidated'
    assert json.loads((output / 'private-allocation.json').read_text())['assignments'] == []
    for questions in public['forms'].values():
        assert Counter(question['objective'] for question in questions) == Counter({name: 2 for name in OBJECTIVES})
        for question in questions:
            assert set(question) == {'question_id', 'objective', 'board', 'turn', 'context', 'rubric_version'} | (
                {'target'} if question['objective'] == 'reply_access' else set())
    text = json.dumps(public)
    for field in ('accepted_pairs', 'source', 'games', 'seeds', 'feedback', 'score', 'recommended_move'):
        assert f'"{field}"' not in text
    frozen = (output / 'private-answer-key.json').read_bytes()
    retry = subprocess.run(command, capture_output=True, text=True, check=False)
    assert retry.returncode != 0 and 'must not be overwritten' in retry.stderr
    assert (output / 'private-answer-key.json').read_bytes() == frozen
    practice_positions = set().union(*(game_positions(game) for game in practice_bank()['games']))
    _, regenerated = freeze_assessment(source_bank(key), practice_bank()['games'], [])
    assert all(not game_positions(game) <= practice_positions for game in key['games'])
    assert [case['question'] for case in regenerated['cases']] == [case['question'] for case in key['cases']]


def test_source_and_symmetry_overlap_rejects_the_entire_packet(packets):
    _, key, _, _ = packets
    bank = source_bank(key)
    with pytest.raises(ValueError, match='overlaps'):
        freeze_assessment(bank, [bank['games'][0]], [])
    board = key['cases'][0]['question']['board']
    rotated = [''.join(board[7 - col][row] for col in range(8)) for row in range(8)]
    reflected = [row[::-1].translate(str.maketrans('XO', 'OX')) for row in rotated]
    with pytest.raises(ValueError, match='overlaps'):
        freeze_assessment(bank, [], [reflected])
    duplicate = deepcopy(bank)
    duplicate['games'][2] = duplicate['games'][0]
    with pytest.raises(ValueError):
        freeze_assessment(duplicate, [], [])
    incomplete = deepcopy(bank)
    incomplete['games'][0]['moves'].pop()
    with pytest.raises(ValueError, match='terminal results'):
        freeze_assessment(incomplete, [], [])


def test_allocation_balances_condition_and_form_order_without_changing_an_assigned_prefix():
    schedule = allocation_schedule(20, 20261020)
    assert schedule[:7] == allocation_schedule(7, 20261020)
    assert schedule == allocation_schedule(20, 20261020)
    for start in range(0, len(schedule), 4):
        block = schedule[start:start + 4]
        assert {(row['condition'], row['baseline']) for row in block} == {
            (condition, form) for condition in CONDITIONS for form in ('form-a', 'form-b')}
        assert all(row['baseline'] != row['post'] for row in block)
    assert allocation_schedule(0, 1) == []


def test_first_attempt_grading_preserves_missing_answers_and_blinds_written_reasons(packets, tmp_path):
    _, key, output, _ = packets
    responses = []
    for case in key['cases'][:-1]:
        question, (move, second) = case['question'], case['accepted_pairs'][0]
        responses.append({'question_id': question['question_id'], 'move': move,
                          'alternative' if question['objective'] == 'reply_access' else 'anchor': second,
                          'reason': 'Rule-derived contract-test answer; no participant was enrolled.'})
    responses += [{**responses[0], 'move': 'd4', 'reason': 'Later attempt must not replace the first.'}]
    report, blind = grade_assessment(key, responses, 19)
    assert report['learning_effect'] == 'not_estimated'
    assert report['duplicate_attempts_ignored'] == 1
    assert sum(form['assigned'] for form in report['forms'].values()) == 16
    assert sum(form['correct'] for form in report['forms'].values()) == 15
    assert sum(form['missing'] for form in report['forms'].values()) == 1
    assert all(not row['reason_reviewed'] for row in report['items'])
    assert all(row['review']['reason_score'] is None for row in blind['cases'])
    assert all('question_id' not in row['question'] for row in blind['cases'])
    assert len(report['blinded_review_mapping']) == len(blind['cases']) == 16
    for field in ('form', 'condition', 'correct', 'accepted_pairs', 'source'):
        assert f'"{field}"' not in json.dumps(blind)
    response_path = tmp_path / 'contract-responses.json'
    response_path.write_text(json.dumps(responses))
    subprocess.run([sys.executable, str(ROOT / 'scripts/teaching_assessment.py'), 'grade',
                    '--key', str(output / 'private-answer-key.json'), '--responses', str(response_path),
                    '--output', str(tmp_path / 'scored'), '--seed', '19'], check=True)
    assert json.loads((tmp_path / 'scored/private-scores.json').read_text()) == report
    assert json.loads((tmp_path / 'scored/blinded-reasons.json').read_text()) == blind
    with pytest.raises(ValueError, match='does not belong'):
        grade_assessment(key, [{'question_id': 'unknown'}], 19)


def test_every_accepted_pair_and_wrong_legal_alternative_is_graded_without_reason_scoring(packets):
    _, key, _, _ = packets
    for case in key['cases']:
        question = case['question']
        allowed = {tuple(pair) for pair in case['accepted_pairs']}
        moves = legal_moves(tuple(question['board']), question['turn'])
        seconds = moves if question['objective'] == 'reply_access' else [
            f'{chr(97 + col)}{row + 1}' for row in range(8) for col in range(8)
            if question['board'][row][col] == question['turn']]
        for move in moves:
            for second in seconds:
                response = {'question_id': question['question_id'], 'move': move, 'reason': '',
                            'alternative' if question['objective'] == 'reply_access' else 'anchor': second}
                report, _ = grade_assessment(key, [response], 1)
                row = next(row for row in report['items'] if row['question_id'] == question['question_id'])
                assert row['correct'] == ((move, second) in allowed)
                assert row['reason_reviewed'] is False


def test_native_edax_replays_every_assessment_root_and_checks_all_reply_sets(packets):
    _, key, _, _ = packets
    engine = Edax(ROOT / 'deploy/edax/edax', ROOT / 'deploy/edax/eval.dat', '4.6', 1)

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
        engine._exchange('verbose 1')
        for case in key['cases']:
            question = case['question']
            board, turn = tuple(question['board']), question['turn']
            options = legal_moves(board, turn)
            assert native_moves(board, turn) == set(options)
            for move in options:
                engine._exchange(f"setboard {''.join(board)} {turn}")
                output = engine._exchange(f'play {move}')
                native = []
                for line in output.splitlines():
                    fields = line.split()
                    if len(fields) >= 10 and fields[0] in '12345678' and fields[9] == fields[0]:
                        native.append(''.join(fields[1:9]).translate(str.maketrans('*O-.', 'XO..')))
                after = apply_move(board, turn, move)
                assert native == list(after)
                assert native_moves(after, opponent(turn)) == set(legal_moves(after, opponent(turn)))
    finally:
        engine.close()
