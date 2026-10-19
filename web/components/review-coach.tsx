import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useLocale } from "@/lib/locale";
import { comparisonTakeaway, lessonText, teachingChoiceLabel } from "@/lib/teaching-text";
import { positionFactText } from "@/lib/review-text";
import type { GameState, PositionLesson, QuestionResult, TeachingComparison, TeachingDefense, TeachingFrame } from "@/lib/types";

export type Variation = {
  revision: number; coordinate: string; frame: number; lesson_frames: TeachingFrame[];
  focus_square?: string | null; capture_lines?: string[][];
  exercise?: {defenses: TeachingDefense[]; target: string; attempt: string | null};
};

export function ReviewCoach({game, lesson, variation, pending, busy, showVariation, ask, answer, questionPending, continueGame, replay, revisit}: {
  game: GameState;
  lesson: PositionLesson;
  variation: Variation | null;
  pending: boolean;
  busy: boolean;
  showVariation: (value: Variation | null) => void;
  ask: (question: string) => void;
  answer: QuestionResult | null;
  questionPending: boolean;
  continueGame: (revision: number) => void;
  replay: (revision: number) => void;
  revisit: (revision: number) => void;
}) {
  const {locale, t} = useLocale();
  const [comparison, setComparison] = useState<TeachingComparison>(lesson.comparison);
  const initialComparison = useRef(lesson.comparison);
  const [question, setQuestion] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const comparisonRequest = useRef<AbortController | null>(null);
  const item = lesson.evidence;
  const legalMoveCount = item.analysis.candidates.length;
  const forcedMove = legalMoveCount === 1;
  const activeMove = comparison.choices.find((choice) => choice.coordinate === variation?.coordinate)
    ?? comparison.choices.find((choice) => choice.coordinate === comparison.selected_move) ?? comparison.choices[0];
  const activeVariation = variation?.coordinate === activeMove.coordinate ? variation : null;
  const frames = activeVariation?.lesson_frames ?? activeMove.frames;
  const takeaway = forcedMove ? t("To study a choice you could change, return to an earlier turn with more than one legal move.", "想学习可以调整的选择，请回看更早有多个合法落点的回合。") : comparisonTakeaway(comparison, locale);
  const card = lesson.coaching?.[0];
  const focusFact = card?.lesson_id !== "comparison" ? card?.facts.find((fact) => fact.topic === card.lesson_id && !fact.id.endsWith(":score") && !fact.id.endsWith(":decision")) : null;
  const answerFacts = [...(answer?.answer_facts ?? []), ...(answer?.coaching ?? []).flatMap((card) => card.facts)];

  useEffect(() => {
    const initial = initialComparison.current;
    const first = initial.choices.find((choice) => choice.coordinate === initial.selected_move)!;
    showVariation({revision: initial.revision, coordinate: first.coordinate, frame: 1,
      lesson_frames: first.frames, focus_square: first.target, capture_lines: first.capture_lines});
  }, [showVariation]);
  useEffect(() => () => comparisonRequest.current?.abort(), []);

  function demonstrate(frame: number) {
    showVariation(activeVariation ? {...activeVariation, frame} : {
      revision: lesson.revision, coordinate: activeMove.coordinate, frame,
      lesson_frames: activeMove.frames, focus_square: activeMove.target, capture_lines: activeMove.capture_lines,
    });
  }

  async function compare(coordinate: string) {
    comparisonRequest.current?.abort();
    const controller = new AbortController();
    comparisonRequest.current = controller;
    setLoading(true); setError(null);
    try {
      const next = await api<TeachingComparison>(`/games/${game.game_id}/lessons/compare?revision=${lesson.revision}&move=${coordinate}`, undefined, controller.signal);
      if (controller.signal.aborted) return;
      setComparison(next);
      const first = next.choices.find((choice) => choice.coordinate === coordinate)!;
      showVariation({revision: next.revision, coordinate, frame: 1,
        lesson_frames: first.frames, focus_square: first.target, capture_lines: first.capture_lines});
    } catch (failure) { if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : t("Could not compare this move", "无法对比这个落点")); }
    finally { if (!controller.signal.aborted) setLoading(false); }
  }

  return <div className="position-coach">
    <div className="teaching-choices" role="group" aria-label={forcedMove ? t("Forced move", "唯一合法落点") : t("Compare moves", "对比落点")}>
      {comparison.choices.map((choice) => <button key={choice.coordinate} disabled={loading} aria-pressed={choice.coordinate === activeMove.coordinate} onClick={() => showVariation({revision: lesson.revision, coordinate: choice.coordinate, frame: 1, lesson_frames: choice.frames, focus_square: choice.target, capture_lines: choice.capture_lines})}>
        {choice.coordinate}<span>{teachingChoiceLabel(item, choice.coordinate, locale)}</span>
      </button>)}
    </div>
    <div className="concrete-lesson">{lessonText(comparison, activeMove, locale, legalMoveCount).map((text) => <p key={text}>{text}</p>)}</div>
    {!forcedMove && activeMove.kind === "line" && focusFact && <p>{positionFactText(focusFact, item, locale)}</p>}
    {takeaway && <p className="concrete-takeaway">{takeaway}</p>}
    {forcedMove && lesson.previous_decision_revision != null && <button disabled={busy} onClick={() => revisit(lesson.previous_decision_revision!)}>{t("Review the last turn with a choice", "回看上一次有选择的回合")}</button>}
    <div className="teaching-steps" role="group" aria-label={t("Demonstration steps", "落子演示步骤")}>
      {frames.slice(1).map((frame, index) => <button key={index} aria-pressed={activeVariation?.frame === index + 1} onClick={() => demonstrate(index + 1)}><small>{index + 1}</small>{frame.actor === "X" ? t("Black", "黑方") : t("White", "白方")} <strong>{frame.coordinate === "pass" ? t("Pass", "跳过") : frame.coordinate}</strong></button>)}
    </div>
    {!forcedMove && activeMove.kind === "corner_forced" && activeMove.defense_lines.length > 0 && <button disabled={busy} onClick={() => showVariation({
      revision: lesson.revision, coordinate: activeMove.coordinate, frame: 2, lesson_frames: activeMove.frames,
      focus_square: activeMove.target, capture_lines: activeMove.capture_lines,
      exercise: {defenses: activeMove.defense_lines, target: activeMove.target!, attempt: null},
    })}>{t("Try defending", "试着防守")}</button>}
    {pending && <p className="muted" role="status">{t("The coach is choosing what to focus on…", "正在为这个局面选择讲解重点…")}</p>}
    {!forcedMove && <details className="lesson-tools"><summary>{t("Compare another move", "比较其他落点")}</summary>
      <label>{t("Move", "落点")} <select aria-label={t("Move to compare", "要对比的落点")} disabled={loading} value={comparison.selected_move} onChange={(event) => void compare(event.target.value)}>{item.analysis.candidates.map((candidate) => <option key={candidate.coordinate}>{candidate.coordinate}</option>)}</select></label>
      {error && <p role="alert">{error}</p>}
      <table><thead><tr><th>{t("Move", "落点")}</th><th>{t("Search score", "搜索评分")}</th></tr></thead><tbody>{comparison.choices.map((choice) => <tr key={choice.coordinate}><td>{choice.coordinate}</td><td>{choice.score}</td></tr>)}</tbody></table>
      <p className="muted">{t("Scores favor the player to move. Estimates are not win probabilities.", "评分从当前行动方的视角计算，估计值不代表胜率。")}</p>
    </details>}
    <form className="question-form" onSubmit={(event) => {event.preventDefault(); if (question.trim()) {ask(question.trim()); setQuestion("");}}}>
      <div><input aria-label={t("Ask about this position", "询问这个局面")} value={question} maxLength={1800} onChange={(event) => setQuestion(event.target.value)} placeholder={t("Why this move? Ask a question…", "对这一步有疑问？继续提问…")} /><button disabled={busy || questionPending || !question.trim()}>{questionPending ? t("Answering…", "回答中…") : t("Ask", "提问")}</button></div>
    </form>
    {answer && <div className="position-answer" role="status">{answer.topic === "unsupported" ? t("The saved evidence cannot answer that question. Ask about this position or its moves.", "已保存的证据无法回答这个问题，可以询问当前局面和落点。") : locale === "en" ? answer.answer : [...new Map(answerFacts.map((fact) => [fact.id, fact])).values()].map((fact) => <p key={fact.id}>{
      fact.id === "outcome_limit" ? "更高的搜索评分不保证获胜，分支对局的结果只适用于那一次对弈。" : fact.id === "result" && game.result ? `终局：黑方 ${game.result.black_count}，白方 ${game.result.white_count}。` : fact.id === "adoption" ? `显示过提示的 ${lesson.hint_adoption.shown_turns} 个回合中，你采用了 ${lesson.hint_adoption.adopted_turns} 次提示。` : positionFactText(fact, item, locale)
    }</p>)}</div>}
    <details className="lesson-tools"><summary>{t("Play from this position", "从这个局面继续")}</summary><div className="branch-actions"><button disabled={busy} onClick={() => continueGame(lesson.revision)}>{t("Play a new branch", "创建对局分支")}</button><button disabled={busy} onClick={() => replay(lesson.revision)}>{t("Replay with hints", "按提示回放")}</button></div></details>
  </div>;
}
