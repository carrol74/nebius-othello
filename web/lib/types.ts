import type { components } from "./generated-api";

export type SavedGame = components["schemas"]["SavedGame"];

export type TeachingComparison = components["schemas"]["TeachingComparison"];
export type TeachingMove = components["schemas"]["TeachingMove"];
export type LessonReason = components["schemas"]["LessonReason"];
export type TeachingFrame = components["schemas"]["TeachingFrame"];
export type CornerPractice = components["schemas"]["CornerPractice"];
export type CornerPracticeOption = components["schemas"]["CornerPracticeOption"];
export type PositionLesson = components["schemas"]["PositionLesson"];
export type QuestionResult = components["schemas"]["QuestionResult"];
export type LessonView = components["schemas"]["LessonView"];
export type EarlierDecisionResult = components["schemas"]["EarlierDecisionResult"];
export type EarlierDecisionLink = components["schemas"]["EarlierDecisionLink"];

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
}

export interface Candidate {
  coordinate: string;
  score: number;
  principal_variation: string[];
  score_kind: "estimate" | "exact";
  depth: number;
}

export interface Analysis {
  terminal_score_rule?: "winner_takes_empties";
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

export type ReviewSummary = components["schemas"]["ReviewSummary"];
export type KeyMove = components["schemas"]["KeyMove"];
export type GameSummary = components["schemas"]["GameSummary"];

interface TaskState {
  language: 'en' | 'zh';
  task_id: string;
  status: "queued" | "running" | "succeeded" | "failed";
  game_id: string;
  error: { code: string; message: string } | null;
}

export type Task = TaskState & (
  | { kind: "review"; result: ReviewSummary | null }
  | { kind: "question"; result: QuestionResult | null }
  | { kind: "lesson"; result: PositionLesson | null }
  | { kind: "summary"; result: GameSummary | null }
);

export interface TrackedTask {
  task: Task;
  purpose: "review" | "question" | "lesson" | "summary";
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
