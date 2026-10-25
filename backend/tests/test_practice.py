import json
from pathlib import Path

import pytest

from nemothello.edax import PV_MOVE, RESULT_LINE, Edax
from nemothello.practice import (
    answer_lines,
    case_position,
    grade_practice,
    position_key,
    practice_bank,
    practice_position,
)
from nemothello.reply_practice import reply_options
from nemothello.rules import apply_move, legal_moves, opponent, square

ROOT = Path(__file__).resolve().parents[2]


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
        assert len(position.moves) >= 3
        if case['objective'] == 'reply_access':
            options = reply_options(position.board, position.turn)
            assert case['target'] not in options
            assert any(case['target'] in replies for replies in options.values())
            assert any(case['target'] not in replies for replies in options.values())
        else:
            lines = answer_lines(position, context, case['objective'])
            assert lines
            if case['objective'] != 'reply':
                assert len({line[0] for line in lines}) < len(position.moves)
        counts[case['objective']] = counts.get(case['objective'], 0) + 1
    assert counts == {'anchor': 4, 'recapture': 4, 'reply': 4, 'reply_access': 4}


def test_grading_accepts_every_matching_capture_and_rejects_wrong_anchors():
    bank = practice_bank()
    for case in bank['cases']:
        if case['objective'] == 'reply_access':
            continue
        position, context = case_position(case, bank)
        question = {'question_id': case['id'], 'objective': case['objective'], 'board': list(position.board),
                    'turn': position.turn, 'context': context, 'rubric_version': bank['rubric_version']}
        lines = answer_lines(position, context, case['objective'])
        pairs = {(line[0], line[-1]) for line in lines}
        own = [f'{chr(97+c)}{r+1}' for r in range(8) for c in range(8) if position.board[r][c] == position.turn]
        for move in position.moves:
            for anchor in own:
                feedback = grade_practice(question, move, anchor)
                assert feedback['legal']
                assert feedback['move_matches_goal'] == any(line[0] == move for line in lines)
                assert feedback['anchor_matches'] == ((move, anchor) in pairs)
                assert feedback['reason_reviewed'] is False
                ray = feedback['capture_line']
                after = apply_move(position.board, position.turn, ray[0])
                for coordinate in ray[1:-1]:
                    r, c = square(coordinate)
                    assert position.board[r][c] == opponent(position.turn) and after[r][c] == position.turn
        occupied = own[0]
        assert not grade_practice(question, occupied, occupied)['legal']


def test_native_edax_checks_legal_moves_in_every_frozen_practice_position():
    executable, weights = ROOT / 'deploy/edax/edax', ROOT / 'deploy/edax/eval.dat'
    if not executable.is_file() or not weights.is_file():
        pytest.skip('Native Edax and eval.dat are required')
    engine = Edax(executable, weights, '4.6', 1)
    bank = practice_bank()
    try:
        engine._start()
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
    finally:
        engine.close()
