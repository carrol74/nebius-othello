import { useState } from "react";
import type { ReactNode } from "react";
import { useLocale } from "@/lib/locale";
import { captureLineText, practiceFeedback, practicePrompt, stepNote, stepText, teachingChoiceLabel, teachingNote } from "@/lib/teaching-text";
import { answerMatchesView, canonicalFrames, coachedFrames, displayedTeachingView, lessonFocus, reasonView } from "@/lib/lesson-view";
import { earlierDecisionText } from "@/lib/earlier-decision";
import { moveNumber } from "@/lib/game-view";
import type { CornerPracticeOption, GameState, LessonView, PositionLesson, QuestionResult, TeachingFrame, TeachingMove } from "@/lib/types";

export type Variation = {
  revision: number; coordinate: string; frame: number; lesson_frames: TeachingFrame[];
  assessment: TeachingMove["assessment"];
  focus_square?: string | null; capture_lines?: string[][];
  capture_frame?: number;
  comparison_ray?: {frame: number; squares: string[]};
  key_frame?: number | null;
  // The line is the lesson's own demonstration, so its step notes apply
  canonical?: boolean;
  answerTaskId?: string;
  exercise?: {options: CornerPracticeOption[]; target: string; attempt: string | null};
};

function CoachNote({texts}: {texts: string[]}) {
  return <div className="coach-note">{texts.map((text) => <p key={text}>{text}</p>)}</div>;
}

export function ReviewCoach({game, lesson, variation, pending, busy, showVariation, ask, answer, answerTaskId, asked, questionPending, continueGame, findEarlier, revisit, practice, request}: {
  game: GameState;
  lesson: PositionLesson;
  variation: Variation | null;
  pending: boolean;
  busy: boolean;
  showVariation: (value: Variation | null) => void;
  ask: (question: string, view: LessonView) => void;
  answer: QuestionResult | null;
  answerTaskId: string | undefined;
  asked: string | undefined;
  questionPending: boolean;
  continueGame: (revision: number, line: string[]) => void;
  findEarlier: () => void;
  revisit: (revision: number) => void;
  practice: (move: string) => void;
  request: ReactNode;
}) {
  const {locale, t} = useLocale();
  const comparison = lesson.comparison;
  const [question, setQuestion] = useState("");
  const forcedMove = comparison.insight.kind === "forced";
  const activeMove = comparison.choices.find((choice) => choice.coordinate === variation?.coordinate)
    ?? comparison.choices.find((choice) => choice.coordinate === comparison.selected_move) ?? comparison.choices[0];
  const view = displayedTeachingView(activeMove, variation);
  const displayedFrame = variation?.lesson_frames[variation.frame] ?? activeMove.frames[1];
  const currentAnswer = answerMatchesView(answer?.view, view, answerTaskId, variation?.answerTaskId) ? answer : null;
  const answerIncludesEarlier = [...(currentAnswer?.answer_facts ?? []), ...(currentAnswer?.coaching ?? []).flatMap((card) => card.facts)]
    .some((fact) => fact.id.endsWith(':earlier_decision'));
  const earlier = currentAnswer?.earlier_decision ?? lesson.earlier_decision;
  const coachTexts = [lesson.answer, ...(lesson.coaching ?? []).map((card) => card.text)].filter((text): text is string => !!text);
  const focus = lessonFocus(lesson);
  const answerLine = [...(currentAnswer?.answer_facts ?? []), ...(currentAnswer?.coaching ?? []).flatMap(card => card.facts)]
    .find(fact => (fact.frames?.length ?? 0) > 1)?.frames;
  const earlierMoveNumber = earlier?.link ? moveNumber(game, earlier.link.revision) : 0;
  const practicing = !!variation?.exercise && !variation.exercise.attempt;
  const attempt = variation?.exercise?.options.find((option) => option.coordinate === variation.exercise!.attempt);
  const captureFrame = variation?.capture_frame ?? (variation ? variation.lesson_frames.length - 2 : -1);
  const capturePreview = variation && !practicing && variation.frame === captureFrame && !!variation.capture_lines?.length;

  function explore(choice: TeachingMove, frame?: number, override?: TeachingFrame[], demonstratedAnswerId?: string) {
    const frames = override ?? coachedFrames(lesson, choice);
    const original = comparison.choices.find(move => move.coordinate === choice.coordinate)!;
    const canonical = canonicalFrames(original, frames);
    const reason = canonical ? reasonView(comparison, original) : null;
    showVariation({revision: lesson.revision, coordinate: frames[1]?.coordinate ?? choice.coordinate,
      frame: frame ?? reason?.key_frame ?? 1, canonical, answerTaskId: demonstratedAnswerId,
      comparison_ray: reason?.ray, key_frame: canonical ? reason?.key_frame ?? null : frames.length - 1,
      assessment: choice.assessment, lesson_frames: frames, focus_square: canonical ? choice.target : null,
      capture_lines: canonical ? choice.continuation_lesson ? [choice.continuation_lesson.capture_line] : choice.capture_lines : [],
      capture_frame: canonical && choice.continuation_lesson ? choice.continuation_lesson.frame_index - 1 : undefined});
  }

  return <div className="position-coach">
    <div className="teaching-choices" role="group" aria-label={t("Choose a line to explore", "选择要演示的走法")}>
      {[...comparison.choices].sort((a, b) => Number(b.assessment.is_played) - Number(a.assessment.is_played)).map((choice) => <button key={choice.coordinate} aria-pressed={choice.coordinate === activeMove.coordinate} onClick={() => explore(choice)}>
        {choice.coordinate}<span>{teachingChoiceLabel(choice, locale)}</span>
      </button>)}
    </div>
    {coachTexts.length > 0 && <CoachNote texts={coachTexts} />}
    {pending && <p className="muted" role="status">{t("Nemotron is writing the lesson for this move…", "Nemotron 正在写这一步的讲解…")}</p>}
    {forcedMove && <p className="lesson-question">{t(`${activeMove.coordinate} is the only legal move.`, `${activeMove.coordinate} 是唯一的合法落点。`)}</p>}
    {!variation && <button onClick={() => focus ? explore(focus.choice, focus.frame, focus.choice.frames) : explore(activeMove)}>{(focus?.choice ?? activeMove).frames.length > 2 ? t("Explore continuation", "查看推演") : t("Show on the board", "在棋盘上看")}</button>}
    {request}
    {variation && <>
      {practicing && <p role="status">{practicePrompt(variation.exercise!.options, variation.exercise!.target, locale)}</p>}
      {/* Step 1 of a lesson line is the selected move itself, already shown on its button */}
      {!practicing && (variation.exercise || variation.frame > 1) && <p className="step-text">{stepText(variation.lesson_frames[variation.frame], comparison.actor, locale)}</p>}
      {variation.canonical && stepNote(comparison, activeMove, variation.frame, locale) && <p className="step-note">{stepNote(comparison, activeMove, variation.frame, locale)}</p>}
      {attempt && <p className="defense-feedback">{practiceFeedback(attempt, variation.exercise!.target, comparison.recommended_move, locale)}</p>}
      {capturePreview && attempt && variation.capture_lines && <p className="capture-explanation">{captureLineText(variation.capture_lines, variation.lesson_frames[captureFrame + 1].actor!, comparison.actor, locale)}</p>}
      <div className="line-controls" role="group" aria-label={t("Teaching continuation", "教学推演")}>
        {!practicing && <>
          <button disabled={variation.frame === 1} onClick={() => showVariation({...variation, frame: variation.frame - 1})}>{t("Previous step", "上一步")}</button>
          <span>{variation.frame}/{variation.lesson_frames.length - 1}{variation.key_frame === variation.frame ? t(" · key step", " · 关键一步")
            : variation.frame === 1 && variation.key_frame ? t(` · key step: ${variation.key_frame}`, ` · 关键在第 ${variation.key_frame} 步`) : ""}</span>
          <button disabled={variation.frame === variation.lesson_frames.length - 1} onClick={() => showVariation({...variation, frame: variation.frame + 1})}>{t("Next step", "下一步")}</button>
        </>}
        {attempt && <button onClick={() => showVariation({...variation, frame: 0, lesson_frames: [variation.lesson_frames[0]], capture_lines: [], focus_square: null, exercise: {...variation.exercise!, attempt: null}})}>{t("Try another move", "换一步试试")}</button>}
        <button onClick={() => showVariation(null)}>{variation.exercise ? t("End practice", "结束练习") : t("Back to your move", "返回你的落子")}</button>
      </div>
    </>}
    {lesson.earlier_eligible && !answerIncludesEarlier && <div className="earlier-choice">
      {!earlier ? <button disabled={busy} onClick={findEarlier}>{busy ? t('Checking earlier choices…', '正在核验更早的选择…') : t('Could I have defended this corner earlier?', '更早能守住这个角吗？')}</button>
        : earlier.link ? <><p>{earlierDecisionText(earlier.link, earlierMoveNumber, locale)}</p><button disabled={busy} onClick={() => revisit(earlier.link!.revision)}>{t('Inspect that decision', '查看那次选择')}</button></>
          : <p className="muted">{t('No earlier recommendation was found that stops this corner threat.', '没有找到能防住这次抢角的更早推荐走法。')}</p>}
    </div>}
    {!forcedMove && !variation?.exercise && activeMove.defendable && comparison.insight.kind !== "shared_corner" && <button disabled={busy} onClick={() => practice(activeMove.coordinate)}>{t("Try defending", "试着防守")}</button>}
    {currentAnswer && <div className="position-answer" role="status">
      {asked && <p className="asked">{t("You asked: ", "你问：")}{asked}</p>}
      <CoachNote texts={[currentAnswer.answer]} />
      {answerLine && <button onClick={() => explore(activeMove, answerLine.length - 1, answerLine, answerTaskId)}>{t("Show this explanation", "在棋盘上看这段讲解")}</button>}
    </div>}
    <form className="question-form" onSubmit={(event) => {event.preventDefault(); if (question.trim()) {ask(question.trim(), view); setQuestion("");}}}>
      <div><input aria-label={t("Ask about this position", "询问这个局面")} value={question} maxLength={1800} onChange={(event) => setQuestion(event.target.value)} placeholder={t("Why this move? Ask a question…", "对这一步有疑问？继续提问…")} /><button disabled={busy || questionPending || !question.trim()}>{questionPending ? t("Answering…", "回答中…") : t("Ask", "提问")}</button></div>
    </form>
    {answerIncludesEarlier && earlier?.link && <button disabled={busy} onClick={() => revisit(earlier.link!.revision)}>{t('Inspect that decision', '查看那次选择')}</button>}
    <button disabled={busy || !displayedFrame?.turn} onClick={() => continueGame(lesson.revision, view.line)}>{t("Continue from this position", "从当前局面继续")}</button>
    <p className="teaching-note">{teachingNote(locale)}</p>
  </div>;
}
