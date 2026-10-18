import type { Locale } from "./locale";
import type { TeachingComparison, TeachingFrame, TeachingMove } from "./types";

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
  return locale === "zh" ? `你下 ${attempted} 后，对手仍能占${cornerName(target, locale)}。需要调整的是更早的 ${rootMove}；走到这里，已经守不住这个角。` : `After your ${attempted}, the opponent can still take the ${cornerName(target, locale)}. The move to reconsider is the earlier ${rootMove}; by this point the corner cannot be saved.`;
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
  const other = comparison.actor === "X" ? zh ? "白方" : "White" : zh ? "黑方" : "Black";
  const own = comparison.actor === "X" ? zh ? "黑方" : "Black" : zh ? "白方" : "White";
  const target = move.target;
  const capture = captureLineText(move.capture_lines, comparison.actor === "X" ? "O" : "X", locale);
  if (move.kind === "corner_forced") return [
    zh ? `${move.coordinate} 把抢角的机会留给了${other}。它先补 ${move.opponent_reply}，下一手就能占${cornerName(target!, locale)}。${move.checked_defenses.length ? "这时再想防守，已经来不及了。" : `${own}此时没有地方能下，必须跳过。`}` : `${move.coordinate} gives ${other} a way to take the corner. They can first play ${move.opponent_reply}, then capture the ${cornerName(target!, locale)}. ${move.checked_defenses.length ? "By then, it is too late to defend it." : `${own} has no legal move and must pass.`}`,
    ...(capture ? [capture + (zh ? "角落棋子以后无法被翻转。" : " A corner disc cannot be flipped later.")] : []),
  ];
  if (move.kind === "corner_given") return [
    zh ? `${move.coordinate} 让${other}可以直接占${cornerName(target!, locale)}。这颗棋子以后就翻不回来了。` : `${move.coordinate} lets ${other} take the ${cornerName(target!, locale)} straight away. That disc can never be flipped back.`,
    ...(capture ? [capture] : []),
  ];
  if (move.kind === "corner_taken") return [zh ? `${move.coordinate} 本身就是角落。下在这里，这颗棋子会一直保留到终局。点击演示，查看同时翻转了哪些棋子。` : `${move.coordinate} is a corner. Playing there keeps that disc safe through the end of the game. Step through to see which other discs it flips.`];
  if (move.kind === "pass") return [zh ? `下 ${move.coordinate} 后，${other}没有合法落点，必须跳过回合。${own}因此可以再下一步。点击演示，注意跳过回合时棋盘没有变化。` : `After ${move.coordinate}, ${other} has no legal move and must pass, so ${own} gets another move. In the demonstration, notice that passing does not change the board.`];
  return move.frames.slice(1, 3).map((frame) => stepText(frame, locale));
}

export function comparisonTakeaway(comparison: TeachingComparison, locale: Locale): string | null {
  const zh = locale === "zh";
  const selected = comparison.choices.find((item) => item.coordinate === comparison.selected_move)!;
  const best = comparison.choices.find((item) => item.coordinate === comparison.recommended_move)!;
  if (selected === best) return null;
  if (selected.target && selected.target === best.target && ["corner_given", "corner_forced"].includes(selected.kind) && ["corner_given", "corner_forced"].includes(best.kind)) {
    return zh ? `这两种走法都会让对手拿到 ${selected.target}，光看谁能占角还分不出优劣。还要比较占角后双方的选择。` : `Both moves let the opponent take ${selected.target}. Corner access alone does not tell us which move is better; we also need to compare the choices left afterward.`;
  }
  if (selected.kind === "corner_forced" && best.frames.length > 2 && !best.opponent_corner_moves_after_reply.includes(selected.target!)) {
    const reply = best.frames[2].coordinate;
    const gap = selected.capture_lines[0]?.slice(1, -1).find((square) => best.frames[2].board[Number(square[1]) - 1][square.charCodeAt(0) - 97] === ".");
    const difference = gap ? zh ? `${gap} 仍然空着，这条夹击线没有连起来。` : `${gap} stays empty, so the same capture line is broken.` : zh ? `对手还不能下 ${selected.target}。` : `the opponent cannot yet play ${selected.target}.`;
    return zh ? `改走 ${best.coordinate}，在图中的 ${reply === "pass" ? "跳过回合" : reply} 回应后，${difference}下在空角旁边之前，先替对手想一步：它能在哪里补一颗棋子，接着抢角？` : `With ${best.coordinate}, after the illustrated ${reply} reply, ${difference} Before playing beside an empty corner, ask where the opponent could place a disc to set up a corner capture.`;
  }
  return zh ? "看清对手这一手的变化后，再换一种落子，比较它会怎样回应。" : "Once you understand this reply, switch moves and compare what the opponent can do in the other line.";
}
