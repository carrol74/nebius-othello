import json
from itertools import pairwise
from pathlib import Path

import pytest

from nemothello.coaching import review_context, verified_teaching_facts
from nemothello.edax import PV_MOVE, RESULT_LINE, Edax
from nemothello.rules import apply_move, legal_moves, opponent, square
from nemothello.schemas import TeachingMove
from nemothello.teaching import compare_lesson, teach_move

DIRECTORY = Path(__file__).parent / 'fixtures'


def test_native_ordinary_lesson_explains_a_disc_gained_as_a_later_capture_anchor():
    case = json.loads((DIRECTORY / 'ordinary-move-native.json').read_text())
    item = case['evidence']
    board = tuple(case['initial_board'])
    for event in case['history']:
        if event['kind'] == 'move':
            board = apply_move(board, event['actor'], event['coordinate'])
    assert list(board) == item['analysis']['board']
    comparison = compare_lesson({'evidence': [item]}, 8, 'f5')
    assert comparison == case['comparison']
    assert len(comparison['choices']) == 1
    choice = comparison['choices'][0]
    assert choice['continuation_lesson'] == {
        'kind': 'anchor', 'frame_index': 3, 'capture_line': ['e2', 'e3', 'e4', 'e5'], 'recaptured': []}
    assert choice['frames'][2]['coordinate'] == 'c6'
    fact = verified_teaching_facts(comparison, 8, comparison['actor'])[0]
    assert fact['id'] == 'p8:continuation_f5'
    assert 'disc gained at e5' in fact['text'] and 'later capture from e2' in fact['text']
    assert 'one local mechanism' in fact['text']


def test_all_native_continuation_lessons_use_verified_capture_lines_and_root_gains():
    review = json.loads((DIRECTORY / 'review-native-positions.json').read_text())['review']
    kinds = set()
    for item in review['evidence']:
        for candidate in item['analysis']['candidates']:
            choice = TeachingMove.model_validate(teach_move(item, candidate['coordinate']))
            lesson = choice.continuation_lesson
            if not lesson:
                continue
            assert choice.kind == 'line'
            kinds.add(lesson.kind)
            before, after = choice.frames[lesson.frame_index - 1:lesson.frame_index + 1]
            ray = lesson.capture_line
            assert after.coordinate == ray[0]
            assert tuple(after.board) == apply_move(tuple(before.board), after.actor, ray[0])
            for coordinate in ray[1:-1]:
                row, column = square(coordinate)
                assert before.board[row][column] == opponent(after.actor)
                assert coordinate in after.flipped
            row, column = square(ray[-1])
            assert before.board[row][column] == after.actor
            gains = {choice.coordinate, *choice.frames[1].flipped}
            if lesson.kind == 'anchor':
                assert after.actor == item['actor'] and ray[-1] in gains
                assert not lesson.recaptured
            else:
                assert after.actor == opponent(item['actor'])
                assert set(lesson.recaptured) == gains.intersection(after.flipped)
                assert bool(lesson.recaptured) == (lesson.kind == 'recapture')
    assert kinds == {'anchor', 'recapture', 'reply'}


def test_ordinary_teaching_facts_reach_questions_without_enabling_unsupported_corner_lessons():
    review = json.loads((DIRECTORY / 'review-native-positions.json').read_text())['review']
    item = next(item for item in review['evidence'] if item['revision'] == 0)
    comparison = compare_lesson(review, 0, item['actual_move'])
    context = review_context({**review, 'teaching_comparison': comparison}, 'Why this move?', 0)
    position = context['positions'][0]
    assert any(fact['id'].startswith('p0:continuation_') for fact in position['facts'])
    assert 'corners' not in position['allowed_lessons']


def test_native_edax_independently_accepts_the_ordinary_teaching_continuation():
    root = Path(__file__).resolve().parents[2]
    executable, weights = root / 'deploy/edax/edax', root / 'deploy/edax/eval.dat'
    if not executable.is_file() or not weights.is_file():
        pytest.skip('Native Edax and eval.dat are required')
    case = json.loads((DIRECTORY / 'ordinary-move-native.json').read_text())
    frames = case['comparison']['choices'][0]['frames']
    engine = Edax(executable, weights, '4.6', 1)
    try:
        engine._start()
        for before, after in pairwise(frames):
            engine._exchange(f"setboard {''.join(before['board'])} {before['turn']}")
            output = engine._exchange('hint 64')
            moves = set()
            for line in output.splitlines():
                match = RESULT_LINE.match(line)
                if match and not match.group(3):
                    pv = PV_MOVE.findall(match.group(5))
                    if pv and pv[0].lower() != 'pa':
                        moves.add(pv[0].lower())
            assert moves == set(legal_moves(tuple(before['board']), before['turn']))
            assert after['coordinate'] in moves
    finally:
        engine.close()
