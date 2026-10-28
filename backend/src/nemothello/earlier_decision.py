from functools import cache

from nemothello.corner_proof import prove_corner
from nemothello.decision import assess_decision
from nemothello.errors import AppError
from nemothello.position_lessons import analyze_position, position_at
from nemothello.rules import apply_move, legal_moves, opponent, square


def threat_checker(defender, target):
    attacker = opponent(defender)

    @cache
    def after_choice(board):
        return prove_corner(board, defender, target)

    @cache
    def threatened(board, turn):
        row, column = square(target)
        if turn is None or board[row][column] != '.':
            return False
        if turn == attacker:
            return after_choice(board)['forced']
        moves = legal_moves(board, defender)
        if not moves:
            return after_choice(board)['forced']
        return all(after_choice(apply_move(board, defender, move))['forced'] for move in moves)

    return threatened, after_choice


def earlier_target(game, evidence, comparison):
    if not evidence.get('is_played', True):
        return None
    choice = next((choice for choice in comparison['choices'] if choice['assessment']['is_played']), None)
    if choice is None or not choice['corner_proof'] or not choice['corner_proof']['forced']:
        return None
    revision = evidence['revision']
    event = next((event for event in game['history'] if event['revision'] == revision + 1), None)
    position = position_at(game, revision)
    if (event is None or event['coordinate'] != evidence['actual_move']
            or event['actor'] != game['human_color'] or position.turn != evidence['actor']
            or list(position.board) != evidence['analysis']['board']):
        raise AppError('LESSON_CHANGED', 'Reload the position before checking earlier choices', 409)
    target = choice['corner_proof']['target']
    threatened, _ = threat_checker(game['human_color'], target)
    return target if threatened(position.board, position.turn) else None


def find_earlier_decision(game, evidence, comparison, engine, game_opponent, known=None):
    target = earlier_target(game, evidence, comparison)
    result = {'status': 'not_applicable' if target is None else 'not_found',
              'scope': 'continuous_bounded_corner_threat', 'link': None}
    if target is None:
        return result
    defender = game['human_color']
    attacker = opponent(defender)
    revision = evidence['revision']
    threatened, after_choice = threat_checker(defender, target)
    observations = []
    for event in reversed([event for event in game['history'] if event['revision'] <= revision + 1]):
        board = tuple(event['board'])
        if not threatened(board, event['turn']):
            break
        observations.append({'revision': event['revision'], 'turn': event['turn'],
                             'max_plies': 3 if event['turn'] == attacker else 4})
        before = event['revision'] - 1
        if before >= revision or event['kind'] != 'move' or event['actor'] != defender:
            continue
        position = position_at(game, before)
        defenses = [move for move in position.moves
                    if not after_choice(apply_move(position.board, defender, move))['forced']]
        if not defenses:
            continue
        earlier = (known or {}).get(before)
        if earlier is None:
            earlier = analyze_position(game, before, engine, game_opponent)
        if (earlier['actual_move'] != event['coordinate'] or earlier['actor'] != defender
                or earlier['analysis']['board'] != list(position.board)):
            raise AppError('LESSON_CHANGED', 'Reload the earlier decision before checking its connection', 409)
        assessment = assess_decision(earlier, earlier['actual_move'])
        recommended = assessment['best_moves'][0]
        if assessment['status'] != 'lower_rated' or recommended not in defenses:
            return result
        result.update(status='verified', link={
            'revision': before, 'actor': defender, 'target': target,
            'recorded_move': earlier['actual_move'], 'recommended_move': recommended,
            'evidence': {key: value for key, value in earlier.items() if key != 'comparisons'},
            'recorded_proof': after_choice(board),
            'recommended_proof': after_choice(apply_move(position.board, defender, recommended)),
            'continuity': list(reversed(observations)),
        })
        return result
    return result
