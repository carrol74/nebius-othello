from pathlib import Path

import pytest

from nemothello.edax import PV_MOVE, RESULT_LINE, Edax
from nemothello.errors import AppError
from nemothello.practice import case_position, grade_practice, practice_bank
from nemothello.reply_practice import reply_options
from nemothello.rules import apply_move, legal_moves, opponent, square

ROOT = Path(__file__).resolve().parents[2]


def reply_cases():
    bank = practice_bank()
    for case in bank['cases']:
        if case['objective'] == 'reply_access':
            position, context = case_position(case, bank)
            yield {'question_id': case['id'], 'objective': 'reply_access', 'board': list(position.board),
                   'turn': position.turn, 'context': context, 'target': case['target'],
                   'rubric_version': 'reply-access-v1'}


def test_all_legal_comparison_pairs_are_graded_by_complete_reply_sets():
    count = 0
    for question in reply_cases():
        count += 1
        options = reply_options(tuple(question['board']), question['turn'])
        for move in options:
            for alternative in options:
                result = grade_practice(question, move, None, alternative)
                assert result['legal'] and result['alternative_legal']
                assert result['move_matches_goal'] == (question['target'] not in options[move])
                assert result['alternative_matches'] == (question['target'] in options[alternative])
                assert not result['reason_reviewed']
                blocking, allowing = result['blocking_frame'], result['allowing_frame']
                for frame, replies in ((blocking, result['replies_after_blocking']),
                                       (allowing, result['replies_after_allowing'])):
                    assert replies == list(legal_moves(tuple(frame['board']), opponent(question['turn'])))
                assert question['target'] not in result['replies_after_blocking']
                assert question['target'] in result['replies_after_allowing']
                witness = result['witness']
                assert witness['coordinate'] == question['target']
                assert witness['available_after'] == allowing['coordinate']
                assert witness['blocked_after'] == blocking['coordinate']
                ray = witness['capture_line']
                available, blocked = allowing['board'], blocking['board']
                after = apply_move(tuple(available), opponent(question['turn']), question['target'])
                for coordinate in ray[1:-1]:
                    row, col = square(coordinate)
                    assert available[row][col] == question['turn']
                    assert after[row][col] == opponent(question['turn'])
                assert witness['changes']
                for change in witness['changes']:
                    row, col = square(change['coordinate'])
                    assert change['available'] == available[row][col] and change['blocked'] == blocked[row][col]
                if result['added_reply']:
                    target = result['added_reply']['coordinate']
                    assert target in result['replies_after_blocking'] and target not in result['replies_after_allowing']
        result = grade_practice(question, 'd4', None, 'd4')
        assert not result['legal'] and not result['alternative_legal']
        with pytest.raises(AppError) as error:
            grade_practice(question, next(iter(options)), None)
        assert error.value.code == 'PRACTICE_PAIR'
    assert count == 4


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
