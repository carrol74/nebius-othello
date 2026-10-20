import random
from collections import Counter

from nemothello.practice import (
    answer_lines,
    case_position,
    grade_practice,
    position_key,
    practice_position,
)
from nemothello.reply_practice import reply_options

OBJECTIVES = ('anchor', 'recapture', 'reply', 'reply_access')
CONDITIONS = ('recommendation_only', 'recommendation_with_verified_explanation')


def game_positions(game):
    positions = [practice_position(game['moves'], ply)[0] for ply in range(len(game['moves']) + 1)]
    if positions[-1].turn is not None or positions[-1].result() != game['result']:
        raise ValueError('Assessment sources must replay to their recorded terminal results')
    return {position_key(position.board) for position in positions}


def freeze_assessment(bank, excluded_games, excluded_boards):
    count = len(bank['games'])
    if count < 4 or count % 2:
        raise ValueError('Use an even number of at least four complete assessment games')
    excluded = {position_key(board) for board in excluded_boards}
    for game in excluded_games:
        excluded.update(game_positions(game))
    positions = [game_positions(game) for game in bank['games']]
    forms = {'form-a': [], 'form-b': []}
    private, seen = [], set()
    half = count // 2
    for case in bank['cases']:
        index = case['game_index']
        if not 0 <= index < count or case['objective'] not in OBJECTIVES:
            raise ValueError('Invalid assessment source or objective')
        if not 12 <= case['ply'] <= 44 or case['ply'] >= len(bank['games'][index]['moves']):
            raise ValueError('Assessment cases must use recorded middle-game choices at plies 12–44')
        position, context = case_position(case, bank)
        key = position_key(position.board)
        other_form = positions[half:] if index < half else positions[:half]
        if key in seen or key in excluded or any(key in boards for boards in other_form):
            raise ValueError('Assessment position overlaps teaching, practice or the other form')
        if len(position.moves) < 3:
            raise ValueError('Assessment questions need at least three legal choices')
        seen.add(key)
        question = {'question_id': f'q{len(private) + 1:03}', 'objective': case['objective'],
                    'board': list(position.board), 'turn': position.turn, 'context': context,
                    'rubric_version': 'reply-access-v1' if case['objective'] == 'reply_access' else bank['rubric_version']}
        if case['objective'] == 'reply_access':
            question['target'] = case['target']
            options = reply_options(position.board, position.turn)
            blocking = [move for move, replies in options.items() if case['target'] not in replies]
            allowing = [move for move, replies in options.items() if case['target'] in replies]
            if not blocking or not allowing or case['target'] in options:
                raise ValueError('Reply assessment needs both allowing and blocking choices')
            answers = [[move, other] for move in blocking for other in allowing]
        else:
            lines = answer_lines(position, context, case['objective'])
            if not lines or (case['objective'] != 'reply' and len({ray[0] for ray in lines}) == len(position.moves)):
                raise ValueError('Capture assessment needs a discriminating rule-verified answer')
            answers = sorted({(ray[0], ray[-1]) for ray in lines})
        form = 'form-a' if index < half else 'form-b'
        forms[form].append(question)
        private.append({'question': question, 'form': form, 'source': case,
                        'accepted_pairs': [list(pair) for pair in answers],
                        'automatic_difficulty': {'ply': case['ply'], 'legal_moves': len(position.moves),
                                                 'accepted_pairs': len(answers)}})
    expected = Counter({objective: half for objective in OBJECTIVES})
    if any(Counter(question['objective'] for question in questions) != expected for questions in forms.values()):
        raise ValueError('Each form needs one question per objective from every source game')
    instructions = {
        'capture': 'Choose a legal move and the friendly anchor at the other end of the capture. Explain the capture in your own words.',
        'reply_access': 'Choose a legal move that denies the stated opponent reply and another that permits it. Explain what changes.',
        'administration': 'Record the first choice and reason before revealing feedback. Give no recommendations during either assessment. Use the assigned form order.',
    }
    public = {'version': 'teaching-assessment-v1', 'instructions': instructions, 'forms': forms}
    grading = {'version': public['version'], 'study_status': 'not_run', 'expert_review': 'not_run',
               'form_equivalence': 'unvalidated', 'source': bank['source'], 'games': bank['games'],
               'cases': private,
               'exclusions': {'complete_games': len(excluded_games), 'additional_boards': len(excluded_boards)},
               'limits': 'Rule-verified opportunities only. Automatic difficulty descriptors do not establish equal form difficulty or learning benefit. Keep this answer packet away from participants.'}
    return public, grading


def allocation_schedule(count, seed):
    if count < 0:
        raise ValueError('Participant count cannot be negative')
    rng, assignments = random.Random(seed), []
    while len(assignments) < count:
        block = [(condition, baseline) for condition in CONDITIONS for baseline in ('form-a', 'form-b')]
        rng.shuffle(block)
        for condition, baseline in block:
            if len(assignments) == count:
                break
            assignments.append({'participant': f'p{len(assignments) + 1:03}', 'condition': condition,
                                'baseline': baseline, 'post': 'form-b' if baseline == 'form-a' else 'form-a'})
    return assignments


def grade_assessment(grading, responses, blind_seed):
    by_id = {case['question']['question_id']: case for case in grading['cases']}
    first, duplicates = {}, 0
    for response in responses:
        identifier = response['question_id']
        if identifier not in by_id:
            raise ValueError('Response does not belong to this assessment')
        if identifier in first:
            duplicates += 1
            continue
        if not isinstance(response.get('reason', ''), str):
            raise TypeError('A response reason must be text')
        first[identifier] = response
    outcomes, blind = [], []
    for identifier, case in by_id.items():
        response, question = first.get(identifier), case['question']
        correct = None
        if response is not None:
            feedback = grade_practice(question, response['move'], response.get('anchor'), response.get('alternative'))
            correct = feedback['legal'] and feedback['move_matches_goal'] and (
                feedback['alternative_legal'] and feedback['alternative_matches']
                if question['objective'] == 'reply_access' else feedback['anchor_matches'])
        outcomes.append({'question_id': identifier, 'form': case['form'], 'objective': question['objective'],
                         'answered': response is not None, 'correct': correct, 'reason_reviewed': False})
        blind.append({'question': {key: value for key, value in question.items() if key != 'question_id'},
                      'answer': None if response is None else {key: response.get(key) for key in ('move', 'anchor', 'alternative', 'reason')},
                      'review': {'reason_score': None, 'board_facts_correct': None, 'notes': None},
                      'question_id': identifier})
    random.Random(blind_seed).shuffle(blind)
    mapping = {}
    for index, case in enumerate(blind):
        identifier = f'r{index + 1:03}'
        mapping[identifier] = case.pop('question_id')
        case['review_id'] = identifier
    summaries = {}
    for form in ('form-a', 'form-b'):
        selected = [row for row in outcomes if row['form'] == form]
        correct = sum(row['correct'] is True for row in selected)
        summaries[form] = {'assigned': len(selected), 'answered': sum(row['answered'] for row in selected),
                           'correct': correct, 'missing': sum(not row['answered'] for row in selected),
                           'fraction_correct_of_assigned': correct / len(selected)}
    return {'learning_effect': 'not_estimated', 'forms': summaries, 'items': outcomes,
            'duplicate_attempts_ignored': duplicates, 'blinded_review_mapping': mapping}, {'cases': blind}
