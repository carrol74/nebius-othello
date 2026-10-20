import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from nemothello.edax import Edax
from nemothello.errors import AppError
from nemothello.search_audit import audit_search, search_observation, summarize_searches

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / 'fixtures'


def source_packet():
    review = json.loads((FIXTURES / 'review-native-positions.json').read_text())['review']
    forced = json.loads((FIXTURES / 'forced-move-native.json').read_text())['evidence']
    ordinary = json.loads((FIXTURES / 'ordinary-move-native.json').read_text())['evidence']
    cases = [item for item in review['evidence'] if item['revision'] in (0, 2, 20)] + [forced, ordinary]
    return {'protocol': 'decision-teaching-v1',
            'cases': [{'case_number': index + 1, 'engine_evidence': item} for index, item in enumerate(cases)]}


def engines(levels=(8, 10)):
    executable, weights = ROOT / 'deploy/edax/edax', ROOT / 'deploy/edax/eval.dat'
    if not executable.is_file() or not weights.is_file():
        pytest.skip('Native Edax and eval.dat are required')
    return [Edax(executable, weights, '4.6', level) for level in levels]


@pytest.fixture(scope='module')
def native_audit(tmp_path_factory):
    packet = source_packet()
    original = deepcopy(packet)
    directory = tmp_path_factory.mktemp('search-audit')
    native = engines()
    report = audit_search(packet, native, directory / 'audit.json')
    assert packet == original
    assert all(engine.process is None for engine in native)
    return report, directory, packet


def test_native_deepening_records_ranking_changes_without_rewriting_source_evidence(native_audit):
    report, directory, packet = native_audit
    assert report == json.loads((directory / 'audit.json').read_text())
    assert report['status'] == 'completed'
    assert report['summary']['ranking_changed'] > 0
    assert report['summary']['position_sign_changed'] > 0
    assert report['summary']['exact_disagreements'] == 0
    assert len(report['cases']) == len(packet['cases']) == 5
    for case, source in zip(report['cases'], packet['cases']):
        item = source['engine_evidence']
        assert case['source']['analysis'] == item['analysis']
        observations = [case['source'], *case['searches']]
        assert case['summary'] == summarize_searches(observations)
        assert [entry['analysis']['settings']['level'] for entry in case['searches']] == [8, 10]
        assert all('raw_output' in entry['analysis'] for entry in case['searches'])
        for entry in observations:
            assert entry['analysis']['board'] == item['analysis']['board']
            assert entry['analysis']['turn'] == entry['analysis']['score_perspective'] == item['actor']
            scores = {candidate['coordinate']: candidate['score'] for candidate in entry['analysis']['candidates']}
            assert set(entry['best_moves']) == {move for move, score in scores.items() if score == max(scores.values())}
            assert entry['original_pair_margin'] == scores[item['recommended_move']] - scores[item['actual_move']]
            assert entry['evaluated_score_loss'] == max(scores.values()) - scores[item['actual_move']]
        if case['source']['score_kind'] == 'exact':
            assert case['summary']['status'] == 'exact_agreement'
            assert case['summary']['exact_score_consistency'] is True
        else:
            assert case['summary']['status'] in ('ranking_changed', 'consistent_within_tested_searches')


def test_corrupt_perspective_or_exact_scores_cannot_be_accepted_as_agreement(native_audit):
    report, _, packet = native_audit
    item = packet['cases'][0]['engine_evidence']
    analysis = deepcopy(item['analysis'])
    analysis['score_perspective'] = 'O'
    with pytest.raises(ValueError, match='same player perspective'):
        search_observation(item, analysis)
    exact = next(case for case in report['cases'] if case['summary']['status'] == 'exact_agreement')
    corrupted = deepcopy(exact['searches'][0])
    corrupted['analysis']['candidates'][0]['score'] += 1
    summary = summarize_searches([exact['source'], corrupted])
    assert summary['status'] == 'exact_disagreement'
    assert summary['exact_score_consistency'] is False


def test_invalid_selection_and_existing_report_fail_before_starting_a_process(native_audit, tmp_path):
    _, directory, packet = native_audit
    native = engines()
    existing = directory / 'audit.json'
    before = existing.read_bytes()
    with pytest.raises(ValueError, match='already exists'):
        audit_search(packet, native, existing)
    assert existing.read_bytes() == before
    duplicate = deepcopy(packet)
    duplicate['cases'][1]['case_number'] = duplicate['cases'][0]['case_number']
    with pytest.raises(ValueError, match='unique case numbers'):
        audit_search(duplicate, native, tmp_path / 'duplicate.json')
    with pytest.raises(ValueError, match='distinct increasing'):
        audit_search(packet, native[::-1], tmp_path / 'reversed.json')
    assert all(engine.process is None for engine in native)


def test_a_real_native_start_failure_preserves_completed_searches_and_closes_processes(tmp_path):
    native = engines()
    native[1] = Edax(tmp_path / 'missing-edax', ROOT / 'deploy/edax/eval.dat', '4.6', 10)
    packet = source_packet()
    packet['cases'] = packet['cases'][:1]
    output = tmp_path / 'failed.json'
    with pytest.raises(AppError) as error:
        audit_search(packet, native, output)
    assert error.value.code == 'EDAX_FAILED'
    saved = json.loads(output.read_text())
    assert saved['status'] == 'failed'
    assert len(saved['cases'][0]['searches']) == 1
    assert saved['cases'][0]['searches'][0]['analysis']['settings']['level'] == 8
    assert saved['cases'][0]['summary'] is None
    assert all(engine.process is None for engine in native)


def test_cli_audits_only_preselected_real_cases_and_preserves_the_input(native_audit, tmp_path):
    _, _, packet = native_audit
    packet = deepcopy(packet)
    selected = packet['cases'][1]['engine_evidence']
    selected.update(is_played=False, actual_move=selected['recommended_move'], score_loss=0)
    source, output = tmp_path / 'source.json', tmp_path / 'selected.json'
    source.write_text(json.dumps(packet))
    before = source.read_bytes()
    subprocess.run([sys.executable, str(ROOT / 'scripts/audit_teaching_search.py'),
                    '--input', str(source), '--output', str(output), '--case', '2'], check=True)
    result = json.loads(output.read_text())
    assert [case['case_number'] for case in result['cases']] == [2]
    assert result['cases'][0]['recorded_move'] is None
    assert result['cases'][0]['evaluated_move'] == selected['recommended_move']
    assert result['levels'] == [8, 10] and result['summary']['cases'] == 1
    assert source.read_bytes() == before
