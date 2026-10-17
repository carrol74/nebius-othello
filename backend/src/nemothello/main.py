import asyncio
import logging
import secrets
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from nemothello.config import Settings
from nemothello.edax import Edax
from nemothello.errors import AppError
from nemothello.games import Games
from nemothello.nemotron import Nemotron
from nemothello.opponents import DIFFICULTY_LEVELS, HINT_LEVELS, EdaxOpponent
from nemothello.schemas import (
    Analysis,
    AnalyzeRequest,
    BranchRequest,
    CreateGame,
    GameState,
    Hint,
    HintDisplay,
    HintDisplayResult,
    HintRequest,
    MoveRequest,
    QuestionRequest,
    Review,
    ReviewLookup,
    RevisionRequest,
    Task,
    WriteRequest,
)
from nemothello.storage import Store
from nemothello.tasks import Tasks

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    settings.validate_resources()
    store = Store(settings.database_path)
    with store.exclusive_worker():
        store.recover_tasks()
        edax = Edax(settings.edax_executable, settings.edax_eval_file,
                    settings.edax_version, settings.edax_level, settings.edax_timeout_seconds)
        hint_engines = {
            level: Edax(settings.edax_executable, settings.edax_eval_file,
                        settings.edax_version, level, settings.edax_timeout_seconds)
            for level in set(HINT_LEVELS.values()) - {edax.level}
        }
        hint_engines[edax.level] = edax
        opponent_engines = {
            level: Edax(settings.edax_executable, settings.edax_eval_file,
                        settings.edax_version, level, settings.edax_timeout_seconds)
            for level in {*DIFFICULTY_LEVELS.values(), settings.edax_opponent_level}
        }
        opponents = {level: EdaxOpponent(engine) for level, engine in opponent_engines.items()}
        opponent = opponents[settings.edax_opponent_level]
        nemotron = Nemotron(settings.token_factory_api_key.get_secret_value(),
                            settings.token_factory_base_url, settings.token_factory_model_id)
        games = Games(store, opponent, edax, settings.task_limit_per_session,
                      settings.task_queue_limit,
                      {name: opponents[level] for name, level in DIFFICULTY_LEVELS.items()},
                      {name: hint_engines[level] for name, level in HINT_LEVELS.items()})
        tasks = Tasks(store, games, nemotron)
        app.state.settings, app.state.games, app.state.store = settings, games, store
        worker = asyncio.create_task(tasks.run())
        try:
            yield
        finally:
            tasks.stop.set()
            try:
                await worker
            finally:
                for engine in hint_engines.values():
                    engine.close()
                for engine in opponent_engines.values():
                    engine.close()
                nemotron.close()


app = FastAPI(title="Nemothello", version="0.1.0", lifespan=lifespan)


def session(
    request: Request, authorization: Annotated[str, Header()],
    x_session_id: Annotated[str, Header(min_length=8, max_length=100)],
) -> str:
    expected = "Bearer " + request.app.state.settings.backend_service_token.get_secret_value()
    if not secrets.compare_digest(authorization, expected):
        raise AppError("UNAUTHORIZED", "服务凭据无效", 401)
    settings = request.app.state.settings
    request.app.state.store.admit_request(
        x_session_id, settings.request_limit_per_session, settings.request_limit_global,
        settings.request_limit_window_seconds,
    )
    return x_session_id


Owner = Annotated[str, Depends(session)]


@app.exception_handler(AppError)
async def app_error(request: Request, exc: AppError):
    return JSONResponse(status_code=exc.status, content={
        "code": exc.code, "message": exc.message,
        "request_id": request.headers.get("x-request-id"), "retryable": exc.retryable,
    })


@app.exception_handler(RequestValidationError)
async def invalid_input(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={
        "code": "INVALID_INPUT", "message": "请求字段缺失或格式不正确",
        "request_id": request.headers.get("x-request-id"), "retryable": False,
    })


@app.exception_handler(Exception)
async def service_error(request: Request, exc: Exception):
    logger.exception("服务请求失败 path=%s", request.url.path)
    upstream = isinstance(exc, httpx.HTTPError)
    return JSONResponse(status_code=502 if upstream else 500, content={
        "code": "UPSTREAM_FAILED" if upstream else "SERVICE_ERROR",
        "message": "外部服务请求失败，请重试" if upstream else "服务处理失败，请检查日志",
        "request_id": request.headers.get("x-request-id"), "retryable": upstream,
    })


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "nemothello"}


@app.post("/games", response_model=GameState)
def create_game(body: CreateGame, owner: Owner, request: Request):
    return request.app.state.games.create(owner, body.request_id, body.human_color, body.difficulty)


@app.get("/games/{game_id}", response_model=GameState)
def get_game(game_id: str, owner: Owner, request: Request):
    return request.app.state.games.get(game_id, owner)


@app.post("/games/{game_id}/moves", response_model=GameState)
def move(game_id: str, body: MoveRequest, owner: Owner, request: Request):
    return request.app.state.games.move(
        owner, game_id, body.request_id, body.expected_revision, body.coordinate,
    )


@app.post("/games/{game_id}/ai-move", response_model=GameState)
def ai_move(game_id: str, body: RevisionRequest, owner: Owner, request: Request):
    return request.app.state.games.move(owner, game_id, body.request_id, body.expected_revision)


@app.post("/games/{game_id}/hint", response_model=Hint)
def hint(game_id: str, body: HintRequest, owner: Owner, request: Request):
    return request.app.state.games.hint(owner, game_id, body.expected_revision)


@app.post("/games/{game_id}/hint-displays", response_model=HintDisplayResult)
def display_hint(game_id: str, body: HintDisplay, owner: Owner, request: Request):
    return request.app.state.games.display_hint(
        owner, game_id, body.request_id, body.expected_revision, body.hint_id,
    )


@app.post("/analyze", response_model=Analysis)
def analyze(body: AnalyzeRequest, owner: Owner, request: Request):
    return request.app.state.games.edax.analyze(tuple(body.board), body.turn)


@app.post("/games/{game_id}/reviews", response_model=Task)
def review(game_id: str, body: WriteRequest, owner: Owner, request: Request):
    return request.app.state.games.create_review_task(owner, game_id, body.request_id)


@app.get("/games/{game_id}/review", response_model=Review | ReviewLookup)
def get_review(game_id: str, owner: Owner, request: Request):
    return request.app.state.games.review(owner, game_id)


@app.post("/games/{game_id}/review/questions", response_model=Task)
def question(game_id: str, body: QuestionRequest, owner: Owner, request: Request):
    return request.app.state.games.create_review_task(owner, game_id, body.request_id, body.question)


@app.post("/games/{game_id}/branches", response_model=GameState | Task)
def branch(game_id: str, body: BranchRequest, owner: Owner, request: Request):
    return request.app.state.games.branch(owner, game_id, body.request_id, body.revision, body.mode)


@app.get("/tasks/{task_id}", response_model=Task)
def get_task(task_id: str, owner: Owner, request: Request):
    return Games.public_task(request.app.state.store.get("task", task_id, owner))
