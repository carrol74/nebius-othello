import type { Locale } from "./locale";
import type { EarlierDecisionLink } from "./types";

export function earlierDecisionText(link: EarlierDecisionLink, moveNumber: number, locale: Locale): string {
  return locale === "zh"
    ? `第 ${moveNumber} 手，你下了 ${link.recorded_move}，让对手能够在接下来两次行动内强行拿到 ${link.target}；当时的推荐走法 ${link.recommended_move} 在这个范围内提供了防守。实际续着一直保留着同一个威胁。这只说明局部联系，不能推断改走后的整盘结果。`
    : `At move ${moveNumber}, your ${link.recorded_move} allowed a forced ${link.target} capture within the opponent's next two turns; the recommendation ${link.recommended_move} offered a defense within that horizon. The threat remained throughout the recorded continuation. This establishes a local connection, not a prediction of a different game result.`;
}
