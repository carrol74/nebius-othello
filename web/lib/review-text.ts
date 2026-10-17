import type { Locale } from "./locale";
import type { Review, ReviewFact } from "./types";

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
