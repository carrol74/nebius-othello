import json
from pathlib import Path

import pytest

from nemothello.coaching import verified_teaching_facts
from nemothello.edax import PV_MOVE, RESULT_LINE, Edax
from nemothello.rules import apply_move, legal_moves, opponent, square
from nemothello.schemas import TeachingComparison
from nemothello.teaching import compare_lesson

DIRECTORY = Path(__file__).parent / 'fixtures'


@pytest.fixture
def review():
    return json.loads((DIRECTORY / 'review-native-positions.json').read_text())['review']


def test_equal_reply_counts_do_not_hide_the_actual_opportunity_tradeoff(review):
    comparison = compare_lesson(review, 2, 'b6')
    contrast = comparison['decision_contrast']
    assert len(contrast['replies_after_actual']) == len(contrast['replies_after_recommended']) == 5
    assert contrast['removed_reply']['coordinate'] == 'b5'
    assert contrast['removed_reply']['capture_line'] == ['b5', 'c5', 'd5']
    assert contrast['removed_reply']['changes'] == [{'coordinate': 'c5', 'available': 'X', 'blocked': 'O'}]
    assert contrast['added_reply']['coordinate'] == 'f5'
    assert contrast['added_reply']['capture_line'] == ['f5', 'e5', 'd5']
    assert [frame['coordinate'] for frame in comparison['choices'][0]['frames']] == [None, 'b6', 'b5']
    assert [frame['coordinate'] for frame in comparison['choices'][1]['frames']] == [None, 'e6', 'f5']
    facts = verified_teaching_facts(comparison, 2, comparison['actor'])
    fact = next(fact for fact in facts if fact['id'] == 'p2:decision_contrast')
    assert 'illegal after e6' in fact['text'] and 'illegal after b6' in fact['text']
    assert 'fewer replies alone do not imply a better move' in fact['text']


def test_every_native_contrast_checks_both_boards_and_survives_switching_to_recommendation(review):
    checked = 0
    for item in review['evidence']:
        comparison = compare_lesson(review, item['revision'], item['actual_move'])
        TeachingComparison.model_validate(comparison)
        contrast = comparison['decision_contrast']
        if not contrast:
            continue
        checked += 1
        board, actor = tuple(item['analysis']['board']), item['actor']
        reversed_selection = compare_lesson(review, item['revision'], comparison['recommended_move'])
        assert reversed_selection['decision_contrast'] == contrast
        states = {move: apply_move(board, actor, move) for move in (contrast['actual_move'], contrast['recommended_move'])}
        assert contrast['replies_after_actual'] == list(legal_moves(states[contrast['actual_move']], opponent(actor)))
        assert contrast['replies_after_recommended'] == list(legal_moves(states[contrast['recommended_move']], opponent(actor)))
        actual_only = set(contrast['replies_after_actual']) - set(contrast['replies_after_recommended'])
        recommended_only = set(contrast['replies_after_recommended']) - set(contrast['replies_after_actual'])
        assert bool(contrast['removed_reply']) == bool(actual_only)
        assert bool(contrast['added_reply']) == bool(recommended_only)
        for witness in (contrast['removed_reply'], contrast['added_reply']):
            if not witness:
                continue
            available, blocked = states[witness['available_after']], states[witness['blocked_after']]
            assert witness['coordinate'] in legal_moves(available, witness['actor'])
            assert witness['coordinate'] not in legal_moves(blocked, witness['actor'])
            after = apply_move(available, witness['actor'], witness['coordinate'])
            ray = witness['capture_line']
            for coordinate in ray[1:-1]:
                row, column = square(coordinate)
                assert available[row][column] == actor and after[row][column] == witness['actor']
            row, column = square(ray[-1])
            assert available[row][column] == witness['actor']
            expected = []
            for coordinate in ray:
                row, column = square(coordinate)
                if available[row][column] != blocked[row][column]:
                    expected.append({'coordinate': coordinate, 'available': available[row][column], 'blocked': blocked[row][column]})
            assert witness['changes'] == expected and expected
    assert checked >= 3


def test_highest_rated_tied_and_forced_moves_do_not_get_a_weaker_alternative(review):
    ordinary = json.loads((DIRECTORY / 'ordinary-move-native.json').read_text())['evidence']
    forced = json.loads((DIRECTORY / 'forced-move-native.json').read_text())['evidence']
    for item in [review['evidence'][0], ordinary, forced]:
        comparison = compare_lesson({'evidence': [item]}, item['revision'], item['actual_move'])
        assert comparison['decision_contrast'] is None
        assert len(comparison['choices']) == 1


def test_native_edax_cross_checks_each_contrasted_reply_set(review):
    root = Path(__file__).resolve().parents[2]
    executable, weights = root / 'deploy/edax/edax', root / 'deploy/edax/eval.dat'
    if not executable.is_file() or not weights.is_file():
        pytest.skip('Native Edax and eval.dat are required')
    engine = Edax(executable, weights, '4.6', 1)
    try:
        engine._start()
        for item in review['evidence']:
            comparison = compare_lesson(review, item['revision'], item['actual_move'])
            contrast = comparison['decision_contrast']
            if not contrast:
                continue
            for move, expected in ((contrast['actual_move'], contrast['replies_after_actual']),
                                   (contrast['recommended_move'], contrast['replies_after_recommended'])):
                board = apply_move(tuple(item['analysis']['board']), item['actor'], move)
                engine._exchange(f"setboard {''.join(board)} {opponent(item['actor'])}")
                output = engine._exchange('hint 64')
                moves = set()
                for line in output.splitlines():
                    match = RESULT_LINE.match(line)
                    if match and not match.group(3):
                        pv = PV_MOVE.findall(match.group(5))
                        if pv and pv[0].lower() != 'pa':
                            moves.add(pv[0].lower())
                assert moves == set(expected)
    finally:
        engine.close()
