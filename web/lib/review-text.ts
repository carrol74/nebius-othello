import type { Locale } from "./locale";
import type { Review, ReviewEvidence, ReviewFact } from "./types";

export function factText(fact: ReviewFact, review: Review, locale: Locale): string {
  if (locale === "en") return fact.text;
  const color = (actor: string) => actor === "X" ? "黑方" : "白方";
  if (fact.id === "result") return `你执${color(review.human_color)}。终局：黑方 ${review.result.black_count}，白方 ${review.result.white_count}，${review.result.winner === "draw" ? "和棋" : `${color(review.result.winner)}获胜`}。`;
  if (fact.id === "adoption") return `显示过提示的 ${review.hint_adoption.shown_turns} 个回合中，你采用了 ${review.hint_adoption.adopted_turns} 次提示。`;
  if (fact.id === "outcome_limit") return "更高的搜索评分不保证获胜。原对局无法证明其他落点的最终结果，已保存的分支结果仅适用于该次对局。";
  if (fact.id.startsWith("hint:")) {
    const hint = review.hints.find((item) => `hint:${item.hint_id}` === fact.id);
    const entry = review.evidence.find((item) => item.shown_hint_ids.includes(hint?.hint_id ?? ""));
    if (hint) return `局面 ${hint.revision} 显示的推荐点为 ${hint.recommended_move}。${entry ? `你选择了 ${entry.actual_move}，${entry.actual_move === hint.recommended_move ? "已采用提示" : "没有采用提示"}。` : "此后没有记录玩家落子。"}`;
  }
  if (fact.id.startsWith("branch:")) {
    const branch = review.branch_results?.find((item) => `branch:${item.game_id}` === fact.id);
    if (branch) return `局面 ${branch.parent_revision} 的提示回放结果：黑方 ${branch.result.black_count}，白方 ${branch.result.white_count}，使用原对手配置。`;
  }
  const entry = review.evidence.find((item) => item.revision === fact.revision);
  if (!entry) {
    const pass = review.history.find((event) => event.kind === "pass" && event.revision - 1 === fact.revision);
    if (pass) return fact.id.endsWith(":decision") ? `局面 ${fact.revision}，${color(pass.actor)}跳过回合。` : `此时${color(pass.actor)}没有合法落点，对手仍可落子，因此必须跳过回合。棋盘和棋子数量不变。`;
    return fact.text;
  }
  const actual = entry.analysis.candidates.find((item) => item.coordinate === entry.actual_move)!;
  const best = entry.analysis.candidates.find((item) => item.coordinate === entry.recommended_move)!;
  const a = entry.comparisons?.find((item) => item.coordinate === entry.actual_move);
  const b = entry.comparisons?.find((item) => item.coordinate === entry.recommended_move);
  const kind = fact.id.split(":")[1];
  if (kind === "decision") return `局面 ${entry.revision}，${color(entry.actor)}选择了 ${entry.actual_move}，引擎推荐 ${entry.recommended_move}。`;
  if (kind === "score" || kind === "endgame") return `从${color(entry.actor)}视角，${actual.coordinate} 评分 ${actual.score}，${best.coordinate} 评分 ${best.score}，相差 ${entry.score_loss}。${actual.score_kind === "exact" && best.score_kind === "exact" ? "这是双方最佳应对下的精确终局子差。" : "这是搜索估计。"}`;
  if (kind === "mobility" && a && b) return `${a.coordinate} 后对手有 ${a.opponent_moves} 个合法落点，${b.coordinate} 后有 ${b.opponent_moves} 个。数量不能单独解释搜索推荐。`;
  if (kind === "frontier" && a && b) return `${a.coordinate} 后双方前沿棋子的数量差为 ${a.frontier_difference}，${b.coordinate} 后为 ${b.frontier_difference}，均按${color(entry.actor)}减去对手计算。前沿棋子指邻接空位的棋子。`;
  if (kind === "corners" && a && b) return `${a.coordinate} 后对手可立即占据的角落：${a.opponent_corners.join("、") || "没有"}；${b.coordinate} 后：${b.opponent_corners.join("、") || "没有"}。${b.corner ? `${b.coordinate} 本身占据角落。` : ""}`;
  if (kind === "corner_neighbor" && a && b) return `${[...new Set([a, b].filter((item) => item.empty_corner_neighbor).map((item) => item.coordinate))].join("、")} 邻接空角；邻接关系本身不能证明落子错误。`;
  if (kind === "pass" && a && b) return [...new Set([a, b])].filter((item) => !item.opponent_moves).map((item) => `${item.coordinate} 后${item.own_moves ? "对手必须跳过回合" : "双方均无合法落点，对局结束"}。`).join(" ");
  const move = kind?.replace(/^line_/, "");
  const candidate = entry.analysis.candidates.find((item) => item.coordinate === move);
  if (candidate && kind.startsWith("line_")) return `一条搜索续着：${candidate.principal_variation.map((item) => item === "pass" ? "跳过" : item).join(" → ")}。它没有涵盖对手的全部合法回应。`;
  if (candidate) return `${candidate.coordinate} 是合法落点，从${color(entry.actor)}视角评分 ${candidate.score}。`;
  return fact.text;
}

export function compareMoves(entry: ReviewEvidence, move: string, locale: Locale, lessonId?: string): string[] {
  const zh = locale === "zh";
  const best = entry.analysis.candidates.find((candidate) => candidate.coordinate === entry.recommended_move)!;
  const selected = entry.analysis.candidates.find((candidate) => candidate.coordinate === move)!;
  const recommended = entry.comparisons?.find((candidate) => candidate.coordinate === best.coordinate);
  const alternative = entry.comparisons?.find((candidate) => candidate.coordinate === move);
  const color = zh ? entry.actor === "X" ? "黑方" : "白方" : entry.actor === "X" ? "Black" : "White";
  const gap = best.score - selected.score;
  const exact = best.score_kind === "exact" && selected.score_kind === "exact";
  const lines = [gap === 0
    ? zh ? `${move} 与最佳评分相同（${selected.score}），同样可以选择。` : `${move} matches the best score (${selected.score}) and is an equally rated choice.`
    : zh ? `${best.coordinate} 的评分为 ${best.score}，比 ${move}（${selected.score}）高 ${gap}。${exact ? "这是双方最佳应对下的最终子差" : "这是搜索后续应对后的估计"}，评分从${color}视角计算。`
      : `${best.coordinate} scores ${best.score}, ${gap} above ${move} (${selected.score}). ${exact ? "This is the final disc difference under best play" : "This estimate includes searched replies"}, from ${color}'s perspective.`];
  if (recommended && alternative && move !== best.coordinate) {
    if (recommended.corner) lines.push(zh ? `${best.coordinate} 占据角落，角落棋子无法被翻转。` : `${best.coordinate} takes a corner, where its disc cannot be flipped.`);
    else if (alternative.opponent_corners.length > recommended.opponent_corners.length) {
      lines.push(zh ? `${move} 后对手可立即占据的角落：${alternative.opponent_corners.join("、")}；${best.coordinate} 后：${recommended.opponent_corners.join("、") || "没有"}。` : `Immediate corner replies after ${move}: ${alternative.opponent_corners.join(", ")}; after ${best.coordinate}: ${recommended.opponent_corners.join(", ") || "none"}.`);
    } else if (recommended.opponent_moves === 0 && recommended.own_moves > 0) lines.push(zh ? `${best.coordinate} 让对手无合法落点，必须跳过回合。` : `${best.coordinate} leaves the opponent no legal move, forcing a pass.`);
    else if (lessonId === "frontier") lines.push(zh ? `${best.coordinate} 后双方前沿棋子的数量差为 ${recommended.frontier_difference}，${move} 后为 ${alternative.frontier_difference}，均按${color}减去对手计算。前沿棋子邻接空位，这项特征不能单独决定优劣。` : `The frontier-disc difference is ${recommended.frontier_difference} after ${best.coordinate}, versus ${alternative.frontier_difference} after ${move}, counting ${color} minus the opponent. Frontier discs touch empty squares; this feature alone does not decide the best move.`);
    else lines.push(zh ? `${best.coordinate} 后对手有 ${recommended.opponent_moves} 个合法落点，${move} 后有 ${alternative.opponent_moves} 个。落点数量只是局面的一部分，最终推荐取决于后续搜索。` : `The opponent has ${recommended.opponent_moves} legal replies after ${best.coordinate}, versus ${alternative.opponent_moves} after ${move}. Reply count is one feature; the recommendation depends on the searched continuation.`);
  }
  if (!exact) lines.push(zh ? "搜索评分不代表胜率，也不保证获胜。" : "Search scores are not win probabilities or a guaranteed win.");
  return lines;
}
