import type { PracticeState } from "../components/practice-panel";

export function practiceFeedbackFrame(practice: PracticeState | null) {
  if (!practice?.feedback || !("witness" in practice.feedback)) return null;
  return practice.feedback_line === "blocking" ? practice.feedback.blocking_frame : practice.feedback.allowing_frame;
}

export function practiceSelection(practice: PracticeState, coordinate: string, cell: string): PracticeState {
  if (practice.feedback) return practice;
  if (practice.question.objective === "reply_access") {
    return !practice.move || practice.move === coordinate
      ? {...practice, move:coordinate, alternative:null}
      : {...practice, alternative:coordinate};
  }
  return cell === "." ? {...practice, move:coordinate, anchor:null} : {...practice, anchor:coordinate};
}
