import type { TrackedTask } from "@/lib/types";

const statusName = { queued: "等待处理", running: "正在处理", succeeded: "已完成", failed: "处理失败" };

export function TaskList({ entries, busy, refresh, openGame, repeatQuestion }: {
  entries: TrackedTask[];
  busy: boolean;
  refresh: () => void;
  openGame: (gameId: string) => void;
  repeatQuestion: (question: string) => void;
}) {
  if (!entries.length) return null;
  return (
    <section className="tasks-panel">
      <div className="card-heading"><span className="section-label">任务与回答</span><button disabled={busy} onClick={refresh}>刷新任务</button></div>
      {entries.map((entry) => {
        const result = entry.task.kind === "branch" ? entry.task.result?.result : undefined;
        return (
          <article key={entry.task.task_id} className="task-item">
            <div><strong>{entry.purpose === "review" ? "终局复盘" : entry.purpose === "question" ? entry.question ?? "复盘追问" : "按提示重演"}</strong><span className={`task-status ${entry.task.status}`}>{statusName[entry.task.status]}</span></div>
            {entry.task.error && <p role="alert" className="inline-error">{entry.task.error.message}</p>}
            {entry.task.kind === "question" && entry.task.result && <p className="explanation">{entry.task.result.answer}</p>}
            {entry.purpose === "question" && entry.task.status === "failed" && entry.question && <button disabled={busy} onClick={() => repeatQuestion(entry.question!)}>重新填写这个问题</button>}
            {entry.purpose === "branch" && result && <p>黑方 {result.black_count} : 白方 {result.white_count} · {result.winner === "draw" ? "和棋" : result.winner === "X" ? "黑方胜" : "白方胜"}</p>}
            {entry.purpose === "branch" && (entry.task.status === "queued" || entry.task.status === "running") && <button disabled={busy} onClick={() => openGame(entry.task.game_id)}>查看重演棋盘</button>}
            {entry.purpose === "branch" && (entry.task.status === "succeeded" || entry.task.status === "failed") && <button disabled={busy} onClick={() => openGame(entry.task.game_id)}>{entry.task.status === "failed" ? "查看已保存的分支" : "查看分支棋谱"}</button>}
          </article>
        );
      })}
    </section>
  );
}
