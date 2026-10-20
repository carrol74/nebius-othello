import argparse
import json
import random
import secrets
from pathlib import Path

from build_practice_bank import build_bank
from nemothello.assessment import (
    allocation_schedule,
    freeze_assessment,
    grade_assessment,
)
from nemothello.edax import Edax
from nemothello.practice import practice_bank, practice_position

ROOT = Path(__file__).resolve().parents[1]


def teaching_sources():
    directory = ROOT / 'backend/tests/fixtures'
    review = json.loads((directory / 'review-native-positions.json').read_text())['review']
    forced = json.loads((directory / 'forced-move-native.json').read_text())['game']
    ordinary = json.loads((directory / 'ordinary-move-native.json').read_text())
    games = []
    for game in (review, forced):
        games.append({'moves': [event['coordinate'] for event in game['history'] if event['kind'] == 'move'],
                      'result': game['result']})
    boards = [item['analysis']['board'] for item in review['evidence']] + [ordinary['evidence']['analysis']['board']]
    moves = [event['coordinate'] for event in ordinary['history'] if event['kind'] == 'move']
    boards.extend(practice_position(moves, ply)[0].board for ply in range(len(moves) + 1))
    return games, boards


def write(path, data):
    with path.open('x') as stream:
        stream.write(json.dumps(data, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description='Prepare local teaching assessments or grade first attempts. No model API calls.')
    commands = parser.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('prepare', help='Generate four completed native Edax games and freeze separate question and answer packets')
    prepare.add_argument('--output', type=Path, required=True, help='New private local directory; do not serve or publish its answer packet')
    prepare.add_argument('--participants', type=int, default=0, help='Prepare a balanced allocation schedule; zero creates no participant records')
    prepare.add_argument('--seed', type=int, default=20261020, help='Allocation seed, fixed before enrolling participants')
    prepare.add_argument('--source-seed', type=int, help='Private source-generation seed; omit to generate and save a fresh seed in the answer packet')
    prepare.add_argument('--exclude-games', type=Path, action='append', default=[], help='Additional JSON lists of completed teaching games with moves and result; repeat for each source')
    grade = commands.add_parser('grade', help='Grade one participant\'s recorded first attempts without grading written reasons')
    grade.add_argument('--key', type=Path, required=True)
    grade.add_argument('--responses', type=Path, required=True, help='One participant only: JSON list of question_id, move, anchor or alternative, and reason')
    grade.add_argument('--output', type=Path, required=True, help='New directory for automatic scores and blinded reason packet')
    grade.add_argument('--seed', type=int, default=20261020, help='Shuffle order for blinded reason review')
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Output already exists; frozen packets must not be overwritten')
    if args.command == 'prepare':
        assignments = allocation_schedule(args.participants, args.seed)
        source_seed = args.source_seed if args.source_seed is not None else secrets.randbits(63)
        seeds = random.Random(source_seed).sample(range(1000, 1000000000), 4)
        engine = Edax(ROOT / 'deploy/edax/edax', ROOT / 'deploy/edax/eval.dat', '4.6', 1)
        try:
            bank = build_bank(seeds, engine)
        finally:
            engine.close()
        bank['source']['generation_seed'] = source_seed
        games, boards = teaching_sources()
        for path in args.exclude_games:
            games.extend(json.loads(path.read_text()))
        public, key = freeze_assessment(bank, [*practice_bank()['games'], *games], boards)
        args.output.mkdir(parents=True)
        write(args.output / 'participant-forms.json', public)
        write(args.output / 'private-answer-key.json', key)
        write(args.output / 'private-allocation.json', {'seed': args.seed, 'assignments': assignments})
        print(f"Frozen {len(key['cases'])} questions from {len(key['games'])} complete games; no participant answers collected")
    else:
        key = json.loads(args.key.read_text())
        result, blind = grade_assessment(key, json.loads(args.responses.read_text()), args.seed)
        args.output.mkdir(parents=True)
        write(args.output / 'private-scores.json', result)
        write(args.output / 'blinded-reasons.json', blind)
        print('Graded first choices; missing answers retained and written reasons await human review')


if __name__ == '__main__':
    main()
