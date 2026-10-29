import type { Locale } from "./locale";
import type { CornerPracticeOption, HistoryEvent, LessonReason, TeachingComparison, TeachingFrame, TeachingMove } from "./types";

export function teachingNote(locale: Locale): string {
  return locale === "zh"
    ? "讲解基于已验证的局部变化，推演不代表整盘的最终结果。"
    : "Lessons use verified local changes. A continuation does not determine the final game result.";
}

export function teachingChoiceLabel(move: TeachingMove, locale: Locale): string {
  const tied = move.assessment.best_moves.length > 1;
  return move.assessment.is_played ? locale === "zh" ? "你当时下的" : "Your game move"
    : locale === "zh" ? tied ? "推荐走法之一" : "推荐走法" : tied ? "One of the recommended moves" : "Recommended move";
}

export function cornerName(square: string, locale: Locale): string {
  const names: Record<string, [string, string]> = {a1:["top-left corner", "左上角"], h1:["top-right corner", "右上角"], a8:["bottom-left corner", "左下角"], h8:["bottom-right corner", "右下角"]};
  const name = names[square]?.[locale === "zh" ? 1 : 0];
  return name ? `${name} ${square}` : square;
}

export function practicePrompt(options: CornerPracticeOption[], target: string, locale: Locale): string {
  const zh = locale === "zh", corner = cornerName(target, locale);
  const prompt = zh ? `回到你落子之前：选一步，试着不让对手拿到${corner}。` : `Back before your move: pick a move that keeps the opponent from taking the ${corner}.`;
  if (options.some((option) => option.safe)) return prompt;
  return prompt + (zh ? `不过这个局面里，每一步都会让对手能拿到${corner}，试试看它是怎么拿到的。` : ` In this position every move lets the opponent take it; try one to see how.`);
}

export function practiceFeedback(option: CornerPracticeOption, target: string, recommended: string, locale: Locale): string {
  const zh = locale === "zh", corner = cornerName(target, locale), move = option.coordinate;
  if (move === target) return zh ? `挡住了：你自己占了${corner}。` : `Blocked: you take the ${corner} yourself.`;
  if (option.safe) return zh
    ? `挡住了：下 ${move} 之后，对手三步之内拿不到${corner}。` + (move === recommended ? "这也是推荐走法。" : option.recommended ? `引擎认为它和 ${recommended} 一样好。` : `不过看完整盘变化，引擎更推荐 ${recommended}。`)
    : `Blocked: after ${move}, the opponent cannot take the ${corner} within three moves.` + (move === recommended ? " This is also the recommended move." : option.recommended ? ` The engine rates it as good as ${recommended}.` : ` Looking at the whole game, the engine still prefers ${recommended}.`);
  if (option.attack === "pass") return zh ? `没挡住：下 ${move} 之后，对手只能跳过，可你接着怎么下都挡不住它拿${corner}。`
    : `Not blocked: after ${move}, the opponent must pass, but whatever you play next it can take the ${corner}.`;
  if (option.attack === target) return zh ? `没挡住：下 ${move} 之后，对手可以直接占${corner}。` : `Not blocked: after ${move}, the opponent can take the ${corner} right away.`;
  return zh ? `没挡住：下 ${move} 之后，对手先下 ${option.attack}，你怎么应对都挡不住它拿${corner}。`
    : `Not blocked: after ${move}, the opponent plays ${option.attack} and then takes the ${corner} whatever you reply.`;
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


// Says why a demonstration step matters, following the backend's primary reason
export function stepNote(comparison: TeachingComparison, choice: TeachingMove, frame: number, locale: Locale): string | null {
  const zh = locale === "zh";
  const sep = zh ? "、" : ", ";
  const list = (squares: string[]) => squares.join(sep);
  const reason = comparison.reason;
  const marks = reason?.marks[choice.coordinate];
  if (reason && marks && frame === Math.min(reason.frame, choice.frames.length - 1)) {
    const move = choice.coordinate, count = marks.length;
    switch (reason.kind) {
      case "reply_consequence": {
        const effect = comparison.decision_contrast?.consequence;
        if (!effect) return null;
        if (move === effect.opportunity.blocked_after) return zh
          ? "高亮的是你接下来全部可选的落点，已经集中在同一条线上。"
          : "The highlighted squares are all your next legal moves, confined to the same line.";
        return zh ? `高亮这条夹击线，展示你保留下来的 ${effect.opportunity.coordinate} 落点。`
          : `The highlighted capture line shows your preserved move at ${effect.opportunity.coordinate}.`;
      }
      case "corner_contrast": case "reply_contrast": {
        const who = reason.actor === comparison.actor ? zh ? "你" : "you" : zh ? "对手" : "the opponent";
        const span = zh ? `${marks[0]} 到 ${marks.at(-1)} 这条线` : `the line from ${marks[0]} to ${marks.at(-1)}`;
        const [column, row] = [marks[0].charCodeAt(0) - 97, Number(marks[0][1]) - 1];
        const taken = choice.frames[frame].board[row][column] !== ".";
        if (move !== reason.move && taken) return zh ? `换成 ${move}，${marks[0]} 已经有棋子，${who}下不了这里。` : `With ${move}, ${marks[0]} is already occupied, so ${who} cannot play there.`;
        return move === reason.move
          ? zh ? `现在 ${span}连上了：${who}下 ${marks[0]} 就能夹住 ${list(marks.slice(1, -1))}。` : `Now ${span} is complete: ${who} can play ${marks[0]} and trap ${list(marks.slice(1, -1))}.`
          : zh ? `换成 ${move}，${span}连不上，${who}下不了 ${marks[0]}。` : `With ${move}, ${span} is broken, so ${who} cannot play ${marks[0]}.`;
      }
      case "recapture": {
        const lesson = choice.continuation_lesson!, anchor = lesson.capture_line.at(-1);
        return zh ? `对手借 ${anchor} 把你刚翻到的 ${list(lesson.recaptured)} 夹了回去。` : `The opponent uses ${anchor} to flip back ${list(lesson.recaptured)}, which you had just gained.`;
      }
      case "quiet": return count
        ? zh ? `高亮的 ${list(marks)} 挨着空格，对手以后可能从旁边的空格下棋，把${count > 1 ? "它们" : "它"}翻回去。` : `The highlighted ${list(marks)} ${count > 1 ? "sit" : "sits"} next to an empty square, where the opponent may later play to flip ${count > 1 ? "them" : "it"} back.`
        : zh ? `${move} 翻过来的棋子里，没有挨着空格的（边上的不算）。` : `None of the discs ${move} flips sits next to an empty square (edge discs aside).`;
      case "mobility": return count
        ? zh ? `高亮的 ${count} 个空格是对手的安全落点：下在那里不会让你拿到角。` : `The ${count} highlighted squares are safe replies for the opponent: none of them lets you take a corner.`
        : zh ? "对手没有安全落点：它下在哪里都会让你拿到角。" : "The opponent has no safe reply: every move it makes lets you take a corner.";
      case "stable": return count
        ? zh ? `高亮的 ${list(marks)} 以后不会再被翻转。` : `The highlighted ${list(marks)} can never be flipped again.`
        : zh ? `${move} 没有让你的棋子变得不能被翻转。` : `${move} makes none of your discs impossible to flip.`;
      case "corners": return count
        ? zh ? `现在对手可以直接占角：${list(marks)}。` : `Now the opponent can take a corner right away: ${list(marks)}.`
        : zh ? "现在对手不能直接占角。" : "Now the opponent cannot take a corner right away.";
    }
  }
  // A corner both moves lose is not the lesson, so its steps get no notes
  if (comparison.insight.kind === "shared_corner" || !choice.target) return null;
  const ray = choice.capture_lines[0];
  const lost = choice.defendable === false ? zh ? "在这一步之前，这个角就已经保不住了。" : " This corner was already lost before this move." : "";
  if (choice.kind === "corner_given" && frame === 1) return (zh
    ? `现在对手可以直接下 ${choice.target}` + (ray ? `，借 ${ray.at(-1)} 夹住 ${list(ray.slice(1, -1))}` : "") + "。"
    : `Now the opponent can play ${choice.target} right away` + (ray ? `, using ${ray.at(-1)} to trap ${list(ray.slice(1, -1))}` : "") + ".") + lost;
  if (choice.kind !== "corner_forced") return null;
  const count = choice.checked_defenses.length;
  if (frame === 2) return (zh ? `对手下了这一步以后，你怎么应对都挡不住它下 ${choice.target}。` : `After this move, nothing you play stops the opponent from taking ${choice.target}.`) + lost;
  if (frame === 3) return count ? zh ? `这只是你的一种应对。这时你共有 ${count} 种下法，换成哪一种都挡不住。` : `This is just one of your ${count} possible replies; none of them stops it.`
    : zh ? "你没有合法落点，只能跳过。" : "You have no legal move and must pass.";
  if (frame === 4) return ray ? zh ? `它借 ${ray.at(-1)} 夹住 ${list(ray.slice(1, -1))}，拿到了这个角。` : `It uses ${ray.at(-1)} to trap ${list(ray.slice(1, -1))} and takes the corner.`
    : zh ? "它拿到了这个角。" : "It takes the corner.";
  return null;
}

// One line for each move worth reviewing, naming its primary reason
export function reasonLabel(reason: LessonReason | null | undefined, locale: Locale): string | null {
  if (!reason) return null;
  const corner = reason.target ? cornerName(reason.target, locale) : "";
  const labels: Record<LessonReason["kind"], [string, string]> = {
    forced_move: ["the only legal move", "唯一的合法落点"],
    corner_contrast: [`the ${corner}`, corner], corner_defense: [`the ${corner}`, corner], corner_threat: [`the ${corner}`, corner],
    corners: ["whether the opponent can take a corner", "对手能不能直接占角"],
    reply_contrast: [`the opponent's reply at ${reason.target}`, `对手的落点 ${reason.target}`],
    reply_consequence: ["keeping a route for your next move", "给下一手保留落点"],
    recapture: ["discs flipped straight back", "刚翻到的棋子被夹回去"],
    quiet: ["discs next to empty squares", "挨着空格的棋子"],
    mobility: ["the opponent's safe replies", "对手的安全落点"],
    stable: ["discs that can never be flipped", "稳定子"],
    parity: ["the empty regions", "空地的奇偶"],
  };
  const [en, zh] = labels[reason.kind];
  return locale === "zh" ? `关键：${zh}` : `Key: ${en}`;
}

// Failures where Nemotron answered but its text did not pass the code checks
const CHECK_FAILURES = ["COACH_UNGROUNDED", "REVIEW_PLAN_INVALID", "COACH_ROUNDS", "COACH_NO_TOOL", "REVIEW_TRUNCATED"];

type CoachSubject = "lesson" | "question" | "summary";

// A check failure or a missing model is quiet: the board demonstration still works
export function coachingFailure(code: string | null | undefined, message: string | null | undefined, subject: CoachSubject, locale: Locale): {quiet: boolean; text: string} {
  const zh = locale === "zh";
  if (code === "SERVICE_RESTARTED") return {quiet: false, text: zh
    ? "服务重启中断了生成，请重试。" : "A server restart interrupted generation. Please retry."};
  if (code === "REVIEW_NOT_CONFIGURED") return {quiet: true, text: {
    lesson: zh ? "这个服务没有接入 Nemotron，可以在棋盘上看推演。" : "Nemotron is not set up on this server; explore the line on the board.",
    question: zh ? "这个服务没有接入 Nemotron，暂时不能回答提问。" : "Nemotron is not set up on this server, so questions cannot be answered.",
    summary: zh ? "这个服务没有接入 Nemotron，可以在棋盘上选择自己的回合查看推演。" : "Nemotron is not set up on this server; select one of your turns on the board to explore it.",
  }[subject]};
  if (!code || !CHECK_FAILURES.includes(code)) return {quiet: false, text: message ?? ""};
  return {quiet: true, text: {
    lesson: zh ? "Nemotron 这次没能给出可靠的讲解。可以先在棋盘上看推演，或者再讲解一次。" : "Nemotron could not give a reliable explanation this time. Explore the line on the board, or ask for the lesson again.",
    question: zh ? "Nemotron 这次没能给出可靠的回答，可以换个问法再问一次。" : "Nemotron could not give a reliable answer this time. Try asking another way.",
    summary: zh ? "Nemotron 这次没能写出可靠的总结。可以在棋盘上选择自己的回合，或者重新总结。" : "Nemotron could not write a reliable summary this time. Select one of your turns on the board, or summarize again.",
  }[subject]};
}

// Null when the game record followed the line's first reply
export function actualReplyText(history: HistoryEvent[], revision: number, frames: TeachingFrame[], locale: Locale): string | null {
  const played = history.find((event) => event.revision === revision + 1);
  const reply = history.find((event) => event.revision === revision + 2);
  if (!played || !reply || frames.length < 3 || played.coordinate !== frames[1].coordinate) return null;
  const actual = reply.kind === "pass" ? "pass" : reply.coordinate;
  if (actual === frames[2].coordinate) return null;
  return locale === "zh"
    ? `实际对局里对手${actual === "pass" ? "跳过了回合" : `下的是 ${actual}`}，没有走这条线。这条推演展示的是对手当时也能选的下法。`
    : `In the actual game the opponent ${actual === "pass" ? "passed" : `played ${actual}`}, not this line. This line shows another move the opponent could have chosen.`;
}
