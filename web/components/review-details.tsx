import type { Review } from "@/lib/types";
import { useLocale } from "@/lib/locale";

export function ReviewDetails({ review, selectRevision }: { review: Review; selectRevision: (revision: number) => void }) {
  const {t} = useLocale();
  const colorName = (color: "X" | "O") => color === "X" ? t("Black", "黑方") : t("White", "白方");
  return (
    <div className="review-details">
      <details>
        <summary>{t("Move analysis", "全部落子分析")} · {review.evidence.length} {t("moves", "步")}</summary>
        <div className="evidence-list">
          {[...review.evidence].sort((a, b) => b.score_loss - a.score_loss).map((entry) => (
            <article key={entry.revision} className="evidence-card">
              <div className="card-heading">
                <strong>{colorName(entry.actor)} · {entry.actual_move}</strong>
                <button onClick={() => selectRevision(entry.revision)}>{t("View position before move", "查看落子前局面")}</button>
              </div>
              <p>{t("Recommended", "推荐")} {entry.recommended_move} · {t("Score difference", "评分差距")} {entry.score_loss.toFixed(2)}</p>
              <div className="table-scroll">
                <table>
                  <thead><tr><th>{t("Candidate", "落点")}</th><th>{t("Score", "评分")} ({colorName(entry.analysis.score_perspective)})</th><th>{t("Type", "类型")}</th><th>{t("Continuation", "续着")}</th></tr></thead>
                  <tbody>{entry.analysis.candidates.map((candidate) => (
                    <tr key={candidate.coordinate}>
                      <td>{candidate.coordinate}{candidate.coordinate === entry.recommended_move ? t(" · Recommended", " · 推荐") : ""}</td>
                      <td>{candidate.score.toFixed(2)}</td>
                      <td>{candidate.score_kind === "exact" ? t("Exact", "精确") : t("Estimate", "估计")}</td>
                      <td>{candidate.principal_variation.join(" → ") || "—"}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            </article>
          ))}
        </div>
      </details>
      <details>
        <summary>{t("Hints followed", "提示采用")} · {review.hint_adoption.adopted_turns} / {review.hint_adoption.shown_turns} {t("turns", "回合")}</summary>
        {review.hints.length > 0 ? (
          <div className="table-scroll"><table>
            <thead><tr><th>{t("Position", "局面")}</th><th>{t("Recommended move", "推荐落点")}</th><th>{t("Played", "实际落子")}</th></tr></thead>
            <tbody>{review.hints.map((hint) => {
              const event = review.evidence.find((entry) => entry.shown_hint_ids.includes(hint.hint_id));
              return <tr key={hint.hint_id}><td>{hint.revision}</td><td>{hint.recommended_move}</td><td>{event ? `${event.actual_move}${event.actual_move === hint.recommended_move ? t(" · Followed", " · 已采用") : t(" · Different move", " · 未采用")}` : t("No player move after this hint", "此提示后没有落子")}</td></tr>;
            })}</tbody>
          </table></div>
        ) : <p>{t("No hints used", "没有使用提示")}</p>}
      </details>
      {review.automatic_hint_moves.length > 0 && <details>
        <summary>{t("Hint replay", "提示回放")} · {review.automatic_hint_moves.length} {t("moves", "步")}</summary>
        <div className="table-scroll"><table>
          <thead><tr><th>{t("Position", "局面")}</th><th>{t("Played move", "实际落子")}</th><th>{t("Search level", "搜索深度")}</th></tr></thead>
          <tbody>{review.automatic_hint_moves.map((entry) => <tr key={entry.hint_id}>
            <td>{entry.revision}</td><td>{entry.coordinate}</td><td>{entry.analysis_settings.level}</td>
          </tr>)}</tbody>
        </table></div>
      </details>}
    </div>
  );
}
