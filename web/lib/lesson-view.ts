import type { LessonView, PositionLesson, TeachingComparison, TeachingFrame, TeachingMove } from "./types";

export function comparisonRay(comparison: TeachingComparison, choice: TeachingMove) {
  const witness = comparison.insight.witness;
  if (witness) return {frame: witness.prefix.length + 1, squares: witness.opportunity.capture_line};
  // Ordinary moves highlight their flipped discs that touch an empty square
  const plain = choice.kind === "line" && !comparison.decision_contrast && !choice.continuation_lesson;
  return plain && choice.concepts.exposed.length ? {frame: 1, squares: choice.concepts.exposed} : undefined;
}

export function keyFrame(comparison: TeachingComparison, choice: TeachingMove): number | null {
  const last = choice.frames.length - 1;
  const frame = comparison.insight.witness ? comparison.insight.witness.prefix.length + 1
    : choice.continuation_lesson ? choice.continuation_lesson.frame_index - 1
    : choice.capture_lines?.length ? last - 1 : null;
  return frame === null ? null : Math.min(frame, last);
}

export function coachFocus(lesson: PositionLesson) {
  const comparison = lesson.comparison;
  const facts = (lesson.coaching ?? []).flatMap((card) => card.facts);
  for (const fact of facts) {
    if (fact.id === `p${lesson.revision}:corner_contrast` && comparison.insight.witness) {
      const choice = comparison.choices.find((move) => move.coordinate === comparison.insight.witness!.opportunity.available_after);
      if (choice) return {choice, frame: comparison.insight.witness.prefix.length + 1};
    }
    if (fact.id === `p${lesson.revision}:defense`) {
      const choice = comparison.choices.find((move) => move.coordinate === comparison.insight.better_move);
      if (choice?.kind === 'corner_defense') return {choice, frame: Math.min(2, choice.frames.length - 1)};
    }
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
