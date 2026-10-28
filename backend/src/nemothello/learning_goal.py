import re


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

    def owner(cell):
        return "empty" if cell == "." else "yours" if cell == human else "opponent's"

    return {
        "fact_id": reason["fact"],
        "available_move": opportunity["available_after"],
        "alternative_move": opportunity["blocked_after"],
        "reply": opportunity["coordinate"],
        "anchor": opportunity["capture_line"][-1],
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
        return ["Use explanation.changed_square and explanation.next_time to teach the learning_goal"]
    problems = []
    if explanation.changed_square not in {change["square"] for change in goal["changes"]}:
        problems.append("explanation.changed_square must select a verified square from learning_goal.changes")
    question = explanation.next_time.strip()
    if not question.endswith(("?", "？")) or re.search(r"[。.!！?？]", question[:-1]):
        problems.append("explanation.next_time must be one short observation question, without a preceding assertion")
    if re.search(r"\b[a-h][1-8]\b|[{}]", question, re.IGNORECASE):
        problems.append("explanation.next_time must teach a reusable check without coordinates or count placeholders")
    return problems


def explanation_text(explanation, goal, language):
    text = mechanism_text(explanation.changed_square, goal, language)
    return text + ("" if language == "Simplified Chinese" else " ") + explanation.next_time.strip()


def mechanism_text(changed_square, goal, language, *, show_continuation=False):
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
                f"using {anchor} to capture it. Keeping an opponent disc can give you a way out; flipping it early closes that route. ")
    if language == "Simplified Chinese":
        actor = "你" if goal["actor"] == "you" else "对手"
        timing = "，经过图示应对" if goal["after_same_moves"] else ""
        if show_continuation and goal["after_same_moves"]:
            timing = "，经过 " + " → ".join(goal["after_same_moves"])
        start = f"下 {move} 后{timing}，"
        if cell == target:
            why = start + f"{target} 留空，{actor}能借 {anchor} 的棋子在这里夹击。"
        elif cell == anchor:
            why = start + f"{anchor} 的棋子为{actor}接上了从 {target} 出发的夹击线。"
        else:
            why = start + f"{actor}从 {target} 到 {anchor} 的夹击线穿过 {cell}。"
        state = {"empty": "留空", "yours": "是你的棋子", "opponent's": "是对手的棋子"}[change["alternative"]]
        effect = "落点已被占据，无法再落子" if cell == target else "这条夹击线便不成立"
        instead = f"改下 {alternative} 后{timing}，{cell} {state}，{effect}。"
        return why + instead
    actor = "you" if goal["actor"] == "you" else "the opponent"
    possessive = "your" if goal["actor"] == "you" else "the opponent's"
    timing = " and the shown continuation" if goal["after_same_moves"] else ""
    if show_continuation and goal["after_same_moves"]:
        timing = " and " + " → ".join(goal["after_same_moves"])
    start = f"After {move}{timing}, "
    if cell == target:
        why = start + f"{target} is empty, with {possessive} disc on {anchor} supporting a capture there."
    elif cell == anchor:
        why = start + f"{possessive} disc on {anchor} completes a capture line from {target}."
    else:
        why = start + f"{actor} has a capture line from {target} to {anchor} through {cell}."
    state = {"empty": "is empty", "yours": "holds your disc", "opponent's": "holds the opponent's disc"}[change["alternative"]]
    effect = "so no disc can be placed there" if cell == target else "breaking that capture line"
    instead = f"After {alternative}{timing}, {cell} {state}, {effect}."
    return " ".join((why, instead))
