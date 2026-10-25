import type { Locale } from "./locale";
import type { CoachToolCall } from "./types";

export function toolCallText(call: CoachToolCall, locale: Locale): string | null {
  if (call.error || typeof call.arguments === "string") return null;
  const {moves, move} = call.arguments as {moves?: string[]; move?: string};
  const zh = locale === "zh";
  if (call.name === "play_line" && moves) return zh ? `推演 ${moves.join(" → ")}` : `played out ${moves.join(" → ")}`;
  if (call.name === "check_corner_threat" && move) return zh ? `检查 ${move} 之后的角` : `checked corners after ${move}`;
  return null;
}
