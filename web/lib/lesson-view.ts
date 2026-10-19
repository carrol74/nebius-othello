import type { LessonView, TeachingFrame } from "./types";

export function teachingView(selected: string, frames: TeachingFrame[], frame: number): LessonView {
  return {selected_move: selected, line: frames.slice(1, frame + 1).map((step) => step.coordinate!)};
}

export function sameTeachingView(first: LessonView | null | undefined, second: LessonView): boolean {
  return !!first && first.selected_move === second.selected_move
    && first.line.length === second.line.length && first.line.every((move, index) => move === second.line[index]);
}
