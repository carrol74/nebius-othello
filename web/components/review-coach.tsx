import { useState } from "react";
import { useLocale } from "@/lib/locale";
import { captureLineText, cornerName, defenseFeedback, lessonText, otherCornerText, stepText, teachingChoiceLabel, teachingNote } from "@/lib/teaching-text";
import { comparisonRay, sameTeachingView, teachingView } from "@/lib/lesson-view";
import { toolCallText } from "@/lib/review-text";
import { earlierDecisionText } from "@/lib/earlier-decision";
import type { CoachToolCall, GameState, LessonView, PositionLesson, QuestionResult, TeachingDefense, TeachingFrame, TeachingMove } from "@/lib/types";

export type Variation = {
  revision: number; coordinate: string; frame: number; lesson_frames: TeachingFrame[];
  assessment: TeachingMove["assessment"];
  focus_square?: string | null; capture_lines?: string[][];
  capture_frame?: number;
  comparison_ray?: {frame: number; squares: string[]};
  exercise?: {defenses: TeachingDefense[]; target: string; attempt: string | null};
};

function CoachNote({texts, calls}: {texts: string[]; calls: CoachToolCall[]}) {
  const {locale, t} = useLocale();
  const steps = calls.map((call) => toolCallText(call, locale)).filter((step): step is string => !!step);
  return <div className="coach-note">
    {texts.map((text) => <p key={text}>{text}</p>)}
    {steps.length > 0 && <p className="coach-meta">{t("Checked with the rules engine: ", "用规则引擎核验：")}{steps.join(t("; ", "；"))}</p>}
  </div>;
}

export function ReviewCoach({game, lesson, variation, pending, busy, showVariation, ask, answer, asked, questionPending, continueGame, replay, findEarlier, revisit}: {
  game: GameState;
  lesson: PositionLesson;
  variation: Variation | null;
  pending: boolean;
  busy: boolean;
  showVariation: (value: Variation | null) => void;
  ask: (question: string, view: LessonView) => void;
  answer: QuestionResult | null;
  asked: string | undefined;
  questionPending: boolean;
  continueGame: (revision: number) => void;
  replay: (revision: number) => void;
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
  const answerIncludesEarlier = [...(currentAnswer?.answer_facts ?? []), ...(currentAnswer?.coaching ?? []).flatMap((card) => card.facts)]
    .some((fact) => fact.id.endsWith(':earlier_decision'));
  const earlier = currentAnswer?.earlier_decision ?? lesson.earlier_decision;
  const coachTexts = [lesson.answer, ...(lesson.coaching ?? []).map((card) => card.text)].filter((text): text is string => !!text);
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
    {coachTexts.length > 0 && <CoachNote texts={coachTexts} calls={lesson.tool_calls ?? []} />}
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
    {pending && <p className="muted" role="status">{t("Nemotron is checking this position…", "Nemotron 正在核验这个局面…")}</p>}
    {currentAnswer && <div className="position-answer" role="status">
      {asked && <p className="asked">{t("You asked: ", "你问：")}{asked}</p>}
      <CoachNote texts={[currentAnswer.answer]} calls={currentAnswer.tool_calls ?? []} />
    </div>}
    <form className="question-form" onSubmit={(event) => {event.preventDefault(); if (question.trim()) {ask(question.trim(), view); setQuestion("");}}}>
      <div><input aria-label={t("Ask about this position", "询问这个局面")} value={question} maxLength={1800} onChange={(event) => setQuestion(event.target.value)} placeholder={t("Why this move? Ask a question…", "对这一步有疑问？继续提问…")} /><button disabled={busy || questionPending || !question.trim()}>{questionPending ? t("Answering…", "回答中…") : t("Ask", "提问")}</button></div>
    </form>
    {answerIncludesEarlier && earlier?.link && <button disabled={busy} onClick={() => revisit(earlier.link!.revision)}>{t('Inspect that decision', '查看那次选择')}</button>}
    <details className="lesson-tools"><summary>{t("Play from this position", "从这个局面继续")}</summary><div className="branch-actions"><button disabled={busy} onClick={() => continueGame(lesson.revision)}>{t("Play a new branch", "创建对局分支")}</button><button disabled={busy} onClick={() => replay(lesson.revision)}>{t("Replay with hints", "按提示回放")}</button></div></details>
    <p className="teaching-note">{teachingNote(locale)}</p>
  </div>;
}
