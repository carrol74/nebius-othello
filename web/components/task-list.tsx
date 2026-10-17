import type { Review, TrackedTask } from "@/lib/types";
import { useLocale } from "@/lib/locale";
import { factText } from "@/lib/review-text";

const statusName = { queued: "Queued", running: "Running", succeeded: "Completed", failed: "Failed" };

export function TaskList({ review, entries, busy, refresh, openGame, repeatQuestion }: {
  review: Review | null;
  entries: TrackedTask[];
  busy: boolean;
  refresh: () => void;
  openGame: (gameId: string) => void;
  repeatQuestion: (question: string) => void;
}) {
  const {locale, t} = useLocale();
  const translatedStatus = {queued: "排队中", running: "进行中", succeeded: "已完成", failed: "失败"};
  if (!entries.length) return null;
  return (
    <details className="tasks-panel"><summary>{t("Answers and replays", "回答与回放")}</summary><section aria-label={t("Tasks and answers", "任务与回答")}>
      <div className="task-actions"><button disabled={busy} onClick={refresh}>{t("Refresh tasks", "刷新任务")}</button></div>
      {entries.map((entry) => {
        const result = entry.task.kind === "branch" ? entry.task.result?.result : undefined;
        const question = locale === "zh" ? entry.question?.replace(/^For position revision (\d+): /, "局面 $1：") : entry.question;
        const answer = entry.task.kind === "question" ? entry.task.result : null;
        const answerFacts = answer?.answer_facts ?? review?.summary_facts?.filter((fact) => answer?.answer.includes(fact.text)) ?? [];
        return (
          <article key={entry.task.task_id} className="task-item">
            <div><strong>{entry.purpose === "review" ? t("Game review", "棋局复盘") : entry.purpose === "question" ? question ?? t("Review question", "复盘问题") : t("Replay with hints", "按提示回放")}</strong><span className={`task-status ${entry.task.status}`}>{locale === "zh" ? translatedStatus[entry.task.status] : statusName[entry.task.status]}</span></div>
            {entry.task.error && <p role="alert" className="inline-error">{entry.task.error.message}</p>}
            {entry.task.kind === "question" && entry.task.result && <div className="explanation">{entry.task.result.format_version !== "grounded-v1" ? t("This answer predates verified coaching. Ask again for a new answer.", "此回答早于经过校验的讲解版本，请重新提问。") : locale === "en" || !review ? entry.task.result.answer : <>
              {answerFacts.map((fact) => <p key={fact.id}>{factText(fact, review, locale)}</p>)}
              {entry.task.result.coaching?.map((card) => <div key={card.revision}>{card.facts.map((fact) => <p key={fact.id}>{factText(fact, review, locale)}</p>)}</div>)}
              {entry.task.result.topic === "unsupported" && <p>已保存的棋局证据无法回答此问题。可以询问落子、提示或对局结果。</p>}
              {!entry.task.result.coaching?.length && !answerFacts.length && entry.task.result.topic !== "unsupported" && <><p>此历史回答的原文为英语。</p><p lang="en">{entry.task.result.answer}</p></>}
            </>}</div>}
            {entry.purpose === "question" && (entry.task.status === "failed" || (entry.task.kind === "question" && entry.task.result && entry.task.result.format_version !== "grounded-v1")) && entry.question && <button disabled={busy} onClick={() => repeatQuestion(entry.question!)}>{t("Ask again", "重新提问")}</button>}
            {entry.purpose === "branch" && result && <p>{t("Black", "黑方")} {result.black_count} : {t("White", "白方")} {result.white_count} · {result.winner === "draw" ? t("Draw", "和棋") : result.winner === "X" ? t("Black wins", "黑方获胜") : t("White wins", "白方获胜")}</p>}
            {entry.purpose === "branch" && (entry.task.status === "queued" || entry.task.status === "running") && <button disabled={busy} onClick={() => openGame(entry.task.game_id)}>{t("View replay", "查看回放")}</button>}
            {entry.purpose === "branch" && (entry.task.status === "succeeded" || entry.task.status === "failed") && <button disabled={busy} onClick={() => openGame(entry.task.game_id)}>{t("View branch", "查看分支")}</button>}
          </article>
        );
      })}
    </section></details>
  );
}
