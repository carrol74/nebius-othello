import type { Review } from "@/lib/types";

const colorName = (color: "X" | "O") => color === "X" ? "黑方" : "白方";

export function ReviewDetails({ review, selectRevision }: { review: Review; selectRevision: (revision: number) => void }) {
  return (
    <div className="review-details">
      <details>
        <summary>逐手分析 · {review.evidence.length} 手</summary>
        <div className="evidence-list">
          {[...review.evidence].sort((a, b) => b.score_loss - a.score_loss).map((entry) => (
            <article key={entry.revision} className="evidence-card">
              <div className="card-heading">
                <strong>{colorName(entry.actor)} · {entry.actual_move}</strong>
                <button onClick={() => selectRevision(entry.revision)}>查看落子前局面</button>
              </div>
              <p>推荐 {entry.recommended_move} · 与推荐点差距 {entry.score_loss.toFixed(2)}</p>
              <div className="table-scroll">
                <table>
                  <thead><tr><th>候选点</th><th>评分（{colorName(entry.analysis.score_perspective)}视角）</th><th>性质</th><th>后续变化</th></tr></thead>
                  <tbody>{entry.analysis.candidates.map((candidate) => (
                    <tr key={candidate.coordinate}>
                      <td>{candidate.coordinate}{candidate.coordinate === entry.recommended_move ? " · 推荐" : ""}</td>
                      <td>{candidate.score.toFixed(2)}</td>
                      <td>{candidate.score_kind === "exact" ? "精确" : "估计"}</td>
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
        <summary>提示采用 · {review.hint_adoption.adopted_turns} / {review.hint_adoption.shown_turns} 回合</summary>
        {review.hints.length > 0 ? (
          <div className="table-scroll"><table>
            <thead><tr><th>局面</th><th>推荐点</th><th>实际选择</th></tr></thead>
            <tbody>{review.hints.map((hint) => {
              const event = review.evidence.find((entry) => entry.shown_hint_ids.includes(hint.hint_id));
              return <tr key={hint.hint_id}><td>{hint.revision}</td><td>{hint.recommended_move}</td><td>{event ? `${event.actual_move}${event.actual_move === hint.recommended_move ? " · 已采用" : " · 选择其他点"}` : "该提示之后没有玩家落子"}</td></tr>;
            })}</tbody>
          </table></div>
        ) : <p>未使用提示</p>}
      </details>
      {review.automatic_hint_moves.length > 0 && <details>
        <summary>提示重演 · {review.automatic_hint_moves.length} 手</summary>
        <div className="table-scroll"><table>
          <thead><tr><th>局面</th><th>采用点</th><th>搜索等级</th></tr></thead>
          <tbody>{review.automatic_hint_moves.map((entry) => <tr key={entry.hint_id}>
            <td>{entry.revision}</td><td>{entry.coordinate}</td><td>{entry.analysis_settings.level}</td>
          </tr>)}</tbody>
        </table></div>
      </details>}
    </div>
  );
}
