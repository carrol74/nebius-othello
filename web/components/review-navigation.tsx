import { useLocale } from "@/lib/locale";
import { reviewRevisions } from "@/lib/game-view";
import type { GameState, Task } from "@/lib/types";

export function ReviewNavigation({game, revision, select, keyMoves, reviewTask}: {
  game: GameState; revision: number; select: (revision: number) => void;
  keyMoves: number[] | undefined; reviewTask: Task | undefined;
}) {
  const {t} = useLocale();
  const revisions = reviewRevisions(game);
  const index = revisions.indexOf(revision);
  function navigate(index: number) {
    const revision = revisions[index];
    if (revision !== undefined) select(revision);
  }
  if (!revisions.length) return null;
  return <nav className="review-navigation" aria-label={t("Your game moves", "你的历史落子")}>
    <div className="timeline-buttons">
      <button aria-label={t("Your first move", "你的第一手")} disabled={index <= 0} onClick={() => navigate(0)}>⇤</button>
      <button aria-label={t("Your previous move", "你的上一手")} disabled={index <= 0} onClick={() => navigate(index - 1)}>←</button>
      <input type="range" aria-label={t("Your game moves", "你的历史落子")} min={0} max={revisions.length - 1} step={1} value={Math.max(0, index)}
        aria-valuetext={t(`Your move ${index + 1} of ${revisions.length}`, `你的第 ${index + 1} 手，共 ${revisions.length} 手`)}
        onChange={(event) => navigate(Number(event.target.value))} />
      <button aria-label={t("Your next move", "你的下一手")} disabled={index >= revisions.length - 1} onClick={() => navigate(index + 1)}>→</button>
      <button aria-label={t("Your last move", "你的最后一手")} disabled={index >= revisions.length - 1} onClick={() => navigate(revisions.length - 1)}>⇥</button>
    </div>
    {keyMoves && keyMoves.length > 0 ? <div className="key-moves" role="group" aria-label={t("Moves worth reviewing", "值得复盘的几步")}>
      <span>{t("Worth reviewing", "值得复盘")}</span>
      {keyMoves.map((value) => {
        const move = game.history.find((event) => event.revision === value + 1 && event.kind === "move");
        return <button key={value} aria-pressed={value === revision} onClick={() => select(value)}>
          {t(`Move ${revisions.indexOf(value) + 1}`, `你的第 ${revisions.indexOf(value) + 1} 手`)} {move?.coordinate}
        </button>;
      })}
    </div>
      : reviewTask?.status === "failed" ? <p className="inline-error" role="alert">{reviewTask.error?.message}</p>
      : game.status === "finished" && <p className="muted key-moves-status" role="status">{t("Finding the moves worth reviewing…", "正在找出值得复盘的几步…")}</p>}
  </nav>;
}
