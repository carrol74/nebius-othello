import type { LessonView, PositionLesson, TeachingFrame } from "./types";

export function coachFocus(lesson: PositionLesson) {
  const comparison = lesson.comparison;
  const facts = (lesson.coaching ?? []).flatMap((card) => card.facts);
  for (const fact of facts) {
    const choice = comparison.choices.find((move) =>
      fact.id === `p${lesson.revision}:continuation_${move.coordinate}`
      || fact.id === `p${lesson.revision}:proof_${move.coordinate}`);
    if (choice) return {choice, frame: choice.continuation_lesson && fact.id.includes(":continuation_")
      ? choice.continuation_lesson.frame_index - 1 : 1};
  }
  return null;
}

export function teachingView(selected: string, frames: TeachingFrame[], frame: number): LessonView {
  return {selected_move: selected, line: frames.slice(1, frame + 1).map((step) => step.coordinate!)};
}

export function sameTeachingView(first: LessonView | null | undefined, second: LessonView): boolean {
  return !!first && first.selected_move === second.selected_move
    && first.line.length === second.line.length && first.line.every((move, index) => move === second.line[index]);
}
