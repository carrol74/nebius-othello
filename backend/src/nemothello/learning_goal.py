from nemothello.board_features import CORNERS
from nemothello.rules import Position


def learning_goal(comparison):
    reason = comparison["reason"]
    if not reason or reason["kind"] not in ("corner_contrast", "reply_contrast", "reply_consequence"):
        return None
    consequence = None
    if reason["kind"] == "reply_consequence":
        consequence = comparison["decision_contrast"]["consequence"]
        opportunity, prefix = consequence["opportunity"], [consequence["reply"]]
    elif reason["kind"] == "corner_contrast":
        witness = comparison["insight"]["witness"]
        opportunity, prefix = witness["opportunity"], witness["prefix"]
    else:
        contrast = comparison["decision_contrast"]
        opportunity, prefix = contrast["removed_reply"] or contrast["added_reply"], []
    human = comparison["actor"]
    # Replay the shared moves to learn whether the capturing side moves right after them
    position, _ = Position(tuple(comparison["choices"][0]["frames"][0]["board"]), human).play(opportunity["available_after"])
    for move in prefix:
        if move != "pass":
            position, _ = position.play(move)

    def owner(cell):
        return "empty" if cell == "." else "yours" if cell == human else "opponent's"

    return {
        "fact_id": reason["fact"],
        "available_move": opportunity["available_after"],
        "alternative_move": opportunity["blocked_after"],
        "reply": opportunity["coordinate"],
        "anchor": opportunity["capture_line"][-1],
        "flipped": opportunity["capture_line"][1:-1],
        "immediate": position.turn == opportunity["actor"],
        "actor": "you" if opportunity["actor"] == human else "opponent",
        "after_same_moves": prefix,
        "changes": [{"square": change["coordinate"], "available": owner(change["available"]),
                     "alternative": owner(change["blocked"])} for change in opportunity["changes"]
                    if not consequence or change["coordinate"] == consequence["retained_disc"]],
        **({"consequence": consequence} if consequence else {}),
        "scope": "A verified local opportunity, not proof of the full search ranking or game result. "
                 "The shared moves must happen first; the capture still needs its actor's turn.",
    }


def explanation_problems(explanation, goal):
    if explanation is None:
        return ["Use explanation.changed_square to teach the learning_goal"]
    if explanation.changed_square not in {change["square"] for change in goal["changes"]}:
        return ["explanation.changed_square must select a verified square from learning_goal.changes"]
    return []


def mechanism_text(changed_square, goal, language):
    change = next(item for item in goal["changes"] if item["square"] == changed_square)
    cell, target, anchor = change["square"], goal["reply"], goal["anchor"]
    move, alternative = goal["available_move"], goal["alternative_move"]
    consequence = goal.get("consequence")
    if consequence:
        reply = consequence["reply"]
        if language == "Simplified Chinese":
            area = (f"{consequence['axis_value']} 列" if consequence["axis"] == "file" else
                    f"与 {consequence['actual_moves'][0]} 相同的一行")
            return (f"下 {alternative}、对手接 {reply} 后，你只能在{area}落子。"
                    f"{move} 保留了 {cell} 的对手棋子；同样接 {reply} 后，你还能下 {target}，借 {anchor} 夹住它。"
                    "留着能被你夹住的对手棋子，也是在给自己保留落点。")
        area = (f"the {consequence['axis_value']}-file" if consequence["axis"] == "file" else
                f"the same row as {consequence['actual_moves'][0]}")
        return (f"After {alternative} and the opponent's {reply}, all your legal moves lie on {area}. "
                f"Playing {move} keeps the opponent disc on {cell}; after the same reply, you can play {target}, "
                f"using {anchor} to capture it. Keeping an opponent disc can give you a way out; flipping it early closes that route.")
    # The shared moves start with the opponent's reply, then alternate
    prefix, flipped = goal["after_same_moves"], goal["flipped"]
    if language == "Simplified Chinese":
        actor, victim = ("你", "对手") if goal["actor"] == "you" else ("对手", "你")
        steps = [f"你下 {move}"] + [("对手" if index % 2 == 0 else "你") + ("停一手" if step == "pass" else f"下 {step}")
                                    for index, step in enumerate(prefix)]
        when = (f"{actor}可以下" if goal["immediate"] else
                f"轮到{victim}下；如果{victim}不挡住，{actor}下一步就可以下")
        text = (f"{'、'.join(steps)}{'后' if prefix[-1:] == ['pass'] else ' 后'}，{when} {target}，"
                f"借 {anchor} 的棋子把中间{victim}的 {'、'.join(flipped)} 翻过来。")
        if target in CORNERS:
            text += f"{target} 是角，角上的棋子不会再被翻回。"
        if alternative == target:
            return text + f"如果改下 {alternative}，就先占住了这个格子，{actor}不能再下这里。"
        instead = f"如果改下 {alternative}" + ("，双方再走同样的几步" if prefix else "") + "，"
        if cell == target:
            return text + instead + f"{target} 已经有棋子，{actor}不能在这里落子。"
        state = {"empty": "是空格", "yours": "是你的棋子", "opponent's": "是对手的棋子"}[change["alternative"]]
        return text + instead + f"{cell} {state}，这条线就夹不成了。"
    actor, victim, first = (("you", "the opponent's", "the opponent moves first; unless the opponent blocks it, you")
                            if goal["actor"] == "you" else
                            ("the opponent", "your", "you move first; unless you block it, the opponent"))
    steps = [f"you play {move}"] + [(("the opponent passes" if step == "pass" else f"the opponent plays {step}")
                                     if index % 2 == 0 else ("you pass" if step == "pass" else f"you play {step}"))
                                    for index, step in enumerate(prefix)]
    when = f"{actor} can play" if goal["immediate"] else f"{first} can then play"
    text = (f"After {', '.join(steps[:-1]) + ' and ' + steps[-1] if prefix else steps[0]}, {when} {target}, "
            f"using the disc on {anchor} to flip {victim} {'disc' if len(flipped) == 1 else 'discs'} on {', '.join(flipped)}.")
    if target in CORNERS:
        text += f" {target} is a corner, and a disc there can never be flipped back."
    if alternative == target:
        return text + f" If you play {alternative} instead, you take that square first."
    instead = f" If you play {alternative} instead" + (" and the same moves follow" if prefix else "") + ", "
    if cell == target:
        return text + instead + f"{target} is already occupied, so {actor} cannot play there."
    state = {"empty": "is empty", "yours": "holds your disc", "opponent's": "holds the opponent's disc"}[change["alternative"]]
    return text + instead + f"{cell} {state}, so this capture is not possible."
