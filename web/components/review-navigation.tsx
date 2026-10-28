import { useLocale } from "@/lib/locale";
import { moveNumber, reviewRevisions } from "@/lib/game-view";
import type { GameState } from "@/lib/types";

// The timeline holds your moves, then the final board where the game summary lives
export function ReviewNavigation({game, revision, select}: {
  game: GameState; revision: number | null; select: (revision: number | null) => void;
}) {
  const {t} = useLocale();
  const stops: (number | null)[] = [...reviewRevisions(game), null];
  const index = stops.indexOf(revision);
  const label = (stop: number | null) => stop === null ? t("Final position", "终局")
    : t(`Move ${moveNumber(game, stop)}`, `第 ${moveNumber(game, stop)} 手`);
  function navigate(index: number) {
    if (index >= 0 && index < stops.length) select(stops[index]);
  }
  return <nav className="review-navigation" aria-label={t("Your game moves", "你的历史落子")}>
    <div className="timeline-buttons">
      <button aria-label={t("Your first move", "你的第一手")} disabled={index <= 0} onClick={() => navigate(0)}>⇤</button>
      <button aria-label={t("Previous", "上一步")} disabled={index <= 0} onClick={() => navigate(index - 1)}>←</button>
      <input type="range" aria-label={t("Your game moves", "你的历史落子")} min={0} max={stops.length - 1} step={1} value={Math.max(0, index)}
        aria-valuetext={label(revision)} onChange={(event) => navigate(Number(event.target.value))} />
      <button aria-label={t("Next", "下一步")} disabled={index >= stops.length - 1} onClick={() => navigate(index + 1)}>→</button>
      <button aria-label={t("Final position", "终局")} disabled={index >= stops.length - 1} onClick={() => navigate(stops.length - 1)}>⇥</button>
    </div>
  </nav>;
}
