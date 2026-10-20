import argparse
import json
from pathlib import Path

from nemothello.edax import Edax
from nemothello.search_audit import audit_search

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description='Recheck a teaching evidence packet at multiple native Edax levels. No model API calls or application writes.')
    parser.add_argument('--input', type=Path, required=True, help='Application evidence packet from export_teaching_cases.py')
    parser.add_argument('--output', type=Path, required=True, help='New local JSON report preserving source and native search output')
    parser.add_argument('--levels', type=int, nargs='+', default=[8, 10], help='At least two distinct increasing non-selective levels between 1 and 10')
    parser.add_argument('--case', type=int, action='append', help='Case number to audit; repeat to select cases before searching')
    parser.add_argument('--executable', type=Path, default=ROOT / 'deploy/edax/edax')
    parser.add_argument('--eval-file', type=Path, default=ROOT / 'deploy/edax/eval.dat')
    parser.add_argument('--version', default='4.6')
    args = parser.parse_args()
    packet = json.loads(args.input.read_text())
    if args.case:
        if len(set(args.case)) != len(args.case):
            parser.error('Select each case only once')
        selected = [case for case in packet['cases'] if case['case_number'] in args.case]
        if {case['case_number'] for case in selected} != set(args.case):
            parser.error('Every selected case must exist in the input packet')
        packet = {**packet, 'cases': selected}
    engines = [Edax(args.executable, args.eval_file, args.version, level) for level in args.levels]
    report = audit_search(packet, engines, args.output)
    print(json.dumps({'status': report['status'], **report['summary']}))
    if report['status'] == 'requires_investigation':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
