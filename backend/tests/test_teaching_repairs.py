import json
from copy import deepcopy
from pathlib import Path

import pytest

from nemothello.coach_agent import CoachTools
from nemothello.coaching import COACH_VERSION, render_plan, review_context, validate_plan
from nemothello.edax import Edax
from nemothello.errors import AppError
from nemothello.games import Games, advance
from nemothello.nemotron import Nemotron
from nemothello.opponents import EdaxOpponent
from nemothello.position_lessons import lesson_context, lesson_document, lesson_key
from nemothello.rules import apply_move, flips, legal_moves, opponent
from nemothello.schemas import PositionLesson, QuestionResult
from nemothello.storage import Store
from nemothello.tasks import Tasks

FIXTURES = Path(__file__).parent / 'fixtures'


def native_review():
    return json.loads((FIXTURES / 'review-native-positions.json').read_text())['review']


def answer(text, ids):
    return json.dumps({'topic': 'comparison', 'selections': [], 'answer': {'text': text, 'fact_ids': ids}})


@pytest.mark.parametrize('language', ['en', 'zh'])
def test_reply_count_cannot_be_relabelled_as_flips(language):
    review = native_review()
    context = review_context(review, 'What does b3 flip?', 16, language)
    tools = CoachTools(review, context)
    tools.run('play_line', json.dumps({'revision': 16, 'moves': ['b3']}))
    fact = tools.facts[0]
    assert fact['values']['t1.s1.flipped'] == ['c2']
    assert fact['values']['t1.replies'] == 10
    for text in ['After b3 you flip {t1.replies} discs.', '下 b3 会翻转 {t1.replies} 颗棋子。',
                 'After b1 you flip {t1.s1.flips} discs.', '对手下 b3 会翻转 {t1.s1.flips} 颗棋子。']:
        with pytest.raises(AppError, match='standalone statement'):
            validate_plan(answer(text, ['t1']), context, tools.facts)
    plan = validate_plan(answer('{t1.s1.flips}. {t1.replies}.', ['t1']), context, tools.facts)
    rendered = render_plan(plan, context, tools.facts)
    assert ('翻转 1 颗棋子' if language == 'zh' else 'flipping 1 disc') in rendered['answer']
    assert ('对手有 10 个合法落点' if language == 'zh' else 'the opponent has 10 legal moves') in rendered['answer']


def test_model_line_and_public_frames_replay_the_same_moves():
    review = native_review()
    item = next(item for item in review['evidence'] if item['revision'] == 0)
    context = review_context(review, 'What happens after d3?', 0)
    tools = CoachTools(review, context)
    tools.run('play_line', json.dumps({'revision': 0, 'moves': ['d3', 'e3']}))
    plan = validate_plan(answer('{t1.s2.flipped}.', ['t1']), context, tools.facts)
    rendered = render_plan(plan, context, tools.facts)
    public = QuestionResult(answer=rendered['answer'], model_id=None, usage=None,
                            answer_facts=rendered['answer_facts'])
    frames = [frame.model_dump() for frame in public.answer_facts[0].frames]
    assert [frame['coordinate'] for frame in frames[1:]] == ['d3', 'e3']
    board, actor = tuple(item['analysis']['board']), item['actor']
    for frame in frames[1:]:
        assert frame['actor'] == actor
        assert len(frame['flipped']) == len(flips(board, actor, frame['coordinate']))
        board = apply_move(board, actor, frame['coordinate'])
        assert list(board) == frame['board']
        actor = opponent(actor)


def test_model_input_uses_the_same_canonical_line_as_the_board():
    review = native_review()
    item = next(item for item in review['evidence'] if item['revision'] == 0)
    document = lesson_document({**review, 'game_id': 'native-game'}, item)
    context = review_context({**review, 'teaching_comparison': document['comparison']}, None, 0)
    line = next(fact for fact in context['positions'][0]['facts'] if fact['id'] == 'p0:line_d3')
    frames = document['comparison']['choices'][0]['frames']
    assert line['frames'] == frames
    assert [frame['coordinate'] for frame in frames[1:]] == ['d3', 'c5']
    assert 'd3, then c5' in line['text']
    assert 'e3' not in line['text']


@pytest.fixture
def runtime(tmp_path):
    root = Path(__file__).resolve().parents[2]
    executable, weights = root / 'deploy/edax/edax', root / 'deploy/edax/eval.dat'
    if not executable.is_file() or not weights.is_file():
        pytest.skip('Native Edax and eval.dat are required')
    engine = Edax(executable, weights, '4.6', 4)
    store = Store(tmp_path / 'repairs.sqlite3')
    games = Games(store, EdaxOpponent(engine), engine, 3)
    model = Nemotron('', 'https://unused.invalid/v1', '')
    game = games.new_game('X')
    review = native_review()
    for event in review['history']:
        if event['kind'] == 'move':
            advance(game, event['coordinate'])
    with store.transaction() as db:
        store.save(db, 'game', game['game_id'], 'owner', game)
    try:
        yield store, games, Tasks(store, games, model), game, review
    finally:
        engine.close()
        model.close()


def test_legacy_lesson_rebuilds_evidence_without_changing_history(runtime):
    store, games, _, game, review = runtime
    item = deepcopy(next(item for item in review['evidence'] if item['revision'] == 16))
    saved = lesson_document(lesson_context(game, item, []), item)
    saved.pop('coaching_version')
    saved.pop('language')
    saved['evidence'].pop('opponent_replies')
    saved['evidence'].pop('reply_scores')
    with store.transaction() as db:
        store.save(db, 'lesson', f"{game['game_id']}:16", 'owner', saved)
    restored = games.position_lesson('owner', game['game_id'], 16)
    PositionLesson.model_validate(restored)
    assert restored['coaching_version'] == COACH_VERSION
    assert restored['coaching_status'] == 'not_requested'
    board, actor = tuple(item['analysis']['board']), item['actor']
    for move, reply in restored['evidence']['opponent_replies'].items():
        assert reply in legal_moves(apply_move(board, actor, move), opponent(actor))
    replies = legal_moves(apply_move(board, actor, item['actual_move']), opponent(actor))
    assert item['score_loss'] > 0 and set(restored['evidence']['reply_scores']) == set(replies)
    assert store.get('game', game['game_id'], 'owner') == game
    assert store.get('lesson', f"{game['game_id']}:16", 'owner') == saved
    assert games.position_lesson('owner', game['game_id'], 16)['evidence'] == restored['evidence']


def test_languages_do_not_reuse_pending_or_completed_tasks(runtime):
    store, games, tasks, game, _ = runtime
    en = games.create_position_lesson_task('owner', game['game_id'], 'en-first', 48, language='en')
    zh = games.create_position_lesson_task('owner', game['game_id'], 'zh-first', 48, language='zh')
    assert en['task_id'] != zh['task_id']
    assert games.create_position_lesson_task('owner', game['game_id'], 'en-again', 48, language='en')['task_id'] == en['task_id']
    for language, task in [('en', en), ('zh', zh)]:
        tasks.process('owner', store.get('task', task['task_id'], 'owner'))
        result = store.get('task', task['task_id'], 'owner')
        assert result['status'] == 'succeeded', result['error']
        assert result['result']['model_id'] is None
        assert result['result']['language'] == language
        lesson = games.position_lesson('owner', game['game_id'], 48, language)
        assert lesson['task_id'] == task['task_id']
        assert store.get('lesson', lesson_key(game['game_id'], 48, language), 'owner')['language'] == language
        repeated = games.create_position_lesson_task('owner', game['game_id'], f'{language}-finished', 48, language=language)
        assert repeated['task_id'] == task['task_id']
