import json
import re
from functools import cache
from pathlib import Path

import pytest

from nemothello.coaching import enrich_evidence, position_facts
from nemothello.edax import Edax
from nemothello.rules import apply_move, legal_moves

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / 'fixtures'
FULL = (1 << 64) - 1
DIRECTIONS = [(row, col) for row in (-1, 0, 1) for col in (-1, 0, 1) if row or col]


def encode(board):
    cells = ''.join(board)
    return tuple(sum(1 << index for index, cell in enumerate(cells) if cell == color)
                 for color in ('X', 'O'))


def decode(black, white):
    cells = ''.join('X' if black & (1 << index) else 'O' if white & (1 << index) else '.'
                    for index in range(64))
    return tuple(cells[index:index + 8] for index in range(0, 64, 8))


def choices(player, other):
    empty = FULL ^ (player | other)
    result = []
    while empty:
        move = empty & -empty
        empty ^= move
        row, col = divmod(move.bit_length() - 1, 8)
        captured = 0
        for dy, dx in DIRECTIONS:
            y, x, ray = row + dy, col + dx, 0
            while 0 <= y < 8 and 0 <= x < 8:
                bit = 1 << (y * 8 + x)
                if other & bit:
                    ray |= bit
                else:
                    if player & bit:
                        captured |= ray
                    break
                y, x = y + dy, x + dx
        if captured:
            result.append((move, captured))
    return result


@cache
def solve(player, other):
    moves = choices(player, other)
    if moves:
        return max(-solve(other ^ captured, player | captured | move) for move, captured in moves)
    if choices(other, player):
        return -solve(other, player)
    difference = player.bit_count() - other.bit_count()
    empty = 64 - (player | other).bit_count()
    return difference + (empty if difference > 0 else -empty if difference < 0 else 0)


def recorded_positions():
    review = json.loads((FIXTURES / 'review-native-positions.json').read_text())['review']
    forced = json.loads((FIXTURES / 'forced-move-native.json').read_text())['game']
    for game in (review, forced):
        black, white = encode(game['initial_board'])
        for event in game['history']:
            actor = event['actor']
            player, other = (black, white) if actor == 'X' else (white, black)
            moves = choices(player, other)
            board = decode(black, white)
            expected = {f'{chr(97 + (move.bit_length() - 1) % 8)}{(move.bit_length() - 1) // 8 + 1}'
                        for move, _ in moves}
            assert expected == set(legal_moves(board, actor))
            yield game, event, board, player, other
            if event['kind'] == 'pass':
                assert not moves and choices(other, player)
                continue
            move = 1 << ((int(event['coordinate'][1]) - 1) * 8 + ord(event['coordinate'][0]) - 97)
            captured = next(captured for candidate, captured in moves if candidate == move)
            player, other = player | captured | move, other ^ captured
            black, white = (player, other) if actor == 'X' else (other, player)
            assert decode(black, white) == apply_move(board, actor, event['coordinate'])
        assert black.bit_count() == game['result']['black_count']
        assert white.bit_count() == game['result']['white_count']
        assert not choices(black, white) and not choices(white, black)
        difference = black.bit_count() - white.bit_count()
        empty = 64 - (black | white).bit_count()
        assert empty > 0
        assert solve(black, white) == difference + (empty if difference > 0 else -empty if difference < 0 else 0)


def test_exact_native_scores_match_an_independent_complete_solver_and_keep_actual_counts():
    executable, weights = ROOT / 'deploy/edax/edax', ROOT / 'deploy/edax/eval.dat'
    if not executable.is_file() or not weights.is_file():
        pytest.skip('Native Edax and eval.dat are required')
    engine = Edax(executable, weights, '4.6', 4)
    checked, passes, actors = 0, 0, set()
    try:
        for game, event, board, player, other in recorded_positions():
            empties = 64 - (player | other).bit_count()
            if empties > 8:
                continue
            if event['kind'] == 'pass':
                passes += 1
                assert solve(player, other) == -solve(other, player)
                continue
            checked += 1
            actors.add(event['actor'])
            analysis = engine.analyze(board, event['actor'])
            assert analysis['score_kind'] == 'exact'
            assert analysis['terminal_score_rule'] == 'winner_takes_empties'
            for candidate in analysis['candidates']:
                move = 1 << ((int(candidate['coordinate'][1]) - 1) * 8 + ord(candidate['coordinate'][0]) - 97)
                captured = next(captured for possible, captured in choices(player, other) if possible == move)
                assert candidate['score_kind'] == 'exact'
                assert candidate['score'] == -solve(other ^ captured, player | captured | move)
            if empties == 1:
                score = next(candidate['score'] for candidate in analysis['candidates']
                             if candidate['coordinate'] == event['coordinate'])
                result = game['result']
                raw = result['black_count'] - result['white_count']
                remaining = 64 - result['black_count'] - result['white_count']
                expected = raw + (remaining if raw > 0 else -remaining if raw < 0 else 0)
                assert score == expected * (1 if event['actor'] == 'X' else -1)
    finally:
        engine.close()
        solve.cache_clear()
    assert checked >= 12 and passes > 0 and actors == {'X', 'O'}


def test_exact_review_facts_describe_the_searched_finish_in_words():
    review = json.loads((FIXTURES / 'review-native-positions.json').read_text())['review']
    item = enrich_evidence(next(item for item in review['evidence'] if item['revision'] == 47))
    facts, _, _ = position_facts(item)
    text = next(fact['text'] for fact in facts if fact['id'] == 'p47:endgame')
    assert 'searched to the end of the game' in text and re.search(r'you finish (ahead|behind|level)', text)
    assert not re.search(r'\d', re.sub(r'[a-h][1-8]', '', text))
