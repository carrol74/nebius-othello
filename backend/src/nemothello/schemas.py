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


Language = Literal["en", "zh"]


class LessonView(RequestModel):
    selected_move: Coordinate
    line: list[Coordinate | Literal["pass"]] = Field(max_length=4)


class LanguageRequest(WriteRequest):
    language: Language = "en"


class PositionLessonRequest(WriteRequest):
    revision: int = Field(ge=0)
    question: str | None = Field(default=None, min_length=1, max_length=2000)
    view: LessonView | None = None
    language: Language = "en"

    @model_validator(mode="after")
    def view_requires_question(self):
        if self.view is not None and self.question is None:
            raise ValueError("A teaching view is only used with a question")
        return self


class BranchRequest(WriteRequest):
    revision: int = Field(ge=0)
    line: list[Coordinate | Literal["pass"]] = Field(default_factory=list, max_length=4)


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


class SavedGame(BaseModel):
    game_id: str
    created_at: str | None = None
    human_color: Color
    parent_game_id: str | None = None
    status: Literal["finished"]


class GameState(BaseModel):
    game_id: str
    created_at: str | None = None
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
    terminal_score_rule: Literal["winner_takes_empties"] = "winner_takes_empties"
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


class TeachingFrame(VariationFrame):
    actor: Color | None
    flipped: list[Coordinate]


class CornerPracticeOption(BaseModel):
    coordinate: Coordinate
    safe: bool
    recommended: bool
    attack: Coordinate | Literal["pass"] | None
    replies: int = Field(ge=0)
    frames: list[TeachingFrame]
    capture_lines: list[list[Coordinate]]


class CornerPractice(BaseModel):
    target: Coordinate
    options: list[CornerPracticeOption]


class DecisionAssessment(BaseModel):
    status: Literal["forced", "best", "tied_best", "lower_rated"]
    legal_move_count: int = Field(ge=1)
    best_moves: list[Coordinate]
    is_played: bool
    score_loss: float = Field(ge=0)
    score_kind: Literal["estimate", "exact"]
    position: Literal["ahead", "behind", "level"]


class CornerRefutation(BaseModel):
    attack: Coordinate | Literal["pass"]
    defense: Coordinate | Literal["pass"] | None


class CornerProof(BaseModel):
    target: Coordinate
    attacker: Color
    max_plies: Literal[3]
    forced: bool
    attack: Coordinate | Literal["pass"] | None
    defenses: list[Coordinate | Literal["pass"]]
    refutations: list[CornerRefutation]


class ContinuationLesson(BaseModel):
    kind: Literal["recapture"]
    frame_index: Literal[2]
    capture_line: list[Coordinate] = Field(min_length=3)
    recaptured: list[Coordinate]


class TeachingConcepts(BaseModel):
    exposed: list[Coordinate]
    inner_flips: int = Field(ge=0)
    stable_gained: list[Coordinate]
    safe_replies: int = Field(ge=0)
    unsafe_replies: list[Coordinate]


class TeachingMove(BaseModel):
    coordinate: Coordinate
    score: float
    score_kind: Literal["estimate", "exact"]
    kind: Literal["line", "corner_taken", "corner_given", "corner_forced", "corner_defense", "pass"]
    target: Coordinate | None
    opponent_reply: Coordinate | None
    checked_defenses: list[Coordinate]
    capture_lines: list[list[Coordinate]]
    opponent_corner_moves_after_reply: list[Coordinate]
    line_source: Literal["engine", "rules"]
    frames: list[TeachingFrame]
    assessment: DecisionAssessment
    corner_proof: CornerProof | None = None
    continuation_lesson: ContinuationLesson | None = None
    concepts: TeachingConcepts
    # Whether any legal move here keeps the opponent from forcing the target corner
    defendable: bool | None = None


class ContrastSquare(BaseModel):
    coordinate: Coordinate
    available: Literal["X", "O", "."]
    blocked: Literal["X", "O", "."]


class ReplyOpportunity(BaseModel):
    actor: Color
    coordinate: Coordinate
    available_after: Coordinate
    blocked_after: Coordinate
    capture_line: list[Coordinate]
    changes: list[ContrastSquare]


class CornerComparisonWitness(BaseModel):
    prefix: list[Coordinate | Literal["pass"]] = Field(max_length=2)
    opportunity: ReplyOpportunity


class TeachingInsight(BaseModel):
    kind: Literal["forced", "best", "equal", "corner_access", "illustrated_corner", "shared_corner", "search", "corner_defense"]
    better_move: Coordinate | None
    worse_move: Coordinate | None
    target: Coordinate | None
    gap: Coordinate | None
    score_kind: Literal["estimate", "exact"]
    proof: CornerProof | None = None
    example: list[Coordinate | Literal["pass"]] = Field(default_factory=list)
    other_threats: list[CornerProof] = Field(default_factory=list)
    witness: CornerComparisonWitness | None = None


class ReplyConsequence(BaseModel):
    reply: Coordinate
    axis: Literal["file", "rank"]
    axis_value: str
    actual_moves: list[Coordinate]
    alternative_moves: list[Coordinate]
    retained_disc: Coordinate
    opportunity: ReplyOpportunity


class DecisionContrast(BaseModel):
    actual_move: Coordinate
    recommended_move: Coordinate
    replies_after_actual: list[Coordinate]
    replies_after_recommended: list[Coordinate]
    removed_reply: ReplyOpportunity | None
    added_reply: ReplyOpportunity | None
    consequence: ReplyConsequence | None = None


class LessonReason(BaseModel):
    kind: Literal["forced_move", "corner_contrast", "corner_defense", "corner_threat", "corners",
                  "reply_contrast", "reply_consequence", "recapture", "quiet", "mobility", "stable", "parity"]
    fact: str
    move: Coordinate
    frame: int = Field(ge=1)
    # Squares to highlight at the key frame, for each move whose line shows the reason
    marks: dict[str, list[Coordinate]]
    target: Coordinate | None
    actor: Color | None


class TeachingComparison(BaseModel):
    revision: int
    actor: Color
    selected_move: Coordinate
    recommended_move: Coordinate
    reference_move: Coordinate | None
    insight: TeachingInsight
    choices: list[TeachingMove]
    decision_contrast: DecisionContrast | None = None
    reason: LessonReason | None
    focus: list[str]


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
    frames: list[TeachingFrame] = Field(default_factory=list)


class Lesson(BaseModel):
    title: str
    text: str
    question: str


class CoachingCard(BaseModel):
    revision: int
    facts: list[ReviewFact]
    lesson_id: str
    lesson: Lesson
    text: str | None = None


class CoachToolCall(BaseModel):
    name: str
    arguments: dict[str, Any] | str
    fact_id: str | None
    error: str | None


class ReviewEvidence(BaseModel):
    revision: int
    actor: Color
    actual_move: Coordinate
    recommended_move: Coordinate
    score_loss: float
    analysis: Analysis
    shown_hint_ids: list[str]
    adopted_hint: bool
    # This game's opponent reply after each candidate, absent when it must pass
    opponent_replies: dict[Coordinate, Coordinate]
    stage: str | None = None
    comparisons: list[MoveComparison] = Field(default_factory=list)


class HintAdoption(BaseModel):
    shown_turns: int = Field(ge=0)
    adopted_turns: int = Field(ge=0)


class KeyMove(BaseModel):
    revision: int
    actual_move: Coordinate
    reason: LessonReason | None


class ReviewSummary(BaseModel):
    game_id: str
    key_moves: list[KeyMove]


class ThreatObservation(BaseModel):
    revision: int
    turn: Color
    max_plies: Literal[3, 4]


class EarlierDecisionLink(BaseModel):
    revision: int
    actor: Color
    target: Coordinate
    recorded_move: Coordinate
    recommended_move: Coordinate
    evidence: ReviewEvidence
    recorded_proof: CornerProof
    recommended_proof: CornerProof
    continuity: list[ThreatObservation]


class EarlierDecisionResult(BaseModel):
    status: Literal['verified', 'not_found', 'not_applicable']
    scope: Literal['continuous_bounded_corner_threat']
    link: EarlierDecisionLink | None

    @model_validator(mode='after')
    def link_matches_status(self):
        if (self.link is not None) != (self.status == 'verified'):
            raise ValueError('Only a verified result can contain an earlier decision link')
        return self


class QuestionResult(BaseModel):
    language: Language = 'en'
    answer: str
    model_id: str | None
    usage: dict[str, Any] | None
    coaching: list[CoachingCard] = Field(default_factory=list)
    format_version: str | None = None
    answer_facts: list[ReviewFact] = Field(default_factory=list)
    topic: str | None = None
    tool_calls: list[CoachToolCall] = Field(default_factory=list)
    view: LessonView | None = None
    earlier_decision: EarlierDecisionResult | None = None


class PositionLesson(BaseModel):
    language: Language = 'en'
    game_id: str
    revision: int
    task_id: str | None = None
    earlier_eligible: bool = False
    earlier_decision: EarlierDecisionResult | None = None
    evidence: ReviewEvidence
    comparison: TeachingComparison
    hint_adoption: HintAdoption
    coaching: list[CoachingCard] = Field(default_factory=list)
    answer: str | None = None
    tool_calls: list[CoachToolCall] = Field(default_factory=list)
    coaching_status: Literal["not_requested", "pending", "ready", "failed"]
    coaching_error: str | None = None
    coaching_error_code: str | None = None
    model_id: str | None = None
    usage: dict[str, Any] | None = None


class GameSummary(BaseModel):
    game_id: str
    language: Language
    task_id: str
    status: Literal["pending", "ready", "failed"]
    text: str | None = None
    facts: list[ReviewFact] = Field(default_factory=list)
    tool_calls: list[CoachToolCall] = Field(default_factory=list)
    model_id: str | None = None
    usage: dict[str, Any] | None = None
    error: str | None = None
    error_code: str | None = None


class Task(BaseModel):
    language: Language = 'en'
    task_id: str
    kind: Literal["review", "question", "lesson", "summary"]
    game_id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    result: ReviewSummary | QuestionResult | PositionLesson | GameSummary | None = None
    error: dict[str, str] | None = None
    usage: dict[str, Any] | None = None

    @model_validator(mode="after")
    def check_result(self) -> "Task":
        expected = {"review": ReviewSummary, "question": QuestionResult, "lesson": PositionLesson,
                    "summary": GameSummary}[self.kind]
        if self.status == "succeeded":
            if not isinstance(self.result, expected):
                raise ValueError("Task result does not match the task kind")
        elif self.result is not None:
            raise ValueError("Unfinished tasks cannot contain a successful result")
        return self


class ReviewLookup(BaseModel):
    task: Task | None
