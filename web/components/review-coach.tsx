import { useState } from "react";
import { useLocale } from "@/lib/locale";
import { captureLineText, cornerName, defenseFeedback, lessonText, otherCornerText, stepText, teachingChoiceLabel, teachingFactText, teachingNote } from "@/lib/teaching-text";
import { comparisonRay, sameTeachingView, teachingView } from "@/lib/lesson-view";
import { positionFactText } from "@/lib/review-text";
import { earlierDecisionText } from "@/lib/earlier-decision";
import type { GameState, LessonView, PositionLesson, QuestionResult, TeachingDefense, TeachingFrame, TeachingMove } from "@/lib/types";

export type Variation = {
  revision: number; coordinate: string; frame: number; lesson_frames: TeachingFrame[];
  assessment: TeachingMove["assessment"];
  focus_square?: string | null; capture_lines?: string[][];
  capture_frame?: number;
  comparison_ray?: {frame: number; squares: string[]};
  exercise?: {defenses: TeachingDefense[]; target: string; attempt: string | null};
};

export function ReviewCoach({game, lesson, variation, pending, busy, showVariation, ask, answer, questionPending, continueGame, replay, practice, findEarlier, revisit}: {
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
  practice: (move: string) => void;
  findEarlier: () => void;
  revisit: (revision: number) => void;
}) {
  const {locale, t} = useLocale();
  const comparison = lesson.comparison;
  const [question, setQuestion] = useState("");
  const item = lesson.evidence;
  const forcedMove = comparison.insight.kind === "forced";
  const activeMove = comparison.choices.find((choice) => choice.coordinate === variation?.coordinate)
    ?? comparison.choices.find((choice) => choice.coordinate === comparison.selected_move) ?? comparison.choices[0];
  const activeVariation = variation?.coordinate === activeMove.coordinate ? variation : null;
  const frames = activeVariation?.lesson_frames ?? activeMove.frames;
  const view = teachingView(activeMove.coordinate, frames, activeVariation?.frame ?? 1);
  const currentAnswer = sameTeachingView(answer?.view, view) ? answer : null;
  const referenceChoice = comparison.choices.find((choice) => choice.coordinate !== activeMove.coordinate);
  const answerEntry = {...item, actual_move: activeMove.coordinate, is_played: activeMove.assessment.is_played,
    recommended_move: referenceChoice?.coordinate ?? activeMove.coordinate,
    score_loss: Math.abs(activeMove.score - (referenceChoice?.score ?? activeMove.score))};
  const answerFacts = [...(currentAnswer?.answer_facts ?? []), ...(currentAnswer?.coaching ?? []).flatMap((card) => card.facts)]
    .filter((fact) => fact.id !== "outcome_limit" && !["score", "endgame"].includes(fact.id.split(":")[1]));
  const answerIncludesEarlier = answerFacts.some((fact) => fact.id.endsWith(':earlier_decision'));
  const earlier = currentAnswer?.earlier_decision ?? lesson.earlier_decision;
  const earlierMoveNumber = earlier?.link ? game.history.filter((event) => event.kind === 'move' && event.revision <= earlier.link!.revision).length + 1 : 0;
  const canDefend = !!variation?.exercise && variation.frame === 2 && !variation.exercise.attempt && !busy;
  const captureFrame = variation?.capture_frame ?? (variation ? variation.lesson_frames.length - 2 : -1);
  const capturePreview = variation && !canDefend && variation.frame === captureFrame && !!variation.capture_lines?.length;

  function explore(choice: TeachingMove, frame = 1) {
    showVariation({revision: lesson.revision, coordinate: choice.coordinate, frame,
      comparison_ray: comparisonRay(comparison),
      assessment: choice.assessment, lesson_frames: choice.frames, focus_square: choice.target,
      capture_lines: choice.continuation_lesson ? [choice.continuation_lesson.capture_line] : choice.capture_lines,
      capture_frame: choice.continuation_lesson ? choice.continuation_lesson.frame_index - 1 : undefined});
  }

  return <div className="position-coach">
    {item.is_played === false && <p>{t("You have not played this turn yet.", "你在这一回合还没有落子。")}</p>}
    <div className="teaching-choices" role="group" aria-label={t("Choose a line to explore", "选择要演示的走法")}>
      {[...comparison.choices].sort((a, b) => Number(b.assessment.is_played) - Number(a.assessment.is_played)).map((choice) => <button key={choice.coordinate} aria-pressed={choice.coordinate === activeMove.coordinate} onClick={() => explore(choice)}>
        {choice.coordinate}<span>{teachingChoiceLabel(choice, locale)}</span>
      </button>)}
    </div>
    <div className="concrete-lesson">{lessonText(comparison, activeMove, locale).map((text, index) => <p key={text} className={index === 0 ? "lesson-question" : undefined}>{text}</p>)}</div>
    {!variation && <button onClick={() => {
      const frame = comparison.insight.witness ? comparison.insight.witness.prefix.length + 1
        : activeMove.continuation_lesson ? activeMove.continuation_lesson.frame_index - 1 : 2;
      explore(activeMove, Math.min(frame, activeMove.frames.length - 1));
    }}>{t("Explore continuation", "查看推演")}</button>}
    {variation && <>
      {canDefend && variation.exercise && <p role="status">{t(`Choose a defense against the ${cornerName(variation.exercise.target, locale)} capture.`, `选择一步，试着守住${cornerName(variation.exercise.target, locale)}。`)}</p>}
      {capturePreview && variation.capture_lines && <p className="capture-explanation">{captureLineText(variation.capture_lines, variation.lesson_frames[captureFrame + 1].actor!, locale)}</p>}
      {otherCornerText(comparison, locale) && <p className="other-corner">{otherCornerText(comparison, locale)}</p>}
      <div className="line-controls" role="group" aria-label={t("Teaching continuation", "教学推演")}>
        <button disabled={canDefend || variation.frame === 0} onClick={() => showVariation({...variation, frame: variation.frame - 1})}>{t("Previous step", "上一步")}</button>
        <span>{variation.frame}/{variation.lesson_frames.length - 1}</span>
        <button disabled={canDefend || variation.frame === variation.lesson_frames.length - 1} onClick={() => showVariation({...variation, frame: variation.frame + 1})}>{variation.exercise?.attempt && variation.frame === 3 ? t("See the reply", "看对手应对") : t("Next step", "下一步")}</button>
        <button onClick={() => showVariation(null)}>{t("Back to your move", "返回你的落子")}</button>
      </div>
      {variation.exercise?.attempt && variation.frame >= 3 && <>
        <p className="defense-feedback">{defenseFeedback(variation.coordinate, variation.exercise.attempt, variation.exercise.target, locale)}</p>
        <button onClick={() => showVariation({...variation, frame: 2, exercise: {...variation.exercise!, attempt: null}})}>{t("Try another defense", "换一步试试")}</button>
      </>}
    </>}
    {!comparison.decision_contrast && activeMove.continuation_lesson && <button disabled={busy} onClick={() => practice(activeMove.coordinate)}>{t("Try this idea in another position", "换个局面试试")}</button>}
    {comparison.decision_contrast && <button disabled={busy} onClick={() => practice(activeMove.coordinate)}>{t("Compare replies in another position", "换个局面对比回应")}</button>}
    {lesson.earlier_eligible && !answerIncludesEarlier && <div className="earlier-choice">
      {!earlier ? <button disabled={busy} onClick={findEarlier}>{busy ? t('Checking earlier choices…', '正在核验更早的选择…') : t('Could I have defended this corner earlier?', '更早能守住这个角吗？')}</button>
        : earlier.link ? <><p>{earlierDecisionText(earlier.link, earlierMoveNumber, locale)}</p><button disabled={busy} onClick={() => revisit(earlier.link!.revision)}>{t('Inspect that decision', '查看那次选择')}</button></>
          : <p className="muted">{t('No earlier recommendation was found that stops this corner threat.', '没有找到能防住这次抢角的更早推荐走法。')}</p>}
    </div>}
    {!forcedMove && activeMove.kind === "corner_forced" && activeMove.defense_lines.length > 0 && <button disabled={busy} onClick={() => showVariation({
      revision: lesson.revision, coordinate: activeMove.coordinate, frame: 2, lesson_frames: activeMove.frames,
      assessment: activeMove.assessment,
      focus_square: activeMove.target, capture_lines: activeMove.capture_lines,
      exercise: {defenses: activeMove.defense_lines, target: activeMove.target!, attempt: null},
    })}>{t("Try defending", "试着防守")}</button>}
    {pending && <p className="muted" role="status">{t("The coach is choosing what to focus on…", "正在为这个局面选择讲解重点…")}</p>}
    <form className="question-form" onSubmit={(event) => {event.preventDefault(); if (question.trim()) {ask(question.trim(), view); setQuestion("");}}}>
      <div><input aria-label={t("Ask about this position", "询问这个局面")} value={question} maxLength={1800} onChange={(event) => setQuestion(event.target.value)} placeholder={t("Why this move? Ask a question…", "对这一步有疑问？继续提问…")} /><button disabled={busy || questionPending || !question.trim()}>{questionPending ? t("Answering…", "回答中…") : t("Ask", "提问")}</button></div>
    </form>
    {currentAnswer && <div className="position-answer" role="status">{currentAnswer.topic === "unsupported" ? t("The saved evidence cannot answer that question. Ask about this position or its moves.", "已保存的证据无法回答这个问题，可以询问当前局面和落点。") : !answerFacts.length ? t("Play this position to the end in a branch, then compare the results.", "从这个局面创建分支，下到终局后再比较结果。") : [...new Map(answerFacts.map((fact) => [fact.id, fact])).values()].map((fact) => <p key={fact.id}>{
      fact.id.endsWith(":earlier_decision") && earlier?.link ? earlierDecisionText(earlier.link, earlierMoveNumber, locale)
        : fact.id.endsWith(":view") ? t(`${view.selected_move} continuation: ${view.line.length ? stepText(frames[view.line.length], locale) : "before the move"}`, `${view.selected_move} 走法：${view.line.length ? stepText(frames[view.line.length], locale) : "落子前的局面"}`)
        : fact.id === "result" && game.result ? t(`Final: Black ${game.result.black_count}, White ${game.result.white_count}.`, `终局：黑方 ${game.result.black_count}，白方 ${game.result.white_count}。`)
        : fact.id === "adoption" ? t(`You followed ${lesson.hint_adoption.adopted_turns} of ${lesson.hint_adoption.shown_turns} displayed hints.`, `显示过提示的 ${lesson.hint_adoption.shown_turns} 个回合中，你采用了 ${lesson.hint_adoption.adopted_turns} 次提示。`)
        : teachingFactText(comparison, fact.id, locale) ?? positionFactText(fact, answerEntry, locale, activeMove.assessment)
    }</p>)}</div>}
    {answerIncludesEarlier && earlier?.link && <button disabled={busy} onClick={() => revisit(earlier.link!.revision)}>{t('Inspect that decision', '查看那次选择')}</button>}
    <details className="lesson-tools"><summary>{t("Play from this position", "从这个局面继续")}</summary><div className="branch-actions"><button disabled={busy} onClick={() => continueGame(lesson.revision)}>{t("Play a new branch", "创建对局分支")}</button><button disabled={busy} onClick={() => replay(lesson.revision)}>{t("Replay with hints", "按提示回放")}</button></div></details>
    <p className="teaching-note">{teachingNote(locale)}</p>
  </div>;
}
