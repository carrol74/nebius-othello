import type { Review, ReviewEvidence } from "@/lib/types";

export type Practice = { revision: number; coordinate: string | null };
export type Variation = { revision: number; coordinate: string; frame: number };

export function ReviewCoach({ review, selectedRevision, practice, variation, busy, select, startPractice, continueGame, showVariation }: {
  review: Review;
  selectedRevision: number | null;
  practice: Practice | null;
  variation: Variation | null;
  busy: boolean;
  select: (revision: number) => void;
  startPractice: (revision: number) => void;
  continueGame: (revision: number, coordinate: string) => void;
  showVariation: (value: Variation | null) => void;
}) {
  const focused = review.evidence.find((item) => item.revision === selectedRevision);
  const card = review.coaching?.find((item) => item.revision === focused?.revision);
  const activePractice = practice?.revision === focused?.revision ? practice : null;
  const hidden = !!activePractice && activePractice.coordinate === null;
  const picked = focused?.analysis.candidates.find((item) => item.coordinate === activePractice?.coordinate);
  const best = focused?.analysis.candidates.find((item) => item.coordinate === focused?.recommended_move);
  const comparisons = focused?.comparisons ?? [];
  const moves = focused ? [...new Set([focused.actual_move, activePractice?.coordinate ?? focused.actual_move, focused.recommended_move])] : [];
  const activeVariation = variation?.revision === focused?.revision ? variation : null;
  const line = comparisons.find((item) => item.coordinate === activeVariation?.coordinate);

  function comparisonTable(entry: ReviewEvidence) {
    return <div className="table-scroll"><table className="move-comparison">
      <thead><tr><th>Move</th><th>Score</th><th>Opponent replies</th></tr></thead>
      <tbody>{moves.map((move) => {
        const candidate = entry.analysis.candidates.find((item) => item.coordinate === move)!;
        const details = comparisons.find((item) => item.coordinate === move);
        const labels = [move === entry.actual_move ? "Played" : null, move === activePractice?.coordinate ? "Your retry" : null, move === entry.recommended_move ? "Search choice" : null].filter(Boolean);
        return <tr key={move}><td><strong>{move}</strong><span className="comparison-label">{labels.join(" / ")}</span></td><td>{candidate.score}</td><td>{details?.opponent_moves ?? "—"}</td></tr>;
      })}</tbody>
    </table></div>;
  }

  return <div className="review-coach">
    <div className="review-summary">{review.summary_facts?.slice(0, 2).map((item) => <p key={item.id}>{item.text}</p>)}</div>
    {review.key_moves.length > 0 && <div className="decision-picker" aria-label="Key player decisions">
      {review.key_moves.map((entry) => <button key={entry.revision} aria-pressed={focused?.revision === entry.revision} onClick={() => select(entry.revision)}>Position {entry.revision}<span>{entry.stage ?? "Decision"}</span></button>)}
    </div>}
    {focused ? <article className="coach-decision">
      <div className="card-heading"><h3>Position {focused.revision}</h3><button disabled={busy || focused.actor !== review.human_color} onClick={() => startPractice(focused.revision)}>{activePractice ? "Try again" : "Try this position"}</button></div>
      {hidden ? <p className="practice-instruction" role="status">Choose a move on the board. The comparison stays hidden until you choose.</p> : <>
        <p className="comparison-perspective">{focused.actor === "X" ? "Black" : "White"} to move · {focused.analysis.score_kind === "exact" ? "Exact endgame analysis" : "Search estimates"}</p>
        {comparisonTable(focused)}
        {picked && best && <div className="practice-feedback" role="status">
          <p>{picked.score === best.score ? "Your move matches the best search score." : `Your move scores ${best.score - picked.score} below the best search score.`} {picked.score_kind === "exact" ? "This is an exact endgame comparison." : "This is a search estimate, not a guaranteed result."}</p>
          <button className="primary" disabled={busy} onClick={() => continueGame(focused.revision, picked.coordinate)}>Play on from {picked.coordinate}</button>
        </div>}
        {card && <div className="coach-lesson"><h3>{card.lesson.title}</h3>
          {card.facts.filter((item) => !item.id.endsWith(":decision") && !item.id.endsWith(":score")).map((item) => <p key={item.id}>{item.text}</p>)}
          <p>{card.lesson.text}</p><p className="reflection-question">{card.lesson.question}</p>
        </div>}
        {comparisons.length > 0 && <details className="variation-inspector"><summary>Explore search continuations</summary>
          <div className="variation-moves">{moves.map((move) => <button key={move} aria-pressed={activeVariation?.coordinate === move} onClick={() => showVariation({revision: focused.revision, coordinate: move, frame: 1})}>{move}</button>)}</div>
          {activeVariation && line && <><p className="variation-caption">One search continuation · {line.frames.slice(1, activeVariation.frame + 1).map((frame) => frame.coordinate).join(" → ") || "Starting position"}</p>
          </>}
        </details>}
      </>}
    </article> : <p>{review.key_moves.length ? "Select a key decision to explore its analysis." : "No player decisions with multiple legal moves were recorded."}</p>}
    {review.branch_results && review.branch_results.length > 0 && <div className="replay-comparisons">{review.branch_results.map((branch) => <p key={branch.game_id}>Hint replay from position {branch.parent_revision}: Black {branch.result.black_count}, White {branch.result.white_count}. This result applies to that replay.</p>)}</div>}
  </div>;
}
