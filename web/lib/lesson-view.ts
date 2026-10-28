import type { LessonView, PositionLesson, TeachingComparison, TeachingFrame, TeachingMove } from "./types";

// The key step and its highlight come from the backend's primary reason for this decision
export function reasonView(comparison: TeachingComparison, choice: TeachingMove) {
  const reason = comparison.reason;
  if (!reason || (reason.move !== choice.coordinate && !(choice.coordinate in reason.marks))) return null;
  const frame = Math.min(reason.frame, choice.frames.length - 1);
  return {key_frame: frame, ray: {frame, squares: reason.marks[choice.coordinate] ?? []}};
}

// A line Nemotron demonstrated comes first; otherwise the board shows the primary reason
export function lessonFocus(lesson: PositionLesson) {
  const comparison = lesson.comparison;
  const facts = (lesson.coaching ?? []).flatMap((card) => card.facts);
  const fact = [...facts].reverse().find((fact) => (fact.frames?.length ?? 0) > 1);
  const frames = fact?.frames;
  const demonstrated = frames && comparison.choices.find((move) => move.coordinate === frames[1].coordinate);
  if (frames && demonstrated) return {choice: {...demonstrated, frames},
    frame: fact?.id === comparison.reason?.fact ? comparison.reason.frame : frames.length - 1};
  const choice = comparison.choices.find((move) => move.coordinate === comparison.reason?.move);
  return choice ? {choice, frame: Math.min(comparison.reason!.frame, choice.frames.length - 1)} : null;
}

export function canonicalFrames(choice: TeachingMove, frames: TeachingFrame[]) {
  return frames.length === choice.frames.length && frames.every((frame, index) => frame.coordinate === choice.frames[index].coordinate);
}

export function coachedFrames(lesson: PositionLesson, choice: TeachingMove) {
  const facts = (lesson.coaching ?? []).flatMap((card) => card.facts);
  return [...facts].reverse().find((fact) => fact.frames?.[1]?.coordinate === choice.coordinate)?.frames ?? choice.frames;
}

export function displayedTeachingView(choice: TeachingMove, variation: {lesson_frames: TeachingFrame[]; frame: number} | null): LessonView {
  const frames = variation?.lesson_frames ?? choice.frames;
  return teachingView(frames[1]?.coordinate ?? choice.coordinate, frames, variation?.frame ?? 1);
}

export function teachingView(selected: string, frames: TeachingFrame[], frame: number): LessonView {
  return {selected_move: selected, line: frames.slice(1, frame + 1).map((step) => step.coordinate!)};
}

export function sameTeachingView(first: LessonView | null | undefined, second: LessonView): boolean {
  return !!first && first.selected_move === second.selected_move
    && first.line.length === second.line.length && first.line.every((move, index) => move === second.line[index]);
}

export function answerMatchesView(answerView: LessonView | null | undefined, view: LessonView,
  answerTaskId: string | undefined, demonstratedAnswerId: string | undefined): boolean {
  return sameTeachingView(answerView, view)
    || (!!answerTaskId && answerTaskId === demonstratedAnswerId);
}
