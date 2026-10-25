import type { Locale } from "./locale";
import type { CornerWitness, TeachingComparison, TeachingFrame, TeachingMove } from "./types";

export function teachingNote(locale: Locale): string {
  return locale === "zh"
    ? "讲解基于已验证的局部变化，推演不代表整盘的最终结果。"
    : "Lessons use verified local changes. A continuation does not determine the final game result.";
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

export function defenseFeedback(rootMove: string, attempted: string, target: string, locale: Locale): string {
  return locale === "zh" ? `在 ${rootMove} 的续着中，你下 ${attempted} 后，对手仍能占${cornerName(target, locale)}。这一步防守没有挡住抢角。` : `In the ${rootMove} continuation, after your ${attempted}, the opponent can still take the ${cornerName(target, locale)}. This defense does not stop the corner capture.`;
}

export function stepText(frame: TeachingFrame, player: string, locale: Locale): string {
  const zh = locale === "zh";
  const you = (actor: string | null) => actor === player;
  if (frame.coordinate === null) return zh ? `初始局面，轮到${you(frame.turn) ? "你" : "对手"}。` : you(frame.turn) ? "Starting position. Your move." : "Starting position. The opponent's move.";
  if (frame.coordinate === "pass") return zh ? `${you(frame.actor) ? "你" : "对手"}没有合法落点，跳过回合，棋盘不变。`
    : `${you(frame.actor) ? "You have no legal move and pass" : "The opponent has no legal move and passes"}. The board stays unchanged.`;
  return zh ? `${you(frame.actor) ? "你" : "对手"}下 ${frame.coordinate}，翻转 ${frame.flipped.join("、")}。`
    : `${you(frame.actor) ? "You play" : "The opponent plays"} ${frame.coordinate}, flipping ${frame.flipped.join(", ")}.`;
}

export function captureLineText(lines: string[][], actor: "X" | "O", player: string, locale: Locale): string | null {
  const line = lines[0];
  if (!line) return null;
  const zh = locale === "zh";
  const mine = actor === player;
  const target = line[0], anchor = line[line.length - 1], discs = line.slice(1, -1).join(zh ? "、" : ", ");
  const sameRow = line.every((square) => square[1] === target[1]);
  const sameColumn = line.every((square) => square[0] === target[0]);
  const direction = sameRow ? zh ? `第 ${target[1]} 行` : `row ${target[1]}` : sameColumn ? zh ? `${target[0]} 列` : `column ${target[0]}` : zh ? "这条斜线" : "this diagonal";
  const who = mine ? "你" : "对手";
  return zh ? `看${direction}：${anchor} 已经有一颗${who}的棋子。${who}再下 ${target}，就会把中间的 ${discs} 夹住，全部翻成${who}的棋子。`
    : `Look at ${direction}: ${mine ? "you already have" : "the opponent already has"} a disc at ${anchor}. Playing ${target} traps ${discs} between two of ${mine ? "your" : "the opponent's"} discs and flips them.`;
}


const CORNERS = ["a1", "h1", "a8", "h8"];

function squares(list: string[], locale: Locale): string {
  return list.slice(0, 3).join(locale === "zh" ? "、" : ", ");
}

export function lessonText(comparison: TeachingComparison, move: TeachingMove, locale: Locale): string[] {
  const zh = locale === "zh";
  const forced = move.assessment.status === "forced";
  const witness = comparison.insight.witness;
  const contrast = comparison.decision_contrast;
  if (!forced && (witness || contrast)) {
    const opportunity = witness?.opportunity ?? contrast!.removed_reply ?? contrast!.added_reply!;
    const added = contrast?.removed_reply && contrast.added_reply;
    const lesson = witnessLesson(comparison, witness ?? {prefix: [], opportunity}, locale);
    if (added) lesson[2] += zh ? `不过，${opportunity.blocked_after} 也让对手多了 ${added.coordinate} 这个落点。` : ` However, ${opportunity.blocked_after} gives the opponent a new reply at ${added.coordinate}.`;
    const tradeoff = otherCornerText(comparison, locale);
    return tradeoff ? [...lesson, tradeoff] : lesson;
  }
  const opening = forced ? zh ? `${move.coordinate} 是唯一的合法落点。` : `${move.coordinate} is the only legal move.` : null;
  const continuation = move.continuation_lesson;
  if (continuation) {
    const ray = continuation.capture_line;
    return [
      opening ?? (zh ? "这一手翻到的棋子，对手下一步能夹回来吗？" : "Can the opponent flip back the discs you just gained?"),
      zh ? `对手可以下 ${ray[0]}，借 ${ray[ray.length - 1]} 夹回 ${squares(continuation.recaptured, locale)}。` : `The opponent can play ${ray[0]} and use ${ray[ray.length - 1]} to flip back ${squares(continuation.recaptured, locale)}.`,
      zh ? "落子前，先替对手找一次夹击，看看刚翻到的棋子能不能保住。" : "Before you play, look for the opponent's capture and check which new discs you can keep.",
    ];
  }
  const target = move.target;
  if (["corner_given", "corner_forced", "corner_defense"].includes(move.kind)) {
    const ray = move.capture_lines[0];
    return [
      opening ?? (zh ? `先看 ${target}：对手准备怎样把这个角拿走？` : `Look at ${target}: how could the opponent take this corner?`),
      ray ? captureLineText([ray], move.corner_proof?.attacker ?? (comparison.actor === "X" ? "O" : "X"), comparison.actor, locale)!
        : zh ? `对手准备占 ${target}。在推演里找出它夹击需要的另一端棋子。` : `The opponent is preparing to take ${target}. In the continuation, find the disc that anchors that capture.`,
      zh ? "在空角附近落子前，先看自己的棋子会不会接上对手抢角的夹击线。" : "Before playing near an empty corner, check whether your disc completes an opponent capture line into it.",
    ];
  }
  if (move.kind === "corner_taken") return [
    zh ? `${move.coordinate} 在角上，为什么这颗棋子能一直保住？` : `Why can you keep the disc at corner ${move.coordinate}?`,
    zh ? "翻转棋子要从两头夹住。角的外侧没有格子，对手夹不住它。" : "Flipping a disc needs both ends of a line. Nothing lies beyond a corner, so it cannot be trapped.",
  ];
  if (move.kind === "pass") return [
    zh ? `下 ${move.coordinate} 后，为什么又轮到你？` : `Why do you move again after ${move.coordinate}?`,
    zh ? "对手没有合法落点，必须跳过回合；你还能下，对局就继续。" : "The opponent has no legal move and must pass. The game continues while you can still move.",
  ];
  const last = move.frames.at(-1)!;
  if (last.turn === null) {
    const cells = last.board.join("");
    const mine = cells.split(comparison.actor).length - 1;
    const theirs = cells.split(comparison.actor === "X" ? "O" : "X").length - 1;
    return [opening ?? (zh ? "这一步之后，对局怎样结束？" : "How does the game end after this move?"),
      zh ? `双方都没有合法落点，按棋子数结算：你 ${mine} 颗，对手 ${theirs} 颗。` : `Neither side can move. You finish with ${mine} discs and the opponent with ${theirs}.`];
  }
  return conceptLesson(move, opening, locale);
}

function conceptLesson(move: TeachingMove, opening: string | null, locale: Locale): string[] {
  const zh = locale === "zh";
  const {exposed, inner_flips, stable_gained} = move.concepts;
  const more = exposed.length > 3 ? zh ? " 等棋子" : " and others" : "";
  const reason = !inner_flips ? zh ? `${move.coordinate} 只翻了边上的棋子。` : `${move.coordinate} flips only edge discs.`
    : exposed.length ? zh ? `${move.coordinate} 翻过来的 ${squares(exposed, locale)}${more} 挨着空格，对手以后可能从旁边的空格下棋，把${exposed.length > 1 ? "它们" : "它"}翻回去。` : `${move.coordinate} flips ${squares(exposed, locale)}${more} next to empty squares, where the opponent may later play to flip them back.`
      : zh ? `${move.coordinate} 翻过来的棋子四周都有棋子，没有新增挨着空格的棋子，这是安静的一步。` : `Every disc ${move.coordinate} flips is surrounded by discs, so it adds no disc next to an empty square: a quiet move.`;
  const stable = stable_gained.length ? zh ? `${squares(stable_gained, locale)} 从此不会再被翻转。` : ` ${squares(stable_gained, locale)} can never be flipped again.` : "";
  return [
    opening ?? (zh ? "这一步翻过来的棋子，哪些挨着空格？" : "Which discs flipped by this move sit next to empty squares?"),
    reason + stable,
    zh ? "落子前比较几个候选：哪一步翻过来的棋子挨着空格最少？" : "Before you play, compare candidates: which one leaves the fewest flipped discs next to empty squares?",
  ];
}

function witnessLesson(comparison: TeachingComparison, witness: CornerWitness, locale: Locale): string[] {
  const zh = locale === "zh";
  const player = comparison.actor;
  const opportunity = witness.opportunity;
  const ray = opportunity.capture_line, target = ray[0], anchor = ray[ray.length - 1];
  const middle = ray.slice(1, -1).join(zh ? "、" : ", ");
  const mine = opportunity.actor === player;
  const setup = witness.prefix[0];
  const proof = comparison.choices.find((choice) => choice.coordinate === opportunity.available_after)?.corner_proof;
  // The proof covers every reply, so the setup cannot be stopped
  const unstoppable = !mine && !!proof?.forced && proof.attack === setup && proof.target === target;
  const corner = CORNERS.includes(target) && !mine;
  const after = opportunity.available_after;
  const result = zh
    ? `${after} 之后，` + (unstoppable ? `对手先下 ${setup}，你怎么应对都挡不住，它接着下 ${target}`
      : setup ? `${setup === "pass" ? "对手跳过回合后" : `对手下 ${setup} 后`}，${mine ? "你" : "对手"}可以下 ${target}` : `${mine ? "你" : "对手"}可以下 ${target}`)
      + `，借 ${anchor} 夹住 ${middle}${corner ? "，拿到这个角" : ""}。`
    : `After ${after}, ` + (unstoppable ? `the opponent plays ${setup} first; whatever you reply, it then plays ${target}`
      : setup ? `${setup === "pass" ? "after the opponent passes" : `after the opponent plays ${setup}`}, ${mine ? "you" : "the opponent"} can play ${target}` : `${mine ? "you" : "the opponent"} can play ${target}`)
      + `, using ${anchor} to trap ${middle}${corner ? " and take the corner" : ""}.`;
  const owner = (value: string) => value === "." ? zh ? "空格" : "empty" : value === player ? zh ? "你的棋子" : "your disc" : zh ? "对手的棋子" : "an opponent disc";
  const change = opportunity.changes.find((item) => item.coordinate === anchor) ?? opportunity.changes[0];
  const attacker = mine ? zh ? "你" : "you" : zh ? "对手" : "the opponent";
  const same = witness.prefix.length ? zh ? "，同样应对之后" : " and the same replies" : "";
  const blocked = zh ? `换成 ${opportunity.blocked_after}${same}，` : `With ${opportunity.blocked_after}${same}, `;
  const effect = change.coordinate === target
    ? zh ? `${target} 已经有棋子，${attacker}下不了这里。` : `${target} is already occupied, so ${attacker} cannot play there.`
    : change.coordinate === anchor
      ? zh ? `${anchor} 是${owner(change.blocked)}，这条线缺了另一端，${attacker}下不了 ${target}。` : `${anchor} is ${owner(change.blocked)}, so the line has no far end and ${attacker} cannot play ${target}.`
      : zh ? `${change.coordinate} 是${owner(change.blocked)}，这条线在中间断开，${attacker}下不了 ${target}。` : `${change.coordinate} is ${owner(change.blocked)}, so the line breaks and ${attacker} cannot play ${target}.`;
  const habit = mine
    ? zh ? "比较两步时，看哪一步之后你还有这样的防守落点。" : " When comparing moves, check which one keeps a defensive square like this."
    : ray.slice(1, -1).includes(after)
      ? zh ? "落子前，看新棋子所在的每条线：一端空着时，另一端会不会变成对手的棋子？" : " Before you play, check each line through the new disc: if one end is empty, could the other end become the opponent's?"
      : zh ? "落子前，从对手的棋子出发，沿着你的棋子看向空格，找对手能完成的夹击。" : " Before you play, start from an opponent disc and look past your discs toward an empty square.";
  return [
    mine ? zh ? `先看 ${target}：为什么换成 ${after}，你才能下这里？` : `Look at ${target}: why can you play there only after ${after}?`
      : zh ? `先看 ${target}：对手怎样才能下这里？` : `Look at ${target}: how can the opponent play there?`,
    result,
    blocked + effect + habit,
  ];
}

export function otherCornerText(comparison: TeachingComparison, locale: Locale): string | null {
  const threats = comparison.insight.other_threats ?? [];
  if (!threats.length) return null;
  const zh = locale === "zh";
  const better = comparison.insight.better_move;
  const lines = threats.map((proof) => proof.attack === proof.target
    ? zh ? `对手可以直接占 ${proof.target}` : `the opponent can take ${proof.target} immediately`
    : zh ? `对手可以先下 ${proof.attack}，你怎么应对都挡不住它拿 ${proof.target}` : `the opponent can play ${proof.attack} and then take ${proof.target} whatever you reply`);
  return zh ? `不过，${better} 也有代价：${lines.join("；")}。看完整盘变化后，引擎仍然推荐 ${better}。`
    : `However, ${better} has a cost: ${lines.join("; ")}. After looking at the whole game, the engine still recommends ${better}.`;
}
