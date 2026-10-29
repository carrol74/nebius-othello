import { useLocale } from "@/lib/locale";
import { moveNumber } from "@/lib/game-view";
import { coachingFailure, reasonLabel } from "@/lib/teaching-text";
import type { GameState, GameSummary, KeyMove, Task } from "@/lib/types";

export function GameSummaryCard({game, keyMoves, summary, pending, busy, select, retry, reviewTask}: {
  game: GameState; keyMoves: KeyMove[] | undefined; summary: GameSummary | null | undefined;
  pending: boolean; busy: boolean; select: (revision: number) => void; retry: () => void;
  reviewTask: Task | undefined;
}) {
  const {locale, t} = useLocale();
  const failure = summary?.status === "failed" ? coachingFailure(summary.error_code, summary.error, "summary", locale) : null;
  const focusRevision = summary?.status === "ready" ? summary.facts?.find((fact) => fact.revision != null)?.revision : null;
  const orderedMoves = keyMoves ? [...keyMoves].sort((a, b) => Number(b.revision === focusRevision) - Number(a.revision === focusRevision)) : [];
  return <section className="game-summary" aria-label={t("Game summary", "整盘总结")}>
    <h2>{t("Game summary", "整盘总结")}</h2>
    {!keyMoves ? reviewTask?.status === "failed"
      ? <p className="inline-error" role="alert">{reviewTask.error?.message}</p>
      : <p className="muted" role="status">{t("Analyzing this game…", "正在分析这盘棋…")}</p>
      : !game.history.some((event) => event.kind === "move" && event.actor === game.human_color)
        ? <p>{t("You have no played moves to review in this game.", "你在这盘对局中没有落子可供复盘。")}</p> : <>
          {summary?.status === "ready" ? <div className="coach-note">{summary.text && <SummaryText text={summary.text} />}</div>
            : pending || summary?.status === "pending" ? <p className="muted" role="status">{t("Nemotron is summarizing this game…", "Nemotron 正在总结这盘棋…")}</p>
              : failure && <div className="summary-failure">
                <p className={failure.quiet ? "muted" : "inline-error"} role={failure.quiet ? "status" : "alert"}>{failure.text}</p>
                {summary?.error_code !== "REVIEW_NOT_CONFIGURED" && <button disabled={busy} onClick={retry}>{t("Summarize again", "重新总结")}</button>}
              </div>}
          {!!keyMoves.length && <div className="summary-moves" role="group" aria-label={t("Moves worth reviewing", "值得复盘的几步")}>
            {orderedMoves.map((move) => <button key={move.revision} onClick={() => select(move.revision)}>
              <strong>{t(`Move ${moveNumber(game, move.revision)} ${move.actual_move}`, `第 ${moveNumber(game, move.revision)} 手 ${move.actual_move}`)}</strong>
              {reasonLabel(move.reason, locale) && <span>{reasonLabel(move.reason, locale)}</span>}
            </button>)}
          </div>}
        </>}
  </section>;
}

function SummaryText({text}: {text: string}) {
  return <>{text.split("\n\n").map((paragraph, index) => <p key={index}>{paragraph}</p>)}</>;
}

// Shows the finished summary on hover or focus while a single move is open
export function SummaryPeek({summary}: {summary: GameSummary | null | undefined}) {
  const {t} = useLocale();
  if (summary?.status !== "ready" || !summary.text) return null;
  return <span className="peek">
    <button type="button" className="icon-button" aria-label={t("Game summary", "整盘总结")} aria-describedby="summary-peek-text"
      onKeyDown={(event) => {if (event.key === "Escape") event.currentTarget.blur();}}>i</button>
    <div className="peek-bubble summary-peek-bubble" id="summary-peek-text" role="tooltip"><SummaryText text={summary.text} /></div>
  </span>;
}
