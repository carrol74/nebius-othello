from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from nemothello.opponents import Difficulty
from nemothello.rules import Color

BoardRows = Annotated[
    list[Annotated[str, Field(pattern=r"^[.XO]{8}$")]], Field(min_length=8, max_length=8)
]
Coordinate = Annotated[str, Field(pattern=r"^[a-h][1-8]$")]


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WriteRequest(RequestModel):
    request_id: str = Field(min_length=8, max_length=100)


class CreateGame(WriteRequest):
    human_color: Color
    difficulty: Difficulty = "medium"


class RevisionRequest(WriteRequest):
    expected_revision: int = Field(ge=0)


class MoveRequest(RevisionRequest):
    coordinate: Coordinate


class HintRequest(RequestModel):
    expected_revision: int = Field(ge=0)


class HintDisplay(RevisionRequest):
    hint_id: str


class QuestionRequest(WriteRequest):
    question: str = Field(min_length=1, max_length=2000)


class BranchRequest(WriteRequest):
    revision: int = Field(ge=0)
    mode: Literal["manual", "follow_hints"]


class AnalyzeRequest(RequestModel):
    board: BoardRows
    turn: Color


class HistoryEvent(BaseModel):
    event_index: int
    actor: Color
    kind: Literal["move", "pass"]
    coordinate: Coordinate | None
    revision: int
    board: BoardRows
    turn: Color | None


class GameResult(BaseModel):
    black_count: int
    white_count: int
    winner: Literal["X", "O", "draw"]


class GameState(BaseModel):
    game_id: str
    revision: int
    board: BoardRows
    turn: Color | None
    human_color: Color
    status: Literal["active", "finished"]
    legal_moves: list[Coordinate]
    history: list[HistoryEvent]
    initial_board: BoardRows
    initial_turn: Color
    opponent_config_id: str
    opponent_name: str = "Previous opponent"
    difficulty: Difficulty | None = None
    hint_level: int | None = Field(default=None, ge=1, le=10)
    result: GameResult | None
    parent_game_id: str | None = None
    parent_revision: int | None = None
    auto_play: bool = False


class AnalysisSettings(BaseModel):
    level: int = Field(ge=1, le=10)
    minimum_depth: int = Field(ge=1, le=60)
    threads: Literal[1]
    book: Literal[False]
    selectivity: Literal[5]


class Candidate(BaseModel):
    coordinate: Coordinate
    score: float
    principal_variation: list[str]
    depth: int = Field(ge=1, le=60)
    score_kind: Literal["estimate", "exact"]


class Analysis(BaseModel):
    board: BoardRows
    turn: Color
    candidates: list[Candidate]
    recommended_move: Coordinate
    score_perspective: Color
    score_kind: Literal["estimate", "exact"]
    engine_version: str
    eval_file: str
    depth: int = Field(ge=1, le=60)
    settings: AnalysisSettings
    elapsed_ms: float = Field(ge=0)
    raw_output: str | None = None


class Hint(BaseModel):
    hint_id: str
    game_id: str
    revision: int
    recommended_move: Coordinate
    analysis: Analysis
    displayed: bool


class HintDisplayResult(BaseModel):
    hint_id: str
    displayed: bool


class VariationFrame(BaseModel):
    board: BoardRows
    turn: Color | None
    coordinate: str | None


class MoveComparison(BaseModel):
    coordinate: Coordinate
    corner: int
    empty_corner_neighbor: int
    opponent_moves: int
    own_moves: int
    frontier_difference: int
    disc_difference: int
    opponent_legal_moves: list[Coordinate]
    opponent_corners: list[Coordinate]
    frames: list[VariationFrame]


class ReviewFact(BaseModel):
    id: str
    text: str
    topic: str
    revision: int | None = None


class Lesson(BaseModel):
    title: str
    text: str
    question: str


class CoachingCard(BaseModel):
    revision: int
    facts: list[ReviewFact]
    lesson_id: str
    lesson: Lesson


class ReviewEvidence(BaseModel):
    revision: int
    actor: Color
    actual_move: Coordinate
    recommended_move: Coordinate
    score_loss: float
    analysis: Analysis
    shown_hint_ids: list[str]
    adopted_hint: bool
    stage: str | None = None
    comparisons: list[MoveComparison] = Field(default_factory=list)


class ReviewHint(BaseModel):
    hint_id: str
    revision: int
    recommended_move: Coordinate
    analysis_settings: AnalysisSettings | None = None


class HintAdoption(BaseModel):
    shown_turns: int = Field(ge=0)
    adopted_turns: int = Field(ge=0)


class AutomaticHintMove(BaseModel):
    revision: int
    hint_id: str
    coordinate: Coordinate
    analysis_settings: AnalysisSettings


class ReviewEvent(BaseModel):
    event_index: int
    actor: Color
    kind: Literal["move", "pass"]
    coordinate: Coordinate | None
    revision: int


class Review(BaseModel):
    game_id: str
    result: GameResult
    human_color: Color
    initial_board: BoardRows
    initial_turn: Color
    history: list[ReviewEvent]
    parent_game_id: str | None
    parent_revision: int | None
    opponent_config_id: str
    key_moves: list[ReviewEvidence]
    branch_mode: Literal["manual", "follow_hints"] | None
    automatic_hint_moves: list[AutomaticHintMove]
    hints: list[ReviewHint]
    hint_adoption: HintAdoption
    explanation: str
    evidence: list[ReviewEvidence]
    model_id: str | None
    usage: dict[str, Any] | None
    format_version: str | None = None
    summary_facts: list[ReviewFact] = Field(default_factory=list)
    coaching: list[CoachingCard] = Field(default_factory=list)
    coaching_status: Literal["pending", "ready", "failed"] | None = None
    coaching_error: str | None = None
    branch_results: list[dict[str, Any]] = Field(default_factory=list)


class BranchResult(BaseModel):
    game_id: str
    result: GameResult


class QuestionResult(BaseModel):
    answer: str
    model_id: str | None
    usage: dict[str, Any] | None
    coaching: list[CoachingCard] = Field(default_factory=list)
    format_version: str | None = None
    answer_facts: list[ReviewFact] = Field(default_factory=list)
    topic: str | None = None


class Task(BaseModel):
    task_id: str
    kind: Literal["review", "question", "branch"]
    game_id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    result: Review | BranchResult | QuestionResult | None = None
    error: dict[str, str] | None = None
    usage: dict[str, Any] | None = None

    @model_validator(mode="after")
    def check_result(self) -> "Task":
        expected = {"review": Review, "branch": BranchResult, "question": QuestionResult}[self.kind]
        if self.status == "succeeded":
            if not isinstance(self.result, expected):
                raise ValueError("Task result does not match the task kind")
        elif self.result is not None:
            raise ValueError("Unfinished tasks cannot contain a successful result")
        return self


class ReviewLookup(BaseModel):
    task: Task | None
