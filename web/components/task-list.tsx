import type { TrackedTask } from "@/lib/types";

const statusName = { queued: "Queued", running: "Running", succeeded: "Completed", failed: "Failed" };

export function TaskList({ entries, busy, refresh, openGame, repeatQuestion }: {
  entries: TrackedTask[];
  busy: boolean;
  refresh: () => void;
  openGame: (gameId: string) => void;
  repeatQuestion: (question: string) => void;
}) {
  if (!entries.length) return null;
  return (
    <section className="tasks-panel" aria-label="Tasks and answers">
      <div className="task-actions"><button disabled={busy} onClick={refresh}>Refresh tasks</button></div>
      {entries.map((entry) => {
        const result = entry.task.kind === "branch" ? entry.task.result?.result : undefined;
        return (
          <article key={entry.task.task_id} className="task-item">
            <div><strong>{entry.purpose === "review" ? "Game review" : entry.purpose === "question" ? entry.question ?? "Review question" : "Replay with hints"}</strong><span className={`task-status ${entry.task.status}`}>{statusName[entry.task.status]}</span></div>
            {entry.task.error && <p role="alert" className="inline-error">{entry.task.error.message}</p>}
            {entry.task.kind === "question" && entry.task.result && <p className="explanation">{entry.task.result.answer}</p>}
            {entry.purpose === "question" && entry.task.status === "failed" && entry.question && <button disabled={busy} onClick={() => repeatQuestion(entry.question!)}>Ask again</button>}
            {entry.purpose === "branch" && result && <p>Black {result.black_count} : White {result.white_count} · {result.winner === "draw" ? "Draw" : result.winner === "X" ? "Black wins" : "White wins"}</p>}
            {entry.purpose === "branch" && (entry.task.status === "queued" || entry.task.status === "running") && <button disabled={busy} onClick={() => openGame(entry.task.game_id)}>View replay</button>}
            {entry.purpose === "branch" && (entry.task.status === "succeeded" || entry.task.status === "failed") && <button disabled={busy} onClick={() => openGame(entry.task.game_id)}>View branch</button>}
          </article>
        );
      })}
    </section>
  );
}
