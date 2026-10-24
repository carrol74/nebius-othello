import type { Locale } from "./locale";
import type { EarlierDecisionLink } from "./types";

export function earlierDecisionText(link: EarlierDecisionLink, moveNumber: number, locale: Locale): string {
  return locale === "zh"
    ? `第 ${moveNumber} 手，你下了 ${link.recorded_move}，对手就能在接下来两次落子内抢到 ${link.target}。当时改下 ${link.recommended_move}，可以防住这轮抢角。`
    : `At move ${moveNumber}, you played ${link.recorded_move}, letting the opponent force ${link.target} within their next two turns. Playing ${link.recommended_move} would let you defend against that corner threat.`;
}
