import type { Locale } from "./locale";
import type { ReplyOpportunity, TeachingComparison, TeachingFrame, TeachingMove } from "./types";

export function teachingNote(locale: Locale): string {
  return locale === "zh"
    ? "评分针对落子前的局面，搜索估计不代表胜率。局部推演不保证整盘结果，也不一定解释全部评分差距。"
    : "Scores refer to the position before your move; estimates are not win probabilities. Local continuations do not guarantee a game result or explain every score difference.";
}

export function teachingChoiceLabel(move: TeachingMove, locale: Locale): string {
  return move.assessment.is_played ? locale === "zh" ? "你当时下的" : "Your game move"
    : locale === "zh" ? "推荐走法" : "Recommended move";
}

export function cornerName(square: string, locale: Locale): string {
  const names: Record<string, [string, string]> = {a1:["top-left corner", "左上角"], h1:["top-right corner", "右上角"], a8:["bottom-left corner", "左下角"], h8:["bottom-right corner", "右下角"]};
  const name = names[square]?.[locale === "zh" ? 1 : 0];
  return name ? `${name} ${square}` : square;
}

export function lessonPrompt(comparison: TeachingComparison, move: TeachingMove, locale: Locale): string {
  const zh = locale === "zh";
  const other = comparison.actor === "X" ? zh ? "白方" : "White" : zh ? "黑方" : "Black";
  if (move.kind === 'corner_defense') return zh ? `下 ${move.coordinate} 后，怎样应对对手的准备，才能守住 ${move.target}？` : `After ${move.coordinate}, how can you answer the opponent's setup to defend ${move.target}?`;
  if (move.kind === "corner_forced") return zh ? `${other}准备先走 ${move.opponent_reply}，再抢${cornerName(move.target!, locale)}。现在换你防守，能挡住它吗？` : `${other} plans to play ${move.opponent_reply}, then take the ${cornerName(move.target!, locale)}. Your turn: can you stop that corner capture?`;
  if (move.kind === "corner_given") return zh ? `下 ${move.coordinate} 后，看看${cornerName(move.target!, locale)}。${other}能直接占住它吗？` : `After ${move.coordinate}, look at the ${cornerName(move.target!, locale)}. Can ${other} take it immediately?`;
  if (move.kind === "corner_taken") return zh ? `下 ${move.coordinate} 后，哪颗棋子能一直保留到终局？` : `After ${move.coordinate}, which disc will stay yours for the rest of the game?`;
  if (move.kind === "pass") return zh ? `下 ${move.coordinate} 后，该谁继续？看看对手还有没有地方能下。` : `Who moves after ${move.coordinate}? Check whether the opponent has anywhere to play.`;
  return zh ? "先替对手想一步：它会下在哪里，又会翻转哪些棋子？" : "Think one move ahead for your opponent: where might they play, and which discs would they flip?";
}

export function defenseFeedback(rootMove: string, attempted: string, target: string, locale: Locale): string {
  return locale === "zh" ? `在 ${rootMove} 的续着中，你下 ${attempted} 后，对手仍能占${cornerName(target, locale)}。这一步防守没有挡住抢角。` : `In the ${rootMove} continuation, after your ${attempted}, the opponent can still take the ${cornerName(target, locale)}. This defense does not stop the corner capture.`;
}

export function stepText(frame: TeachingFrame, locale: Locale): string {
  const zh = locale === "zh";
  const color = (actor: string | null) => actor === "X" ? zh ? "黑方" : "Black" : zh ? "白方" : "White";
  if (frame.coordinate === null) return zh ? `初始局面，轮到${color(frame.turn)}。` : `Starting position. ${color(frame.turn)} to move.`;
  if (frame.coordinate === "pass") return zh ? `${color(frame.actor)}没有合法落点，跳过回合，棋盘不变。` : `${color(frame.actor)} has no legal move and passes. The board stays unchanged.`;
  return zh ? `${color(frame.actor)}下 ${frame.coordinate}，翻转 ${frame.flipped.join("、")}。` : `${color(frame.actor)} plays ${frame.coordinate}, flipping ${frame.flipped.join(", ")}.`;
}

export function captureLineText(lines: string[][], actor: "X" | "O", locale: Locale): string | null {
  const line = lines[0];
  if (!line) return null;
  const zh = locale === "zh";
  const color = actor === "X" ? zh ? "黑方" : "Black" : zh ? "白方" : "White";
  const target = line[0], anchor = line[line.length - 1], discs = line.slice(1, -1).join(zh ? "、" : ", ");
  const sameRow = line.every((square) => square[1] === target[1]);
  const sameColumn = line.every((square) => square[0] === target[0]);
  const direction = sameRow ? zh ? `第 ${target[1]} 行` : `row ${target[1]}` : sameColumn ? zh ? `${target[0]} 列` : `column ${target[0]}` : zh ? "这条斜线" : "this diagonal";
  return zh ? `看${direction}：${anchor} 已经有一颗${color}棋子。${color}再下 ${target}，就会把中间的 ${discs} 夹住，全部翻成${color}棋子。` : `Look at ${direction}: ${color} already has a disc at ${anchor}. Playing ${target} traps ${discs} between two ${color} discs and flips them.`;
}

export function lessonText(comparison: TeachingComparison, move: TeachingMove, locale: Locale): string[] {
  const zh = locale === "zh";
  const own = comparison.actor === "X" ? zh ? "黑方" : "Black" : zh ? "白方" : "White";
  const assessment = move.assessment;
  if (assessment.status === "forced") {
    const context = zh ? `${move.coordinate} 是${own}此时唯一的合法落点，这一回合没有其他走法可以选择。`
      : `${move.coordinate} is ${own}'s only legal move here. There is no alternative to choose on this turn.`;
    return [context, ...moveConsequence(comparison, move, locale)];
  }
  const basis = assessment.score_kind === "exact" ? zh ? "精确终局分析" : "Exact endgame analysis" : zh ? "当前搜索" : "The current search";
  const context = assessment.status === "tied_best" ? zh
    ? `这一步在${basis}中并列最高评分。`
    : `This move is tied for the highest rating in ${basis.toLowerCase()}.`
    : assessment.status === "best" ? zh
      ? `这一步已是${basis}中评分最高的选择。`
      : `This move has the highest rating in ${basis.toLowerCase()}.`
      : zh ? `${basis}对 ${comparison.recommended_move} 的评分高于 ${move.coordinate}。`
        : `${basis} rates ${comparison.recommended_move} above ${move.coordinate}.`;
  const comparedTactic = !!comparison.decision_contrast || ["corner_defense", "corner_access", "shared_corner"].includes(comparison.insight.kind);
  return [context, ...(comparedTactic ? [] : moveConsequence(comparison, move, locale))];
}

export function continuationText(move: TeachingMove, locale: Locale): string | null {
  const lesson = move.continuation_lesson;
  if (!lesson) return null;
  const zh = locale === "zh";
  const ray = lesson.capture_line, anchor = ray[ray.length - 1];
  const rootActor = move.frames[1].actor;
  const own = rootActor === "X" ? zh ? "黑方" : "Black" : zh ? "白方" : "White";
  const other = rootActor === "X" ? zh ? "白方" : "White" : zh ? "黑方" : "Black";
  const reply = move.frames[2].coordinate;
  if (lesson.kind === "anchor") return zh
    ? `重点看 ${anchor}：这一手拿到的棋子，能成为下一次夹击的另一端。在这段续着中，${other}回应 ${reply} 后，${own}仍能借它反击。落子前，试着找出新拿到的哪颗棋子能接应下一手。`
    : `Focus on ${anchor}: the disc gained by this move can anchor another capture. In this continuation, after ${other} replies at ${reply}, ${own} can use it to capture again. Before playing, look for a disc your move gains that could support your next move.`;
  if (lesson.kind === "recapture") return zh
    ? `这一手刚拿到的 ${lesson.recaptured.join("、")}，对手下一步就有办法翻回去。这段变化说明，眼前多拿几颗棋子未必保得住。落子前，先检查对手能否把这些棋子夹在两端之间。`
    : `The opponent can flip back ${lesson.recaptured.join(", ")}, gained by this move, on the very next turn. This sequence shows why gaining discs now does not mean keeping them. Before playing, check whether the opponent can trap those discs between two ends.`;
  return zh
    ? `对手在 ${anchor} 的棋子是现成的夹击另一端；这手之后，它能沿图中的连线反击。轮到对手时，先找它已有的棋子，再沿中间的己方棋子看向空位，就能发现这种威胁。这是当前续着里的一个可能回应。`
    : `The opponent's disc at ${anchor} anchors a capture along the highlighted line after this move. To spot this reply, start at an opponent disc and look past your own discs toward an empty square. This is one possible reply in the displayed continuation.`;
}

function moveConsequence(comparison: TeachingComparison, move: TeachingMove, locale: Locale): string[] {
  const zh = locale === "zh";
  const other = comparison.actor === "X" ? zh ? "白方" : "White" : zh ? "黑方" : "Black";
  const own = comparison.actor === "X" ? zh ? "黑方" : "Black" : zh ? "白方" : "White";
  const target = move.target;
  if (move.kind === "corner_forced") return [
    zh ? `这条续着里，${other}先下 ${move.opponent_reply}，再占${cornerName(target!, locale)}。${move.checked_defenses.length ? `已核对${own}随后全部 ${move.checked_defenses.length} 个合法回应，仍会留下这个角。` : `${own}此时没有合法落点，必须跳过。`}` : `In this continuation, ${other} plays ${move.opponent_reply} and can then take the ${cornerName(target!, locale)}. ${move.checked_defenses.length ? `All ${move.checked_defenses.length} legal ${own} replies were checked and still leave that corner available.` : `${own} has no legal move and must pass.`}`,
  ];
  if (move.kind === "corner_given") return [
    zh ? `下完 ${move.coordinate}，${other}可以直接占${cornerName(target!, locale)}。角落棋子以后无法被翻转。` : `After ${move.coordinate}, ${other} can take the ${cornerName(target!, locale)} immediately. A corner disc cannot be flipped later.`,
  ];
  if (move.kind === "corner_taken") return [zh ? `${move.coordinate} 本身就是角落。下在这里，这颗棋子会一直保留到终局。点击演示，查看同时翻转了哪些棋子。` : `${move.coordinate} is a corner. Playing there keeps that disc safe through the end of the game. Step through to see which other discs it flips.`];
  if (move.kind === "pass") return [zh ? `下 ${move.coordinate} 后，${other}没有合法落点，必须跳过回合。${own}因此可以再下一步。点击演示，注意跳过回合时棋盘没有变化。` : `After ${move.coordinate}, ${other} has no legal move and must pass, so ${own} gets another move. In the demonstration, notice that passing does not change the board.`];
  const continuation = continuationText(move, locale);
  if (continuation) return [continuation];
  const last = move.frames.at(-1)!;
  if (last.turn === null) {
    const black = last.board.join("").split("X").length - 1;
    const white = last.board.join("").split("O").length - 1;
    return [zh ? `这条续着结束时，双方都没有合法落点，按棋子数结算：黑方 ${black}，白方 ${white}。终局比较的是棋子总数，不能只看最后一手翻了多少。` : `At the end of this continuation neither player can move: Black has ${black} discs and White has ${white}. The final total decides the result, not how many discs the last move flips.`];
  }
  return [];
}

export function replyOpportunityText(witness: ReplyOpportunity, locale: Locale): string {
  const zh = locale === "zh";
  const actor = witness.actor === "X" ? zh ? "黑方" : "Black" : zh ? "白方" : "White";
  const anchor = witness.capture_line[witness.capture_line.length - 1];
  const change = witness.changes.find((entry) => entry.coordinate === anchor) ?? witness.changes[0];
  const cell = (value: string) => value === "." ? zh ? "空位" : "empty" : value === "X" ? zh ? "黑棋" : "a Black disc" : zh ? "白棋" : "a White disc";
  const mechanism = change.coordinate === witness.coordinate
    ? zh ? "这个落点已经被占据" : "occupying the landing square"
    : change.coordinate === anchor ? zh ? "这条夹击线的另一端消失了" : "removing its anchor"
      : zh ? "这条夹击线在这里中断" : "breaking the line there";
  return zh
    ? `${witness.available_after} 后，${actor}可以走 ${witness.coordinate}；换成 ${witness.blocked_after}，这个回应不再合法。图中 ${change.coordinate} 从${cell(change.available)}变为${cell(change.blocked)}，${mechanism}。`
    : `After ${witness.available_after}, ${actor} can play ${witness.coordinate}; after ${witness.blocked_after}, that reply is illegal. In the illustrated capture line, ${change.coordinate} changes from ${cell(change.available)} to ${cell(change.blocked)}, ${mechanism}.`;
}

export function comparisonTakeaway(comparison: TeachingComparison, locale: Locale): string | null {
  const zh = locale === "zh";
  const insight = comparison.insight;
  const contrast = comparison.decision_contrast;
  if (contrast) {
    const removed = contrast.removed_reply, added = contrast.added_reply;
    const witness = removed ?? added!;
    const actor = witness.actor === "X" ? zh ? "黑方" : "Black" : zh ? "白方" : "White";
    const difference = replyOpportunityText(witness, locale);
    const tradeoff = removed && added ? zh
      ? `不过，${contrast.recommended_move} 也开放了 ${added.coordinate}：${actor}在 ${contrast.actual_move} 后原本不能下这里。`
      : `However, ${contrast.recommended_move} also opens ${added.coordinate}, which ${actor} cannot play after ${contrast.actual_move}.` : "";
    return [difference, tradeoff].filter(Boolean).join(" ");
  }
  if (insight.kind === "forced" || insight.kind === "best" || insight.kind === "search") return null;
  if (insight.kind === "equal") return comparison.choices[0].assessment.status === "tied_best" ? null
    : zh ? "这两种走法的评分相同。" : "These two moves have the same rating.";
  if (insight.kind === "shared_corner") return zh
    ? `这两种走法都会让对手拿到 ${insight.target}，光看谁能占角还分不出优劣。`
    : `Both moves let the opponent take ${insight.target}. Corner access alone does not tell us which move is better.`;
  const best = comparison.choices.find((item) => item.coordinate === insight.better_move)!;
  if (insight.kind === "corner_defense") {
    const line = insight.example ?? [];
    const setup = line[1] === 'pass' ? zh ? '对手跳过回合后' : 'after the opponent passes'
      : zh ? `对手下 ${line[1]} 后` : `after ${line[1]}`;
    const alreadyUnavailable = !best.opponent_corner_moves_after_reply.includes(insight.target!);
    const effect = alreadyUnavailable
      ? zh ? `使 ${insight.target} 继续保持不可落子` : `keep ${insight.target} unavailable`
      : zh ? `挡住随后占 ${insight.target}` : `stop the following ${insight.target} capture`;
    const example = line.length !== 3 ? '' : line[2] === 'pass'
      ? zh ? `图中${setup}，你必须跳过回合；对手随后仍不能占 ${insight.target}。`
        : `In the example, ${setup}, you must pass; the opponent still cannot take ${insight.target} on the following turn.`
      : zh ? `图中${setup}，你可以用 ${line[2]} 防守，${effect}。`
        : `In the example, ${setup}, play ${line[2]} to ${effect}.`;
    const response = insight.proof?.refutations.some((entry) => entry.defense === null)
      ? zh ? '每种回应后，要么对局已经结束，要么存在防守，能阻止它再下一手占这个角。' : 'each either ends the game or permits a defense against the corner capture on the following turn.'
      : zh ? '每种回应下都有防守，能阻止它再下一手占这个角。' : 'each has a defense that prevents the corner capture on the following turn.';
    return zh
      ? `下 ${insight.worse_move}，对手有办法抢到 ${insight.target}。改走 ${insight.better_move}，面对对手下一步的全部合法回应，${response}${cornerWitnessText(comparison, locale) ?? ''}${example}${otherCornerText(comparison, locale) ?? ''}`
      : `After ${insight.worse_move}, the opponent has a way to take ${insight.target}. After ${insight.better_move}, consider every legal next reply: ${response} ${cornerWitnessText(comparison, locale) ?? ''} ${example} ${otherCornerText(comparison, locale) ?? ''}`;
  }
  if (insight.kind === "corner_access") return zh
    ? `下 ${insight.worse_move} 后，对手下一步就能下 ${insight.target}；下 ${insight.better_move} 后，对手这一回合无法占 ${insight.target}。`
    : `After ${insight.worse_move}, the opponent can play ${insight.target} immediately. After ${insight.better_move}, ${insight.target} is not a legal reply on the next turn.`;
  if (insight.kind === "illustrated_corner") {
    const reply = best.frames[2].coordinate;
    const difference = insight.gap ? zh ? `${insight.gap} 仍然空着，这条夹击线没有连起来。` : `${insight.gap} stays empty, so the same capture line is broken.` : zh ? `对手还不能下 ${insight.target}。` : `the opponent cannot yet play ${insight.target}.`;
    return zh ? `改走 ${best.coordinate}，在图中的 ${reply === "pass" ? "跳过回合" : reply} 回应后，${difference}下在空角旁边之前，先替对手想一步：它能在哪里补一颗棋子，接着抢角？` : `With ${best.coordinate}, after the illustrated ${reply} reply, ${difference} Before playing beside an empty corner, ask where the opponent could place a disc to set up a corner capture.`;
  }
  return null;
}

export function cornerWitnessText(comparison: TeachingComparison, locale: Locale): string | null {
  const witness = comparison.insight.witness;
  if (!witness) return null;
  if (!witness.prefix.length) return replyOpportunityText(witness.opportunity, locale);
  const zh = locale === 'zh';
  const opportunity = witness.opportunity;
  const actor = opportunity.actor === 'X' ? zh ? '黑方' : 'Black' : zh ? '白方' : 'White';
  const cell = (value: string) => value === '.' ? zh ? '空格' : 'empty' : value === 'X' ? zh ? '黑子' : 'a black disc' : zh ? '白子' : 'a white disc';
  const sequence = witness.prefix.map((move) => move === 'pass' ? zh ? '跳过回合' : 'pass' : move).join(' → ');
  const changes = opportunity.changes.map((change) => zh
    ? `${opportunity.available_after} 走法的 ${change.coordinate} 是${cell(change.available)}；${opportunity.blocked_after} 走法中是${cell(change.blocked)}`
    : `${change.coordinate} has ${cell(change.available)} after ${opportunity.available_after}, versus ${cell(change.blocked)} after ${opportunity.blocked_after}`).join(zh ? '；' : '; ');
  const turnNote = witness.prefix.length === 1
    ? zh ? '落子仍须等待各自回合。' : 'Each player must still wait for their turn.' : '';
  return zh
    ? `同样经过 ${sequence} 后，${changes}。因此${actor}的夹击线 ${opportunity.capture_line.join(' → ')} 只在 ${opportunity.available_after} 变化中成立。${turnNote}`
    : `After the same ${sequence} sequence, ${changes}. Thus ${actor}'s capture line ${opportunity.capture_line.join(' → ')} exists only in the ${opportunity.available_after} variation. ${turnNote}`;
}

export function otherCornerText(comparison: TeachingComparison, locale: Locale): string | null {
  const threats = comparison.insight.other_threats ?? [];
  if (!threats.length) return null;
  const targets = threats.map((proof) => proof.target).join(locale === 'zh' ? '、' : ', ');
  return locale === 'zh' ? `不过，${comparison.insight.better_move} 后，${targets} 仍有对手两次行动内可以强行拿角的威胁。`
    : `After ${comparison.insight.better_move}, the opponent can still force ${targets} within its next two turns.`;
}

export function teachingFactText(comparison: TeachingComparison, id: string, locale: Locale): string | null {
  const kind = id.split(":")[1];
  if (kind === 'corner_contrast') return cornerWitnessText(comparison, locale);
  if (kind === 'other_corners') return otherCornerText(comparison, locale);
  if (kind === "decision_contrast") return comparisonTakeaway(comparison, locale);
  if (kind?.startsWith("continuation_")) {
    const choice = comparison.choices.find((choice) => choice.coordinate === kind.slice(13));
    return choice ? continuationText(choice, locale) : null;
  }
  if (kind === "defense") return comparisonTakeaway(comparison, locale);
  if (!kind?.startsWith("proof_")) return null;
  const coordinate = kind.slice(6);
  const proof = comparison.choices.find((choice) => choice.coordinate === coordinate)?.corner_proof;
  if (!proof || !proof.forced) return null;
  const zh = locale === "zh";
  const actor = proof.attacker === "X" ? zh ? "黑方" : "Black" : zh ? "白方" : "White";
  const action = proof.attack === proof.target ? zh ? `可以直接占 ${proof.target}` : `can take ${proof.target} immediately`
    : zh ? `可以先下 ${proof.attack}；无论你随后怎样应对，它再下一手都能占 ${proof.target}`
      : `can play ${proof.attack}, after which every legal defense still permits ${proof.target} on their next turn`;
  return zh ? `下 ${coordinate} 后，${actor}${action}。`
    : `After ${coordinate}, ${actor} ${action}.`;
}
