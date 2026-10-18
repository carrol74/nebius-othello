import type { components } from "./generated-api";

export type TeachingComparison = components["schemas"]["TeachingComparison"];
export type TeachingMove = components["schemas"]["TeachingMove"];
export type TeachingFrame = components["schemas"]["TeachingFrame"];
export type TeachingDefense = components["schemas"]["TeachingDefense"];
export type PositionLesson = components["schemas"]["PositionLesson"];
export type QuestionResult = components["schemas"]["QuestionResult"];

export type Color = "X" | "O";
export type Difficulty = "easy" | "medium" | "hard";

export interface GameResult {
  black_count: number;
  white_count: number;
  winner: Color | "draw";
}

export interface HistoryEvent {
  event_index: number;
  actor: Color;
  kind: "move" | "pass";
  coordinate: string | null;
  revision: number;
  board: string[];
  turn: Color | null;
}

export interface GameState {
  game_id: string;
  created_at: string | null;
  revision: number;
  board: string[];
  initial_board: string[];
  initial_turn: Color;
  turn: Color | null;
  human_color: Color;
  status: "active" | "finished";
  legal_moves: string[];
  history: HistoryEvent[];
  opponent_config_id: string;
  opponent_name: string;
  difficulty: Difficulty | null;
  hint_level: number | null;
  result: GameResult | null;
  parent_game_id: string | null;
  parent_revision: number | null;
  auto_play: boolean;
}

export interface Candidate {
  coordinate: string;
  score: number;
  principal_variation: string[];
  score_kind: "estimate" | "exact";
  depth: number;
}

export interface Analysis {
  board: string[];
  turn: Color;
  candidates: Candidate[];
  recommended_move: string;
  score_perspective: Color;
  score_kind: "estimate" | "exact";
  engine_version: string;
  eval_file: string;
  depth: number;
  elapsed_ms: number;
  settings: { level: number; minimum_depth: number; threads: number; book: boolean; selectivity: number };
  raw_output?: string | null;
}

export interface Hint {
  hint_id: string;
  game_id: string;
  revision: number;
  recommended_move: string;
  analysis: Analysis;
  displayed: boolean;
}

export interface Review {
  game_id: string;
  initial_board: string[];
  initial_turn: Color;
  history: Pick<HistoryEvent, "event_index" | "actor" | "kind" | "coordinate" | "revision">[];
  explanation: string;
  evidence: ReviewEvidence[];
  hints: {
    hint_id: string;
    revision: number;
    recommended_move: string;
    analysis_settings?: Analysis["settings"] | null;
  }[];
  hint_adoption: { shown_turns: number; adopted_turns: number };
  result: GameResult;
  human_color: Color;
  parent_game_id: string | null;
  parent_revision: number | null;
  opponent_config_id: string;
  key_moves: ReviewEvidence[];
  model_id: string | null;
  usage: Record<string, unknown> | null;
  branch_mode: "manual" | "follow_hints" | null;
  automatic_hint_moves: {
    revision: number;
    hint_id: string;
    coordinate: string;
    analysis_settings: Analysis["settings"];
  }[];
  format_version?: string | null;
  summary_facts?: ReviewFact[];
  coaching?: CoachingCard[];
  coaching_status?: "pending" | "ready" | "failed" | null;
  coaching_error?: string | null;
  branch_results?: { game_id: string; parent_revision: number; result: GameResult }[];
}

export interface ReviewFact {
  id: string;
  text: string;
  topic: string;
  revision?: number | null;
}

export interface CoachingCard {
  revision: number;
  facts: ReviewFact[];
  lesson_id: string;
  lesson: { title: string; text: string; question: string };
}

export interface VariationFrame {
  board: string[];
  turn: Color | null;
  coordinate: string | null;
}

export interface MoveComparison {
  coordinate: string;
  corner: number;
  empty_corner_neighbor: number;
  opponent_moves: number;
  own_moves: number;
  frontier_difference: number;
  disc_difference: number;
  opponent_legal_moves: string[];
  opponent_corners: string[];
  frames: VariationFrame[];
}

export interface ReviewEvidence {
  revision: number;
  actor: Color;
  actual_move: string;
  recommended_move: string;
  score_loss: number;
  analysis: Analysis;
  shown_hint_ids: string[];
  adopted_hint: boolean;
  is_played?: boolean;
  stage?: string | null;
  comparisons?: MoveComparison[];
}

interface TaskState {
  task_id: string;
  status: "queued" | "running" | "succeeded" | "failed";
  game_id: string;
  error: { code: string; message: string } | null;
}

export type Task = TaskState & (
  | { kind: "review"; result: Review | null }
  | { kind: "branch"; result: { game_id: string; result: GameResult } | null }
  | { kind: "question"; result: { answer: string; model_id: string | null; usage: Record<string, unknown> | null; coaching?: CoachingCard[]; format_version?: string | null; answer_facts?: ReviewFact[]; topic?: string | null } | null }
  | { kind: "lesson"; result: PositionLesson | null }
);

export interface TrackedTask {
  task: Task;
  purpose: "review" | "question" | "branch" | "lesson";
  game_id: string;
  revision?: number;
  question?: string;
}

export interface ApiFailure {
  code: string;
  message: string;
  request_id?: string | null;
  retryable?: boolean;
}
