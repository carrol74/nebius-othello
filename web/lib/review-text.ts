import type { Locale } from "./locale";
import type { Review, ReviewEvidence, ReviewFact, TeachingMove } from "./types";

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
  return positionFactText(fact, entry, locale);
}

export function positionFactText(fact: ReviewFact, entry: ReviewEvidence, locale: Locale, assessment?: TeachingMove["assessment"]): string {
  const color = (actor: string) => actor === "X" ? "黑方" : "白方";
  const actual = entry.analysis.candidates.find((item) => item.coordinate === entry.actual_move)!;
  const best = entry.analysis.candidates.find((item) => item.coordinate === entry.recommended_move)!;
  const a = entry.comparisons?.find((item) => item.coordinate === entry.actual_move);
  const b = entry.comparisons?.find((item) => item.coordinate === entry.recommended_move);
  const kind = fact.id.split(":")[1];
  const hasComparison = actual.coordinate !== best.coordinate;
  if (locale === "en") {
    const own = entry.actor === "X" ? "Black" : "White";
    if (kind === "forced_move") return `${entry.actual_move} is ${own}'s only legal move.`
      + (a?.opponent_corners.length ? ` The opponent can then take ${a.opponent_corners.join(", ")}.` : "");
    if (kind === "decision") {
      const judgment = assessment ? ({forced:"It is the only legal move.", best:"It has the highest rating.", tied_best:"It is tied for the highest rating.", lower_rated:`The search rates ${entry.recommended_move} higher.`})[assessment.status] : "";
      return `${entry.is_played === false ? "Compare" : "You played"} ${entry.actual_move}. ${judgment}`;
    }
    if (kind === "score" || kind === "endgame") return `From ${own}'s perspective, ${actual.coordinate} scores ${actual.score}`
      + (hasComparison ? ` and ${best.coordinate} scores ${best.score}, a difference of ${entry.score_loss}` : "")
      + (actual.score_kind === "exact" && best.score_kind === "exact" ? ". This is an exact Edax endgame score under best play; unfilled squares count for the winner. The board shows the actual disc count." : ".");
    if (kind === "mobility" && a && b) return `After ${a.coordinate}, the opponent has ${a.opponent_moves} legal replies`
      + (hasComparison ? `; after ${b.coordinate}, ${b.opponent_moves}` : "") + ". Look for replies that take a corner or create a capture line.";
    if (kind === "frontier" && a && b) return `After ${a.coordinate}, ${own}'s frontier-disc count minus the opponent's is ${a.frontier_difference}`
      + (hasComparison ? `; after ${b.coordinate}, ${b.frontier_difference}` : "") + ". Frontier discs touch an empty square.";
    if (kind === "corners" && a && b) return `After ${a.coordinate}, the opponent can immediately take: ${a.opponent_corners.join(", ") || "no corners"}`
      + (hasComparison ? `; after ${b.coordinate}: ${b.opponent_corners.join(", ") || "no corners"}` : "") + ".";
    if (kind === "corner_neighbor" && a && b) return `${[...new Set([a, b].filter((item) => item.empty_corner_neighbor).map((item) => item.coordinate))].join(", ")} sits beside an empty corner. Check whether the opponent can take that corner before playing there.`;
    if (kind === "pass" && a && b) return [...new Set([a, b])].filter((item) => !item.opponent_moves).map((item) => `After ${item.coordinate}, ${item.own_moves ? "the opponent must pass" : "neither player can move, so the game ends"}.`).join(" ");
    const candidate = entry.analysis.candidates.find((item) => `line_${item.coordinate}` === kind);
    if (candidate) return `Follow this continuation: ${candidate.principal_variation.join(" → ")}.`;
    return fact.text;
  }
  if (kind === "forced_move") return `${entry.actual_move} 是${color(entry.actor)}唯一的合法落点，这一回合没有其他走法可选。${a?.opponent_corners.length ? `随后${color(entry.actor === "X" ? "O" : "X")}可以占 ${a.opponent_corners.join("、")}。` : ""}`;
  if (kind === "decision") {
    const judgment = assessment ? ({forced:"这是唯一合法落点。", best:"这是评分最高的合法落点。", tied_best:"这是并列最高评分的落点。", lower_rated:`当前评分低于 ${entry.recommended_move}。`})[assessment.status] : "";
    return `局面 ${entry.revision}，${color(entry.actor)}${entry.is_played === false ? "可以下" : "实际落子"} ${entry.actual_move}。${judgment}`;
  }
  if (kind === "score" || kind === "endgame") return `从${color(entry.actor)}视角，${actual.coordinate} 评分 ${actual.score}` + (hasComparison ? `，${best.coordinate} 评分 ${best.score}，相差 ${entry.score_loss}` : "") + `。${actual.score_kind === "exact" && best.score_kind === "exact" ? "这是双方最佳应对下的 Edax 精确终局评分，剩余空格计入胜方；对局显示实际棋子数量。" : "这是搜索估计。"}`;
  if (kind === "mobility" && a && b) return `${a.coordinate} 后对手有 ${a.opponent_moves} 个合法落点` + (hasComparison ? `，${b.coordinate} 后有 ${b.opponent_moves} 个` : "") + "。看看这些落点里，哪些能占角或形成夹击。";
  if (kind === "frontier" && a && b) return `${a.coordinate} 后双方前沿棋子的数量差为 ${a.frontier_difference}` + (hasComparison ? `，${b.coordinate} 后为 ${b.frontier_difference}` : "") + `，按${color(entry.actor)}减去对手计算。前沿棋子指邻接空位的棋子。`;
  if (kind === "corners" && a && b) return `${a.coordinate} 后对手可立即占据的角落：${a.opponent_corners.join("、") || "没有"}` + (hasComparison ? `；${b.coordinate} 后：${b.opponent_corners.join("、") || "没有"}` : "") + `。${b.corner ? `${b.coordinate} 本身占据角落。` : ""}`;
  if (kind === "corner_neighbor" && a && b) return `${[...new Set([a, b].filter((item) => item.empty_corner_neighbor).map((item) => item.coordinate))].join("、")} 邻接空角。下在这里之前，先检查对手能否抢到这个角。`;
  if (kind === "pass" && a && b) return [...new Set([a, b])].filter((item) => !item.opponent_moves).map((item) => `${item.coordinate} 后${item.own_moves ? "对手必须跳过回合" : "双方均无合法落点，对局结束"}。`).join(" ");
  const move = kind?.replace(/^line_/, "");
  const candidate = entry.analysis.candidates.find((item) => item.coordinate === move);
  if (candidate && kind.startsWith("line_")) return `沿着这条走法推演：${candidate.principal_variation.map((item) => item === "pass" ? "跳过" : item).join(" → ")}。`;
  if (candidate) return `${candidate.coordinate} 是合法落点，从${color(entry.actor)}视角评分 ${candidate.score}。`;
  return fact.text;
}
