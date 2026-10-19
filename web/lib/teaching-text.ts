import type { Locale } from "./locale";
import type { TeachingComparison, TeachingFrame, TeachingMove } from "./types";

export function teachingChoiceLabel(move: TeachingMove, locale: Locale): string {
  const zh = locale === "zh";
  const labels = [];
  if (move.assessment.is_played) labels.push(zh ? "实际落子" : "Played");
  const status = move.assessment.status;
  if (status === "forced") labels.push(zh ? "唯一合法落点" : "Only legal move");
  else if (status === "best") labels.push(zh ? "评分最高" : "Best rated");
  else if (status === "tied_best") labels.push(zh ? "并列最高" : "Tied best rated");
  else if (move.assessment.is_played) labels.push(zh ? "评分较低" : "Lower rated");
  return labels.length ? labels.join(" · ") : zh ? "所选落点" : "Your choice";
}

export function cornerName(square: string, locale: Locale): string {
  const names: Record<string, [string, string]> = {a1:["top-left corner", "左上角"], h1:["top-right corner", "右上角"], a8:["bottom-left corner", "左下角"], h8:["bottom-right corner", "右下角"]};
  const name = names[square]?.[locale === "zh" ? 1 : 0];
  return name ? `${name} ${square}` : square;
}

export function lessonPrompt(comparison: TeachingComparison, move: TeachingMove, locale: Locale): string {
  const zh = locale === "zh";
  const other = comparison.actor === "X" ? zh ? "白方" : "White" : zh ? "黑方" : "Black";
  if (move.kind === "corner_forced") return zh ? `${other}准备先走 ${move.opponent_reply}，再抢${cornerName(move.target!, locale)}。现在换你防守，能挡住它吗？` : `${other} plans to play ${move.opponent_reply}, then take the ${cornerName(move.target!, locale)}. Your turn: can you stop that corner capture?`;
  if (move.kind === "corner_given") return zh ? `下 ${move.coordinate} 后，看看${cornerName(move.target!, locale)}。${other}能直接占住它吗？` : `After ${move.coordinate}, look at the ${cornerName(move.target!, locale)}. Can ${other} take it immediately?`;
  if (move.kind === "corner_taken") return zh ? `下 ${move.coordinate} 后，哪颗棋子能一直保留到终局？` : `After ${move.coordinate}, which disc will stay yours for the rest of the game?`;
  if (move.kind === "pass") return zh ? `下 ${move.coordinate} 后，该谁继续？看看对手还有没有地方能下。` : `Who moves after ${move.coordinate}? Check whether the opponent has anywhere to play.`;
  return zh ? "先替对手想一步：它会下在哪里，又会翻转哪些棋子？" : "Think one move ahead for your opponent: where might they play, and which discs would they flip?";
}

export function defenseFeedback(rootMove: string, attempted: string, target: string, locale: Locale): string {
  return locale === "zh" ? `你下 ${attempted} 后，对手仍能占${cornerName(target, locale)}。这说明这条续着里的防守没有挡住抢角；可以返回 ${rootMove} 前的局面，比较另一条走法。` : `After your ${attempted}, the opponent can still take the ${cornerName(target, locale)} in this continuation. Return to the position before ${rootMove} to compare the other line.`;
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
  const other = comparison.actor === "X" ? zh ? "白方" : "White" : zh ? "黑方" : "Black";
  const assessment = move.assessment;
  if (assessment.status === "forced") {
    const context = zh ? `${move.coordinate} 是${own}此时唯一的合法落点，这一回合没有其他走法可以选择。`
      : `${move.coordinate} is ${own}'s only legal move here. There is no alternative to choose on this turn.`;
    return [context, ...moveConsequence(comparison, move, locale)];
  }
  const basis = assessment.score_kind === "exact" ? zh ? "精确终局分析" : "Exact endgame analysis" : zh ? "当前搜索" : "The current search";
  const context = assessment.status === "tied_best" ? zh
    ? `${basis}把 ${assessment.best_moves.join("、")} 并列为最高评分。${move.coordinate} 是其中之一。`
    : `${basis} rates ${assessment.best_moves.join(", ")} equally best. ${move.coordinate} is one of these tied moves.`
    : assessment.status === "best" ? zh
      ? `${basis}中，${move.coordinate} 在 ${assessment.legal_move_count} 个合法落点里评分最高。`
      : `${basis} rates ${move.coordinate} highest among ${assessment.legal_move_count} legal moves.`
      : zh ? `${basis}对 ${assessment.best_moves.join("、")} 的评分高于 ${move.coordinate}。`
        : `${basis} rates ${assessment.best_moves.join(", ")} above ${move.coordinate}.`;
  const evaluation = assessment.position === "behind" ? [zh
    ? `${assessment.score_kind === "estimate" ? "当前估计" : "精确终局"}评分仍偏向${other}，即使选择最高评分的走法，局面也仍然不利。`
    : `The ${assessment.score_kind === "estimate" ? "estimated" : "exact endgame"} score still favors ${other}, even with the highest-rated move.`] : [];
  return [context, ...evaluation, ...moveConsequence(comparison, move, locale)];
}

function moveConsequence(comparison: TeachingComparison, move: TeachingMove, locale: Locale): string[] {
  const zh = locale === "zh";
  const other = comparison.actor === "X" ? zh ? "白方" : "White" : zh ? "黑方" : "Black";
  const own = comparison.actor === "X" ? zh ? "黑方" : "Black" : zh ? "白方" : "White";
  const target = move.target;
  const capture = captureLineText(move.capture_lines, comparison.actor === "X" ? "O" : "X", locale);
  if (move.kind === "corner_forced") return [
    zh ? `这条续着里，${other}先下 ${move.opponent_reply}，再占${cornerName(target!, locale)}。${move.checked_defenses.length ? `已核对${own}随后全部 ${move.checked_defenses.length} 个合法回应，仍会留下这个角。` : `${own}此时没有合法落点，必须跳过。`}` : `In this continuation, ${other} plays ${move.opponent_reply} and can then take the ${cornerName(target!, locale)}. ${move.checked_defenses.length ? `All ${move.checked_defenses.length} legal ${own} replies were checked and still leave that corner available.` : `${own} has no legal move and must pass.`}`,
    ...(capture ? [capture + (zh ? "角落棋子以后无法被翻转。" : " A corner disc cannot be flipped later.")] : []),
  ];
  if (move.kind === "corner_given") return [
    zh ? `下完 ${move.coordinate}，${other}可以直接占${cornerName(target!, locale)}。角落棋子以后无法被翻转。` : `After ${move.coordinate}, ${other} can take the ${cornerName(target!, locale)} immediately. A corner disc cannot be flipped later.`,
    ...(capture ? [capture] : []),
  ];
  if (move.kind === "corner_taken") return [zh ? `${move.coordinate} 本身就是角落。下在这里，这颗棋子会一直保留到终局。点击演示，查看同时翻转了哪些棋子。` : `${move.coordinate} is a corner. Playing there keeps that disc safe through the end of the game. Step through to see which other discs it flips.`];
  if (move.kind === "pass") return [zh ? `下 ${move.coordinate} 后，${other}没有合法落点，必须跳过回合。${own}因此可以再下一步。点击演示，注意跳过回合时棋盘没有变化。` : `After ${move.coordinate}, ${other} has no legal move and must pass, so ${own} gets another move. In the demonstration, notice that passing does not change the board.`];
  return move.frames.slice(1, 3).map((frame) => stepText(frame, locale));
}

export function comparisonTakeaway(comparison: TeachingComparison, locale: Locale): string | null {
  const zh = locale === "zh";
  const insight = comparison.insight;
  if (insight.kind === "forced") return zh ? "想学习可以调整的选择，请回看更早有多个合法落点的回合。" : "To study a choice you could change, return to an earlier turn with more than one legal move.";
  if (insight.kind === "equal") return zh
    ? `这两种走法在${insight.score_kind === "exact" ? "精确终局分析" : "当前搜索"}中评分相同，不能仅凭推荐点选了其中一个，就把另一个判成失误。可以比较两条续着的回应。`
    : `These moves are equally rated by ${insight.score_kind === "exact" ? "exact endgame analysis" : "the current search"}. The recommendation alone gives no score-based reason to reject the other move. Compare their replies.`;
  if (insight.kind === "shared_corner") return zh
    ? `这两种走法都会让对手拿到 ${insight.target}，光看谁能占角还分不出优劣。${insight.score_kind === "exact" ? "终局分析" : "当前搜索"}评分偏向 ${insight.better_move}，但这段抢角演示本身还解释不了评分差距。`
    : `Both moves let the opponent take ${insight.target}. Corner access alone does not tell us which move is better. ${insight.score_kind === "exact" ? "Endgame analysis" : "The current search"} favors ${insight.better_move}, but this corner demonstration does not establish the reason for that score gap.`;
  const best = comparison.choices.find((item) => item.coordinate === insight.better_move)!;
  if (insight.kind === "corner_access") return zh
    ? `下 ${insight.worse_move} 后，对手下一步就能下 ${insight.target}；下 ${insight.better_move} 后，${insight.target} 暂时不是它的合法落点。这是两种走法已核实的一处差别。`
    : `After ${insight.worse_move}, the opponent can play ${insight.target} immediately. After ${insight.better_move}, ${insight.target} is not a legal reply on the next turn. This is one verified difference between the moves.`;
  if (insight.kind === "illustrated_corner") {
    const reply = best.frames[2].coordinate;
    const difference = insight.gap ? zh ? `${insight.gap} 仍然空着，这条夹击线没有连起来。` : `${insight.gap} stays empty, so the same capture line is broken.` : zh ? `对手还不能下 ${insight.target}。` : `the opponent cannot yet play ${insight.target}.`;
    return zh ? `改走 ${best.coordinate}，在图中的 ${reply === "pass" ? "跳过回合" : reply} 回应后，${difference}下在空角旁边之前，先替对手想一步：它能在哪里补一颗棋子，接着抢角？` : `With ${best.coordinate}, after the illustrated ${reply} reply, ${difference} Before playing beside an empty corner, ask where the opponent could place a disc to set up a corner capture.`;
  }
  return zh ? `当前评分偏向 ${insight.better_move}。这两条短续着展示了可能的回应，还不足以归纳出评分差距的单一原因。切换落点，比较对手下在哪里、翻转哪些棋子。`
    : `The current scores favor ${insight.better_move}. These short lines show possible replies but do not establish a single reason for the score gap. Switch moves to compare the reply squares and flipped discs.`;
}
