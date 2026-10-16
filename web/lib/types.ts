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
  hints: { hint_id: string; revision: number; recommended_move: string }[];
  hint_adoption: { shown_turns: number; adopted_turns: number };
  result: GameResult;
  human_color: Color;
  parent_game_id: string | null;
  parent_revision: number | null;
  opponent_config_id: string;
  key_moves: ReviewEvidence[];
  model_id: string;
  usage: Record<string, unknown> | null;
  branch_mode: "manual" | "follow_hints" | null;
  automatic_hint_moves: {
    revision: number;
    hint_id: string;
    coordinate: string;
    analysis_settings: Analysis["settings"];
  }[];
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
  | { kind: "question"; result: { answer: string; model_id: string; usage: Record<string, unknown> | null } | null }
);

export interface TrackedTask {
  task: Task;
  purpose: "review" | "question" | "branch";
  game_id: string;
  question?: string;
}

export interface ApiFailure {
  code: string;
  message: string;
  request_id?: string | null;
  retryable?: boolean;
}
