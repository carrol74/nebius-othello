import type { Locale } from "./locale";
import type { TeachingComparison, TeachingFrame, TeachingMove } from "./types";

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
  return zh ? `看这条线 ${line.join(" → ")}：${anchor} 的${color}棋子封住一端，${color}再下 ${target}，就能从两端夹住并翻转 ${discs}。` : `Follow ${line.join(" → ")}: ${color}'s disc at ${anchor} anchors one end. Playing ${target} brackets and flips ${discs}.`;
}

export function lessonText(comparison: TeachingComparison, move: TeachingMove, locale: Locale): string[] {
  const zh = locale === "zh";
  const other = comparison.actor === "X" ? zh ? "白方" : "White" : zh ? "黑方" : "Black";
  const own = comparison.actor === "X" ? zh ? "黑方" : "Black" : zh ? "白方" : "White";
  const target = move.target;
  const capture = captureLineText(move.capture_lines, comparison.actor === "X" ? "O" : "X", locale);
  if (move.kind === "corner_forced") return [
    zh ? `下 ${move.coordinate} 后，${other}可以先下 ${move.opponent_reply}，再占 ${target} 角落。${move.checked_defenses.length ? `${own}接下来的 ${move.checked_defenses.length} 种合法应对都挡不住这个角落。` : `${own}此时没有合法落点，必须跳过回合。`}` : `After ${move.coordinate}, ${other} can play ${move.opponent_reply} and then take corner ${target}. ${move.checked_defenses.length ? `None of ${own}'s ${move.checked_defenses.length} legal replies prevents that corner capture.` : `${own} has no legal move and must pass.`}`,
    ...(capture ? [capture + (zh ? "角落棋子以后无法被翻转。" : " A corner disc cannot be flipped later.")] : []),
  ];
  if (move.kind === "corner_given") return [
    zh ? `下 ${move.coordinate} 后，${other}立即可以下 ${target} 占据角落。这颗角落棋子以后无法被翻转。` : `${move.coordinate} lets ${other} immediately take corner ${target}. That corner disc cannot be flipped later.`,
    ...(capture ? [capture] : []),
  ];
  if (move.kind === "corner_taken") return [zh ? `${move.coordinate} 本身就是角落。下在这里，这颗棋子会一直保留到终局。点击演示，查看同时翻转了哪些棋子。` : `${move.coordinate} is a corner. Playing there keeps that disc safe through the end of the game. Step through to see which other discs it flips.`];
  if (move.kind === "pass") return [zh ? `下 ${move.coordinate} 后，${other}没有合法落点，必须跳过回合。${own}因此可以再下一步。点击演示，注意跳过回合时棋盘没有变化。` : `After ${move.coordinate}, ${other} has no legal move and must pass, so ${own} gets another move. In the demonstration, notice that passing does not change the board.`];
  return move.frames.slice(1, 3).map((frame) => stepText(frame, locale)).concat([
    zh ? "先看对手的回应会翻转哪些棋子，再切换另一种落子进行对照。" : "Check what the opponent's reply flips, then switch moves to compare the two lines.",
  ]);
}

export function comparisonTakeaway(comparison: TeachingComparison, locale: Locale): string | null {
  const zh = locale === "zh";
  const selected = comparison.choices.find((item) => item.coordinate === comparison.selected_move)!;
  const best = comparison.choices.find((item) => item.coordinate === comparison.recommended_move)!;
  if (selected === best) return null;
  if (selected.target && selected.target === best.target && ["corner_given", "corner_forced"].includes(selected.kind) && ["corner_given", "corner_forced"].includes(best.kind)) {
    return zh ? `两种落子都允许对手占 ${selected.target}，所以这个角落不能解释它们的评分差。演示只能证明这里有占角机会。` : `Both choices let the opponent take ${selected.target}, so that corner does not explain the score difference. The demonstrations establish that corner opportunity only.`;
  }
  if (selected.kind === "corner_forced" && best.frames.length > 2 && !best.opponent_corner_moves_after_reply.includes(selected.target!)) {
    const reply = best.frames[2].coordinate;
    return zh ? `改下 ${best.coordinate}，在演示的 ${reply === "pass" ? "跳过回合" : reply} 回应后，对手还不能下 ${selected.target}。这里要学的是：下在空角旁边前，先检查对手能否借下一手形成挡不住的占角机会。` : `With ${best.coordinate}, after the demonstrated ${reply} reply the opponent cannot yet play ${selected.target}. Before playing beside an empty corner, check whether the opponent can create a corner capture you cannot prevent.`;
  }
  return zh ? "这些演示说明了具体变化；当前分析没有证实一个能单独解释全部评分差的战术原因。" : "These demonstrations show concrete changes. The analysis has not established a single tactical cause for the full score difference.";
}
