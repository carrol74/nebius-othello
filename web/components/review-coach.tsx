import { useEffect, useRef, useState } from "react";
import { useLocale } from "@/lib/locale";
import { comparisonTakeaway, lessonText, stepText, teachingChoiceLabel, teachingFactText } from "@/lib/teaching-text";
import { sameTeachingView, teachingView } from "@/lib/lesson-view";
import { positionFactText } from "@/lib/review-text";
import type { GameState, LessonView, PositionLesson, QuestionResult, TeachingDefense, TeachingFrame, TeachingMove } from "@/lib/types";

export type Variation = {
  revision: number; coordinate: string; frame: number; lesson_frames: TeachingFrame[];
  assessment: TeachingMove["assessment"];
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
  ask: (question: string, view: LessonView) => void;
  answer: QuestionResult | null;
  questionPending: boolean;
  continueGame: (revision: number) => void;
  replay: (revision: number) => void;
  revisit: (revision: number) => void;
}) {
  const {locale, t} = useLocale();
  const comparison = lesson.comparison;
  const initialComparison = useRef(lesson.comparison);
  const [question, setQuestion] = useState("");
  const item = lesson.evidence;
  const forcedMove = comparison.insight.kind === "forced";
  const activeMove = comparison.choices.find((choice) => choice.coordinate === variation?.coordinate)
    ?? comparison.choices.find((choice) => choice.coordinate === comparison.selected_move) ?? comparison.choices[0];
  const activeVariation = variation?.coordinate === activeMove.coordinate ? variation : null;
  const frames = activeVariation?.lesson_frames ?? activeMove.frames;
  const view = teachingView(activeMove.coordinate, frames, activeVariation?.frame ?? 0);
  const currentAnswer = sameTeachingView(answer?.view, view) ? answer : null;
  const referenceChoice = comparison.choices.find((choice) => choice.coordinate !== activeMove.coordinate);
  const answerEntry = {...item, actual_move: activeMove.coordinate, is_played: activeMove.assessment.is_played,
    recommended_move: referenceChoice?.coordinate ?? activeMove.coordinate,
    score_loss: Math.abs(activeMove.score - (referenceChoice?.score ?? activeMove.score))};
  const takeaway = comparisonTakeaway(comparison, locale);
  const answerFacts = [...(answer?.answer_facts ?? []), ...(answer?.coaching ?? []).flatMap((card) => card.facts)];

  useEffect(() => {
    const initial = initialComparison.current;
    const first = initial.choices.find((choice) => choice.coordinate === initial.selected_move)!;
    showVariation({revision: initial.revision, coordinate: first.coordinate, frame: 1,
      assessment: first.assessment,
      lesson_frames: first.frames, focus_square: first.target, capture_lines: first.capture_lines});
  }, [showVariation]);

  return <div className="position-coach">
    {item.is_played === false && <p>{t("You have not played this turn yet.", "你在这一回合还没有落子。")}</p>}
    <div className="teaching-choices" role="group" aria-label={t("Choose a line to explore", "选择要演示的走法")}>
      {[...comparison.choices].sort((a, b) => Number(b.assessment.is_played) - Number(a.assessment.is_played)).map((choice) => <button key={choice.coordinate} aria-pressed={choice.coordinate === activeMove.coordinate} onClick={() => showVariation({revision: lesson.revision, coordinate: choice.coordinate, frame: 1, assessment: choice.assessment, lesson_frames: choice.frames, focus_square: choice.target, capture_lines: choice.capture_lines})}>
        {choice.coordinate}<span>{teachingChoiceLabel(choice, locale)}</span>
      </button>)}
    </div>
    <div className="concrete-lesson">{lessonText(comparison, activeMove, locale).map((text) => <p key={text}>{text}</p>)}</div>
    {takeaway && <p className="concrete-takeaway">{takeaway}</p>}
    {forcedMove && lesson.previous_decision_revision != null && <button disabled={busy} onClick={() => revisit(lesson.previous_decision_revision!)}>{t("Review the last turn with a choice", "回看上一次有选择的回合")}</button>}
    {!forcedMove && activeMove.kind === "corner_forced" && activeMove.defense_lines.length > 0 && <button disabled={busy} onClick={() => showVariation({
      revision: lesson.revision, coordinate: activeMove.coordinate, frame: 2, lesson_frames: activeMove.frames,
      assessment: activeMove.assessment,
      focus_square: activeMove.target, capture_lines: activeMove.capture_lines,
      exercise: {defenses: activeMove.defense_lines, target: activeMove.target!, attempt: null},
    })}>{t("Try defending", "试着防守")}</button>}
    {pending && <p className="muted" role="status">{t("The coach is choosing what to focus on…", "正在为这个局面选择讲解重点…")}</p>}
    {comparison.choices.length > 1 && <details className="lesson-tools"><summary>{t("Scores", "评分")}</summary>
      <table><thead><tr><th>{t("Move", "落点")}</th><th>{t("Search score", "搜索评分")}</th></tr></thead><tbody>{comparison.choices.map((choice) => <tr key={choice.coordinate}><td>{choice.coordinate}</td><td>{choice.score}</td></tr>)}</tbody></table>
      <p className="muted">{t("Scores favor the player to move. Estimates are not win probabilities.", "评分从当前行动方的视角计算，估计值不代表胜率。")}</p>
    </details>}
    <form className="question-form" onSubmit={(event) => {event.preventDefault(); if (question.trim()) {ask(question.trim(), view); setQuestion("");}}}>
      <div><input aria-label={t("Ask about this position", "询问这个局面")} value={question} maxLength={1800} onChange={(event) => setQuestion(event.target.value)} placeholder={t("Why this move? Ask a question…", "对这一步有疑问？继续提问…")} /><button disabled={busy || questionPending || !question.trim()}>{questionPending ? t("Answering…", "回答中…") : t("Ask", "提问")}</button></div>
    </form>
    {currentAnswer && <div className="position-answer" role="status">{currentAnswer.topic === "unsupported" ? t("The saved evidence cannot answer that question. Ask about this position or its moves.", "已保存的证据无法回答这个问题，可以询问当前局面和落点。") : locale === "en" ? currentAnswer.answer : [...new Map(answerFacts.map((fact) => [fact.id, fact])).values()].map((fact) => <p key={fact.id}>{
      fact.id.endsWith(":view") ? `${view.selected_move} 走法，${view.line.length ? stepText(frames[view.line.length], locale) : "落子前的局面"}。评分针对起点的选择。` : fact.id === "outcome_limit" ? "更高的搜索评分不保证获胜，分支对局的结果只适用于那一次对弈。" : fact.id === "result" && game.result ? `终局：黑方 ${game.result.black_count}，白方 ${game.result.white_count}。` : fact.id === "adoption" ? `显示过提示的 ${lesson.hint_adoption.shown_turns} 个回合中，你采用了 ${lesson.hint_adoption.adopted_turns} 次提示。` : teachingFactText(comparison, fact.id, locale) ?? positionFactText(fact, answerEntry, locale, activeMove.assessment)
    }</p>)}</div>}
    <details className="lesson-tools"><summary>{t("Play from this position", "从这个局面继续")}</summary><div className="branch-actions"><button disabled={busy} onClick={() => continueGame(lesson.revision)}>{t("Play a new branch", "创建对局分支")}</button><button disabled={busy} onClick={() => replay(lesson.revision)}>{t("Replay with hints", "按提示回放")}</button></div></details>
  </div>;
}
