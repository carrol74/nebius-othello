import json
from pathlib import Path

from nemothello.decision import assess_decision
from nemothello.schemas import Analysis


def search_observation(item, analysis):
    Analysis.model_validate(analysis)
    if (analysis['board'] != item['analysis']['board'] or analysis['turn'] != item['actor']
            or analysis['score_perspective'] != item['actor']):
        raise ValueError('Every search must analyze the same board from the same player perspective')
    assessed = assess_decision({**item, 'analysis': analysis}, item['actual_move'])
    if analysis['recommended_move'] not in assessed['best_moves']:
        raise ValueError('A search recommendation must have the highest actual candidate score')
    scores = {candidate['coordinate']: candidate['score'] for candidate in analysis['candidates']}
    return {'analysis': analysis, 'best_moves': assessed['best_moves'],
            'evaluated_move_status': assessed['status'], 'evaluated_score_loss': assessed['score_loss'],
            'position_estimate': assessed['position'], 'score_kind': assessed['score_kind'],
            'original_pair_margin': scores[item['recommended_move']] - scores[item['actual_move']]}


def summarize_searches(observations):
    best_sets = [set(entry['best_moves']) for entry in observations]
    exact = [entry for entry in observations if entry['score_kind'] == 'exact']
    exact_vectors = [{candidate['coordinate']: candidate['score'] for candidate in entry['analysis']['candidates']}
                     for entry in exact]
    exact_consistency = None if len(exact) < 2 else all(vector == exact_vectors[0] for vector in exact_vectors)
    consistent = all(moves == best_sets[0] for moves in best_sets)
    return {
        'status': 'exact_disagreement' if exact_consistency is False else
                  'exact_agreement' if len(exact) == len(observations) else
                  'consistent_within_tested_searches' if consistent else 'ranking_changed',
        'best_set_consistent': consistent,
        'common_best_moves': sorted(set.intersection(*best_sets)),
        'evaluated_assessment_consistent': len({entry['evaluated_move_status'] for entry in observations}) == 1,
        'position_sign_consistent': len({entry['position_estimate'] for entry in observations}) == 1,
        'original_pair_strictly_higher_in_every_search': all(entry['original_pair_margin'] > 0 for entry in observations),
        'exact_score_consistency': exact_consistency,
        'source_minimum_depth': min(candidate['depth'] for candidate in observations[0]['analysis']['candidates']),
        'largest_minimum_depth': max(min(candidate['depth'] for candidate in entry['analysis']['candidates'])
                                     for entry in observations),
    }


def audit_search(packet, engines, output: Path):
    if output.exists():
        raise ValueError('Output already exists; preserve previous search evidence')
    levels = [engine.level for engine in engines]
    if len(levels) < 2 or levels != sorted(set(levels)):
        raise ValueError('Use at least two distinct increasing native search levels')
    cases = packet['cases']
    if not cases or len({case['case_number'] for case in cases}) != len(cases):
        raise ValueError('Use a nonempty evidence packet with unique case numbers')
    for case in cases:
        item = case['engine_evidence']
        source = search_observation(item, item['analysis'])
        if item['recommended_move'] not in source['best_moves']:
            raise ValueError('The original recommendation must match the original search scores')
    report = {'protocol': 'teaching-search-audit-v1', 'status': 'running', 'levels': levels,
              'cases': [], 'limits': 'Agreement in these finite searches does not prove optimal midgame play, explain a full score gap, or establish learning benefit. Source evidence is preserved; no application scores are overwritten.'}
    output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        output.write_text(json.dumps(report, indent=2) + '\n')

    try:
        save()
        for case in cases:
            item = case['engine_evidence']
            entry = {'case_number': case['case_number'], 'revision': item['revision'],
                     'actor': item['actor'], 'evaluated_move': item['actual_move'],
                     'recorded_move': item['actual_move'] if item.get('is_played', True) else None,
                     'original_recommendation': item['recommended_move'],
                     'source': search_observation(item, item['analysis']), 'searches': [], 'summary': None}
            report['cases'].append(entry)
            save()
            for engine in engines:
                analysis = engine.analyze(tuple(item['analysis']['board']), item['actor'])
                entry['searches'].append(search_observation(item, analysis))
                save()
            entry['summary'] = summarize_searches([entry['source'], *entry['searches']])
            save()
        report['status'] = 'requires_investigation' if any(
            case['summary']['exact_score_consistency'] is False for case in report['cases']) else 'completed'
        report['summary'] = {'cases': len(cases),
                             'ranking_changed': sum(not case['summary']['best_set_consistent'] for case in report['cases']),
                             'evaluated_assessment_changed': sum(not case['summary']['evaluated_assessment_consistent'] for case in report['cases']),
                             'position_sign_changed': sum(not case['summary']['position_sign_consistent'] for case in report['cases']),
                             'exact_disagreements': sum(case['summary']['exact_score_consistency'] is False for case in report['cases'])}
        return report
    except Exception as exc:
        report.update(status='failed', error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        for engine in engines:
            engine.close()
        save()
