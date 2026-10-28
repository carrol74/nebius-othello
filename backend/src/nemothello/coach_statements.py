def statements(context, tool_facts=()):
    zh = context['language'] == 'Simplified Chinese'
    result = {}
    for position in context['positions']:
        for key, value in position['values'].items():
            parts = key.split('.')
            if len(parts) == 2:
                result[key] = f'这里你有 {value} 个合法落点' if zh else f'You have {value} legal moves here'
                continue
            _, move, metric = parts
            en = {
                'replies': f'After {move}, the opponent has {value} legal replies',
                'flips': f'Playing {move} flips {value} discs',
                'exposed': f'{move} flips {value} interior discs that touch an empty square afterward',
                'safe_replies': f'After {move}, {value} opponent replies avoid opening a new corner for you',
                'stable_gained': f'{move} makes {value} additional discs permanently yours',
                'region': f'{move} lies in a region of {value} empty squares before the move',
            }
            cn = {
                'replies': f'下 {move} 后，对手有 {value} 个合法落点',
                'flips': f'下 {move} 会翻转 {value} 颗棋子',
                'exposed': f'{move} 翻转的棋子中，有 {value} 颗内部棋子随后挨着空格',
                'safe_replies': f'下 {move} 后，对手有 {value} 种应对不会为你开放新的角落',
                'stable_gained': f'{move} 让你新增 {value} 颗不会再被翻转的棋子',
                'region': f'落子前，{move} 所在的连通空地有 {value} 个空格',
            }
            if metric == 'corner_replies':
                squares = '、'.join(value) if zh else ', '.join(value)
                result[key] = f'下 {move} 后，对手可以占据 {squares}' if zh else f'After {move}, the opponent can take {squares}'
            else:
                result[key] = (cn if zh else en)[metric]
    summary = context['summary_values']
    for key, value in summary.items():
        en = {'hints.shown': f'Hints were displayed on {value} turns',
              'hints.adopted': f'You followed a displayed hint on {value} turns',
              'result.black': f'Black finished with {value} discs',
              'result.white': f'White finished with {value} discs'}
        cn = {'hints.shown': f'对局中有 {value} 个回合显示过提示',
              'hints.adopted': f'你在 {value} 个回合采用了已显示的提示',
              'result.black': f'终局黑棋有 {value} 颗', 'result.white': f'终局白棋有 {value} 颗'}
        result[key] = (cn if zh else en)[key]
    for fact in tool_facts:
        frames = fact.get('frames', [])
        steps = [frame for frame in frames[1:] if frame['coordinate'] != 'pass']
        human = frames[0]['turn'] if frames else None
        for key, value in fact['values'].items():
            metric = key.split('.')[-1]
            if metric in ('flips', 'flipped', 'exposed'):
                step = steps[int(key.split('.')[1][1:]) - 1]
                actor = ('你' if step['actor'] == human else '对手') if zh else ('You' if step['actor'] == human else 'The opponent')
                move = step['coordinate']
                verb = 'play' if step['actor'] == human else 'plays'
                if metric == 'flipped':
                    squares = '、'.join(value) if zh else ', '.join(value)
                    text = f'{actor}下 {move}，翻转 {squares}' if zh else f'{actor} {verb} {move}, flipping {squares}'
                elif metric == 'flips':
                    unit = 'disc' if value == 1 else 'discs'
                    text = f'{actor}下 {move}，翻转 {value} 颗棋子' if zh else f'{actor} {verb} {move}, flipping {value} {unit}'
                else:
                    text = f'{actor}下 {move} 翻转的棋子中，{value} 颗内部棋子随后挨着空格' if zh else f'{actor} {verb} {move}, flipping {value} interior discs that touch an empty square afterward'
            elif metric in ('replies', 'corner_moves'):
                actor = ('你' if frames[-1]['turn'] == human else '对手') if zh else ('You' if frames[-1]['turn'] == human else 'The opponent')
                if metric == 'replies':
                    text = f'这段推演后，{actor}有 {value} 个合法落点' if zh else f'After this line, {actor.lower()} {"have" if frames[-1]["turn"] == human else "has"} {value} legal moves'
                else:
                    squares = '、'.join(value) if zh else ', '.join(value)
                    text = f'这段推演后，{actor}可以占据 {squares}' if zh else f'After this line, {actor.lower()} can take {squares}'
            elif metric == 'threatened':
                squares = '、'.join(value) if zh else ', '.join(value)
                move = fact['move']
                text = f'下 {move} 后，对手可以在接下来两次行动内强行占据 {squares}' if zh else f'After {move}, the opponent can force {squares} within its next two turns'
            else:
                actor = ('你' if metric == 'your_discs' else '对手') if zh else ('you' if metric == 'your_discs' else 'the opponent')
                text = f'这段推演后，{actor}有 {value} 颗棋子' if zh else f'After this line, {actor} {"have" if metric == "your_discs" else "has"} {value} discs'
            result[key] = text
    return result
