import json
from itertools import pairwise
from pathlib import Path

import pytest

from nemothello.coaching import review_context
from nemothello.edax import PV_MOVE, RESULT_LINE, Edax
from nemothello.rules import apply_move, legal_moves, opponent, square
from nemothello.schemas import TeachingMove
from nemothello.teaching import compare_lesson, teach_move

DIRECTORY = Path(__file__).parent / 'fixtures'


def test_native_ordinary_lesson_stops_at_the_reply_and_names_exposed_discs():
    case = json.loads((DIRECTORY / 'ordinary-move-native.json').read_text())
    item = case['evidence']
    board = tuple(case['initial_board'])
    for event in case['history']:
        if event['kind'] == 'move':
            board = apply_move(board, event['actor'], event['coordinate'])
    assert list(board) == item['analysis']['board']
    comparison = compare_lesson({'evidence': [item]}, 8, 'f5')
    assert comparison == case['comparison']
    choice = comparison['choices'][0]
    assert [frame['coordinate'] for frame in choice['frames'][1:]] == ['f5', item['opponent_replies']['f5']] == ['f5', 'c4']
    assert choice['continuation_lesson'] is None
    assert choice['concepts']['exposed'] == ['e5']


def test_all_native_continuation_lessons_are_verified_recaptures_on_the_next_reply():
    review = json.loads((DIRECTORY / 'review-native-positions.json').read_text())['review']
    found = 0
    for item in review['evidence']:
        for candidate in item['analysis']['candidates']:
            choice = TeachingMove.model_validate(teach_move(item, candidate['coordinate']))
            if choice.kind == 'line':
                assert len(choice.frames) <= 3
            lesson = choice.continuation_lesson
            if not lesson:
                continue
            found += 1
            before, after = choice.frames[1:3]
            ray = lesson.capture_line
            assert after.coordinate == ray[0] and after.actor == opponent(item['actor'])
            assert tuple(after.board) == apply_move(tuple(before.board), after.actor, ray[0])
            for coordinate in ray[1:-1]:
                row, column = square(coordinate)
                assert before.board[row][column] == item['actor']
                assert coordinate in after.flipped
            row, column = square(ray[-1])
            assert before.board[row][column] == after.actor
            gains = {choice.coordinate, *choice.frames[1].flipped}
            assert set(lesson.recaptured) == gains.intersection(after.flipped) != set()
    assert found > 0


def test_recapture_facts_reach_questions_without_enabling_unsupported_corner_lessons():
    review = json.loads((DIRECTORY / 'review-native-positions.json').read_text())['review']
    item = next(item for item in review['evidence'] if item['revision'] == 24)
    comparison = compare_lesson(review, 24, item['actual_move'])
    context = review_context({**review, 'teaching_comparison': comparison}, 'Why this move?', 24)
    facts = {fact['id']: fact['text'] for fact in context['positions'][0]['facts']}
    assert 'flip back newly gained discs: g3' in facts['p24:continuation_g3']
    assert 'corners' not in context['positions'][0]['allowed_lessons']


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
