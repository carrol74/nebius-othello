import type { Review } from "@/lib/types";

const colorName = (color: "X" | "O") => color === "X" ? "Black" : "White";

export function ReviewDetails({ review, selectRevision }: { review: Review; selectRevision: (revision: number) => void }) {
  return (
    <div className="review-details">
      <details>
        <summary>Move analysis · {review.evidence.length} moves</summary>
        <div className="evidence-list">
          {[...review.evidence].sort((a, b) => b.score_loss - a.score_loss).map((entry) => (
            <article key={entry.revision} className="evidence-card">
              <div className="card-heading">
                <strong>{colorName(entry.actor)} · {entry.actual_move}</strong>
                <button onClick={() => selectRevision(entry.revision)}>View position before move</button>
              </div>
              <p>Recommended {entry.recommended_move} · Score loss {entry.score_loss.toFixed(2)}</p>
              <div className="table-scroll">
                <table>
                  <thead><tr><th>Candidate</th><th>Score ({colorName(entry.analysis.score_perspective)} perspective)</th><th>Type</th><th>Continuation</th></tr></thead>
                  <tbody>{entry.analysis.candidates.map((candidate) => (
                    <tr key={candidate.coordinate}>
                      <td>{candidate.coordinate}{candidate.coordinate === entry.recommended_move ? " · Recommended" : ""}</td>
                      <td>{candidate.score.toFixed(2)}</td>
                      <td>{candidate.score_kind === "exact" ? "Exact" : "Estimate"}</td>
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
        <summary>Hints followed · {review.hint_adoption.adopted_turns} / {review.hint_adoption.shown_turns} turns</summary>
        {review.hints.length > 0 ? (
          <div className="table-scroll"><table>
            <thead><tr><th>Position</th><th>Recommended move</th><th>Played</th></tr></thead>
            <tbody>{review.hints.map((hint) => {
              const event = review.evidence.find((entry) => entry.shown_hint_ids.includes(hint.hint_id));
              return <tr key={hint.hint_id}><td>{hint.revision}</td><td>{hint.recommended_move}</td><td>{event ? `${event.actual_move}${event.actual_move === hint.recommended_move ? " · Followed" : " · Different move"}` : "No player move after this hint"}</td></tr>;
            })}</tbody>
          </table></div>
        ) : <p>No hints used</p>}
      </details>
      {review.automatic_hint_moves.length > 0 && <details>
        <summary>Hint replay · {review.automatic_hint_moves.length} moves</summary>
        <div className="table-scroll"><table>
          <thead><tr><th>Position</th><th>Played move</th><th>Search level</th></tr></thead>
          <tbody>{review.automatic_hint_moves.map((entry) => <tr key={entry.hint_id}>
            <td>{entry.revision}</td><td>{entry.coordinate}</td><td>{entry.analysis_settings.level}</td>
          </tr>)}</tbody>
        </table></div>
      </details>}
    </div>
  );
}
