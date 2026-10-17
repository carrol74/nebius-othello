"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, requestId } from "@/lib/api";
import { ReviewDetails } from "@/components/review-details";
import { TaskList } from "@/components/task-list";
import type { Color, Difficulty, GameState, Hint, Review, Task, TrackedTask } from "@/lib/types";

type RecentGame = { game_id: string; label: string };
const difficultyName: Record<Difficulty, string> = { easy: "Beginner", medium: "Intermediate", hard: "Advanced" };
const colorName = (color: Color) => color === "X" ? "Black" : "White";

function message(error: unknown) {
  if (error instanceof ApiError) return `${error.message}${error.detail.request_id ? ` · Request ${error.detail.request_id}` : ""}`;
  return error instanceof Error ? error.message : "Request failed. Please try again.";
}

export default function Home() {
  const [game, setGame] = useState<GameState | null>(null);
  const [humanColor, setHumanColor] = useState<Color>("X");
  const [difficulty, setDifficulty] = useState<Difficulty>("medium");
  const [recent, setRecent] = useState<RecentGame[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tips, setTips] = useState(false);
  const [hint, setHint] = useState<Hint | null>(null);
  const [hintConfirmed, setHintConfirmed] = useState(false);
  const [hintError, setHintError] = useState<string | null>(null);
  const [hintRetry, setHintRetry] = useState(0);
  const [displayRetry, setDisplayRetry] = useState(0);
  const [historyRevision, setHistoryRevision] = useState<number | null>(null);
  const [review, setReview] = useState<Review | null>(null);
  const [tasks, setTasks] = useState<TrackedTask[]>([]);
  const [question, setQuestion] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [bootRetry, setBootRetry] = useState(0);
  const gameRef = useRef<GameState | null>(null);
  const busyRef = useRef(false);
  const tipsRef = useRef(false);
  const attemptedAi = useRef<string | null>(null);
  const displayIds = useRef(new Map<string, string>());
  const bootStarted = useRef(false);

  const acceptGame = useCallback((next: GameState) => {
    const isNew = gameRef.current?.game_id !== next.game_id;
    const nextKey = `${next.game_id}:${next.revision}`;
    if (attemptedAi.current !== nextKey) attemptedAi.current = null;
    displayIds.current.clear();
    gameRef.current = next;
    setGame(next);
    setHistoryRevision(null);
    setHint(null);
    setHintConfirmed(false);
    if (isNew) {
      setHumanColor(next.human_color);
      if (next.difficulty) setDifficulty(next.difficulty);
      setReview(null);
      setQuestion("");
      setTips(false);
      tipsRef.current = false;
    }
    setRecent((current) => [
      { game_id: next.game_id, label: `${next.parent_game_id ? "Branch" : "Game"} · ${colorName(next.human_color)} · ${next.game_id.slice(0, 8)}` },
      ...current.filter((item) => item.game_id !== next.game_id),
    ].slice(0, 20));
    localStorage.setItem("nemothello_active_game", next.game_id);
    window.history.replaceState(null, "", `?game=${encodeURIComponent(next.game_id)}`);
  }, []);

  const perform = useCallback(async (label: string, action: () => Promise<void>) => {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(label);
    setError(null);
    try {
      await action();
    } catch (failure) {
      setError(message(failure));
      if (failure instanceof ApiError && failure.status === 409 && gameRef.current) {
        try { acceptGame(await api<GameState>(`/games/${gameRef.current.game_id}`)); }
        catch (refreshFailure) { setError(`${message(failure)}; Could not refresh the board: ${message(refreshFailure)}`); }
      }
    } finally { busyRef.current = false; setBusy(null); }
  }, [acceptGame]);

  const createGame = useCallback(async (color: Color, level: Difficulty) => {
    acceptGame(await api<GameState>("/games", {
      human_color: color, difficulty: level, request_id: requestId(),
    }));
  }, [acceptGame]);

  useEffect(() => {
    if (bootStarted.current) return;
    bootStarted.current = true;
    void perform("Preparing game", async () => {
      await api<{ ready: boolean }>("/session");
      const saved = localStorage.getItem("nemothello_recent_games");
      if (saved) {
        try {
          const parsed: unknown = JSON.parse(saved);
          if (!Array.isArray(parsed) || !parsed.every((item) => item && typeof item.game_id === "string" && typeof item.label === "string")) throw new Error("Saved game list is invalid");
          setRecent(parsed.map((item: RecentGame) => ({
            ...item,
            label: item.label.startsWith("Game · ") || item.label.startsWith("Branch · ")
              ? item.label : `Saved game · ${item.game_id.slice(0, 8)}`,
          })));
        } catch (failure) { setError(message(failure)); }
      }
      const gameId = new URLSearchParams(window.location.search).get("game");
      if (gameId) {
        try {
          acceptGame(await api<GameState>(`/games/${encodeURIComponent(gameId)}`));
        } catch (failure) {
          if (failure instanceof ApiError && failure.status === 404) {
            localStorage.removeItem("nemothello_active_game");
            setRecent((current) => current.filter((item) => item.game_id !== gameId));
            window.history.replaceState(null, "", window.location.pathname);
          }
          throw failure;
        }
      } else await createGame("X", "medium");
      setLoaded(true);
    });
  }, [acceptGame, createGame, perform, bootRetry]);

  useEffect(() => { if (loaded) localStorage.setItem("nemothello_recent_games", JSON.stringify(recent)); }, [recent, loaded]);

  const requestAi = useCallback((current: GameState) => perform("AI is choosing a move", async () => {
    acceptGame(await api<GameState>(`/games/${current.game_id}/ai-move`, { expected_revision: current.revision, request_id: requestId() }));
  }), [acceptGame, perform]);

  useEffect(() => {
    if (!game || busy || game.auto_play || game.status !== "active" || game.turn === game.human_color) return;
    const key = `${game.game_id}:${game.revision}`;
    if (attemptedAi.current === key) return;
    attemptedAi.current = key;
    void requestAi(game);
  }, [game, busy, requestAi]);

  useEffect(() => {
    if (!game?.auto_play) return;
    const gameId = game.game_id;
    const controller = new AbortController();
    let pending = false;
    const timer = setInterval(() => {
      if (pending || document.visibilityState === "hidden") return;
      pending = true;
      void api<GameState>(`/games/${gameId}`, undefined, controller.signal).then((next) => {
        if (controller.signal.aborted || gameRef.current?.game_id !== gameId) return;
        if (!next.auto_play && next.status === "active") attemptedAi.current = `${gameId}:${next.revision}`;
        gameRef.current = next;
        setGame(next);
      }).catch((failure) => {
        if (!controller.signal.aborted) setError(`Could not update replay: ${message(failure)}`);
      }).finally(() => { pending = false; });
    }, 1600);
    return () => { clearInterval(timer); controller.abort(); };
  }, [game?.game_id, game?.auto_play]);

  useEffect(() => {
    setHint(null); setHintConfirmed(false); setHintError(null);
    if (!tips || busy || historyRevision !== null || !game || game.auto_play || game.status !== "active" || game.turn !== game.human_color) return;
    const controller = new AbortController();
    const current = game;
    void api<Hint>(`/games/${current.game_id}/hint`, { expected_revision: current.revision }, controller.signal)
      .then((next) => {
        if (controller.signal.aborted || busyRef.current || !tipsRef.current || gameRef.current?.game_id !== next.game_id || gameRef.current?.revision !== next.revision) return;
        setHint(next);
      }).catch((failure) => { if (!controller.signal.aborted) setHintError(message(failure)); });
    return () => controller.abort();
  }, [tips, busy, game?.game_id, game?.revision, game?.status, game?.turn, game?.human_color, game?.auto_play, historyRevision, hintRetry]);

  useEffect(() => {
    if (!hint || !tips || historyRevision !== null) return;
    let cancelled = false;
    const displayRequestId = displayIds.current.get(hint.hint_id) ?? requestId();
    displayIds.current.clear();
    displayIds.current.set(hint.hint_id, displayRequestId);
    let paintedFrame = 0;
    const frame = requestAnimationFrame(() => { paintedFrame = requestAnimationFrame(() => {
      if (cancelled || !tipsRef.current || gameRef.current?.revision !== hint.revision || gameRef.current?.game_id !== hint.game_id) return;
      void api(`/games/${hint.game_id}/hint-displays`, { hint_id: hint.hint_id, expected_revision: hint.revision, request_id: displayRequestId })
        .then(() => {
          displayIds.current.delete(hint.hint_id);
          if (!cancelled) { setHintConfirmed(true); setHintError(null); }
        })
        .catch((failure) => { if (!cancelled) setHintError(`Could not record hint display: ${message(failure)}`); });
    }); });
    return () => { cancelled = true; cancelAnimationFrame(frame); cancelAnimationFrame(paintedFrame); };
  }, [hint, tips, historyRevision, displayRetry]);

  const trackTask = useCallback((entry: TrackedTask) => {
    setTasks((current) => [entry, ...current.filter((item) => item.task.task_id !== entry.task.task_id)]);
    if (entry.task.status === "succeeded" && entry.task.kind === "review" && entry.task.result && entry.game_id === gameRef.current?.game_id) setReview(entry.task.result);
  }, []);

  useEffect(() => {
    if (!loaded) return;
    const saved = localStorage.getItem("nemothello_tasks");
    if (!saved) return;
    const controller = new AbortController();
    try {
      const entries: unknown = JSON.parse(saved);
      if (!Array.isArray(entries) || !entries.every((item) => item && typeof item.task_id === "string" && typeof item.game_id === "string" && ["review", "question", "branch"].includes(item.purpose))) throw new Error("Saved task list is invalid");
      void Promise.allSettled(entries.map((entry) => api<Task>(`/tasks/${encodeURIComponent(entry.task_id)}`, undefined, controller.signal))).then((results) => {
        if (controller.signal.aborted) return;
        results.forEach((result, index) => {
          if (result.status === "fulfilled") trackTask({ task: result.value, purpose: entries[index].purpose, game_id: entries[index].game_id, question: entries[index].question });
          else setError(`Could not restore task: ${message(result.reason)}`);
        });
      });
    } catch (failure) { setError(message(failure)); }
    return () => controller.abort();
  }, [loaded, trackTask]);

  useEffect(() => {
    if (!tasks.length) return;
    localStorage.setItem("nemothello_tasks", JSON.stringify(tasks.slice(0, 50).map((entry) => ({
      task_id: entry.task.task_id, purpose: entry.purpose, game_id: entry.game_id, question: entry.question,
    }))));
  }, [tasks]);

  useEffect(() => {
    if (!game || game.status !== "finished") return;
    const controller = new AbortController();
    const gameId = game.game_id;
    void api<Review | { task: Task | null }>(`/games/${gameId}/review`, undefined, controller.signal).then((result) => {
      if (controller.signal.aborted || gameRef.current?.game_id !== gameId) return;
      if ("task" in result) { if (result.task) trackTask({ task: result.task, purpose: "review", game_id: gameId }); }
      else setReview(result);
    }).catch((failure) => {
      if (!controller.signal.aborted && !(failure instanceof ApiError && failure.detail.code === "REVIEW_NOT_FOUND")) setError(message(failure));
    });
    return () => controller.abort();
  }, [game?.game_id, game?.status, trackTask]);

  useEffect(() => {
    const pending = tasks.filter(({ task }) => task.status === "queued" || task.status === "running");
    if (!pending.length) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      void Promise.allSettled(pending.map((entry) => api<Task>(`/tasks/${entry.task.task_id}`, undefined, controller.signal))).then((results) => {
        if (controller.signal.aborted) return;
        results.forEach((result, index) => {
          if (result.status === "fulfilled") trackTask({ ...pending[index], task: result.value });
          else setError(`Could not fetch task: ${message(result.reason)}. Select Refresh tasks to try again.`);
        });
      });
    }, 1600);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [tasks, trackTask]);

  const selectedEvent = game?.history.find((event) => event.revision === historyRevision);
  const board = historyRevision === 0 ? game?.initial_board : selectedEvent?.board ?? game?.board;
  const displayedTurn = historyRevision === 0 ? game?.initial_turn : selectedEvent ? selectedEvent.turn : game?.turn;
  const live = historyRevision === null;
  const canMove = !!game && live && !busy && !game.auto_play && game.status === "active" && game.turn === game.human_color && (!hint || hintConfirmed);
  const visibleHint = tips && live && hint?.game_id === game?.game_id && hint?.revision === game?.revision ? hint : null;
  const currentTasks = tasks.filter((entry) => entry.game_id === game?.game_id || (entry.purpose === "branch" && entry.task.game_id === game?.game_id));
  const reviewPending = currentTasks.some((entry) => entry.purpose === "review" && ["queued", "running"].includes(entry.task.status));
  const branchPending = currentTasks.some((entry) => entry.purpose === "branch" && ["queued", "running"].includes(entry.task.status));
  const branchRevision = historyRevision ?? game?.revision;
  const awaitingPass = !!selectedEvent && !!game?.history.some((event) => event.kind === "pass" && event.revision === selectedEvent.revision + 1);
  const branchUnavailable = branchRevision === undefined || displayedTurn === null || awaitingPass || !!game?.auto_play;
  const canChangeOpening = !!game && !game.parent_game_id && !game.auto_play && game.status === "active"
    && !game.history.some((event) => event.kind === "move" && event.actor === game.human_color);

  function changeSettings(color: Color, level: Difficulty) {
    if (busyRef.current) return;
    if (canChangeOpening) {
      if (color !== game?.human_color || level !== game?.difficulty) {
        void perform("Updating game", () => createGame(color, level));
      }
    } else {
      setHumanColor(color);
      setDifficulty(level);
    }
  }

  return (
    <main className="workspace">
      <header className="masthead"><a className="wordmark" href="/">Nemo<span>thello</span><span className="brand-dot" /></a></header>
      <section className="game-toolbar" aria-label="Game settings"><div className="color-picker">{!canChangeOpening && game && <span>Next game color</span>}<button aria-pressed={humanColor === "X"} onClick={() => changeSettings("X", difficulty)} disabled={!!busy || !loaded}><i className="mini-disc black" />Black</button><button aria-pressed={humanColor === "O"} onClick={() => changeSettings("O", difficulty)} disabled={!!busy || !loaded}><i className="mini-disc white" />White</button></div><label className="difficulty-picker">{!canChangeOpening && game && "Next game difficulty"}<select aria-label={canChangeOpening ? "Difficulty" : "Next game difficulty"} value={difficulty} disabled={!!busy || !loaded} onChange={(event) => changeSettings(humanColor, event.target.value as Difficulty)}><option value="easy">Beginner</option><option value="medium">Intermediate</option><option value="hard">Advanced</option></select></label><button className="primary" disabled={!!busy || !loaded} onClick={() => void perform("Creating game", () => createGame(humanColor, difficulty))}>New game</button>{recent.length > 0 && <label className="recent-picker">Recent games<select value={game?.game_id ?? ""} disabled={!!busy} onChange={(event) => { const id = event.target.value; if (id) void perform("Loading game", async () => acceptGame(await api<GameState>(`/games/${id}`))); }}><option value="" disabled>Select a game</option>{recent.map((item) => <option key={item.game_id} value={item.game_id}>{item.label}</option>)}</select></label>}</section>
      {error && <div className="error-banner" role="alert"><span>{error}</span><button aria-label="Dismiss error" onClick={() => setError(null)}>×</button></div>}
      {!loaded && !busy && bootStarted.current && <button className="primary connection-retry" onClick={() => {
        bootStarted.current = false;
        setBootRetry((attempt) => attempt + 1);
      }}>Reconnect</button>}
      <div className="play-layout">
        <section className="board-panel" aria-label="Othello board"><div className="board-topline">{game?.difficulty && <span className="turn-label" aria-label="Opponent difficulty">{difficultyName[game.difficulty]}</span>}<span className="turn-label" aria-live="polite">{busy ?? (game ? live && game.status === "finished" ? "Game over" : displayedTurn ? live ? game.turn === game.human_color ? "Your turn" : "AI's turn" : `${colorName(displayedTurn)} to move` : "Game over" : "Preparing a new game…")}</span></div>
          <div className="board-with-labels"><div className="column-labels" aria-hidden="true">{"abcdefgh".split("").map((column) => <span key={column}>{column}</span>)}</div><div className="board-rows"><div className="row-labels" aria-hidden="true">{Array.from({ length: 8 }, (_, row) => <span key={row}>{row + 1}</span>)}</div><div className={`board ${board ? "" : "empty-board"}`} role="group" aria-label={board ? "Board, a1 is at the top left" : "No game started"}>{Array.from({ length: 64 }, (_, index) => {
            const row = Math.floor(index / 8), column = index % 8;
            const coordinate = `${"abcdefgh"[column]}${row + 1}`, cell = board?.[row]?.[column] ?? ".";
            const legal = live && !!game?.legal_moves.includes(coordinate), recommended = visibleHint?.recommended_move === coordinate;
            return <button key={coordinate} className={`square ${recommended ? "recommended" : ""}`} disabled={!canMove || !legal} aria-label={`${coordinate}, ${cell === "X" ? "black disc" : cell === "O" ? "white disc" : "empty"}${legal ? ", legal move" : ""}${recommended ? ", recommended move" : ""}`} onClick={() => { if (game) void perform("Playing move", async () => acceptGame(await api<GameState>(`/games/${game.game_id}/moves`, { coordinate, expected_revision: game.revision, request_id: requestId() }))); }}>{cell !== "." && <span className={`disc ${cell === "X" ? "black" : "white"}`} />}{cell === "." && legal && <span className="legal-marker" />}{recommended && <span className="hint-ring" />}</button>;
          })}</div></div></div>
          {game && (game.auto_play || !live || (game.status === "active" && game.turn !== game.human_color && !busy)) && <div className="board-footer">
            {!live && <><span>{historyRevision === 0 ? "Starting position" : `Position ${historyRevision}`}</span><button onClick={() => setHistoryRevision(null)}>Back to final position</button></>}
            {game.auto_play && <span>Replaying with hints</span>}
            {game.status === "active" && !game.auto_play && game.turn !== game.human_color && !busy && <button className="primary" onClick={() => void requestAi(game)}>Retry AI move</button>}
          </div>}
        </section>
        <aside className="side-panel"><section className="score-card" aria-label={live ? "Disc count" : "Disc count at selected position"}><div className="score-line"><div><i className="mini-disc black" /><span>Black {game?.human_color === "X" && <small>You</small>}</span><strong>{board ? board.join("").split("X").length - 1 : "—"}</strong></div><div><i className="mini-disc white" /><span>White {game?.human_color === "O" && <small>You</small>}</span><strong>{board ? board.join("").split("O").length - 1 : "—"}</strong></div></div>{game?.result && <p className="result-label">{!live && "Final · "}{game.result.winner === "draw" ? "Draw" : game.result.winner === game.human_color ? "You win" : "AI wins"}<span>{game.result.black_count} : {game.result.white_count}</span></p>}</section>
          {game?.status !== "finished" && <section className="tips-card">
            <div className="card-heading">
              <span className="section-label">Hints</span>
              <button className={`toggle ${tips ? "on" : ""}`} role="switch" aria-checked={tips} aria-label="Move hints" disabled={!game || game.auto_play || game.status !== "active"} onClick={() => { tipsRef.current = !tips; setTips(!tips); }}><span /></button>
            </div>
            {tips && (hintError || (live && game?.turn === game?.human_color && (!visibleHint || !hintConfirmed))) && <div className="tip-status" aria-live="polite">
              {hintError ? <><span className="inline-error">{hintError}</span><button onClick={() => hint ? setDisplayRetry((value) => value + 1) : setHintRetry((value) => value + 1)}>Retry hint</button></> : "Preparing hint…"}
            </div>}
          </section>}
          {game?.status === "finished" && <section className="history-card" aria-label="Move history"><span className="section-label">Move history</span><div className="history-list"><button className={historyRevision === 0 ? "selected" : ""} onClick={() => setHistoryRevision(0)}>Starting position</button>{game.history.map((event) => <button key={event.event_index} className={historyRevision === event.revision ? "selected" : ""} onClick={() => setHistoryRevision(event.revision)}><span><small>{event.event_index + 1}</small>{colorName(event.actor)}</span><strong>{event.kind === "pass" ? "Pass" : event.coordinate}</strong></button>)}</div></section>}
        </aside>
      </div>
      {game?.status === "finished" && (
        <section className="review-panel">
          <div className="review-heading">
            {review && <h2>Review</h2>}
            {!review && <button className="primary" disabled={!!busy || reviewPending} onClick={() => void perform("Requesting review", async () => trackTask({
              task: await api<Task>(`/games/${game.game_id}/reviews`, { request_id: requestId() }), purpose: "review", game_id: game.game_id,
            }))}>{reviewPending ? "Generating review" : "Review game"}</button>}
          </div>
          {review ? <>
            <div className="explanation">{review.explanation}</div>
            <ReviewDetails review={review} selectRevision={setHistoryRevision} />
            <form className="question-form" onSubmit={(event) => {
              event.preventDefault();
              const text = question.trim();
              if (text) void perform("Sending question", async () => {
                const contextualQuestion = historyRevision === null ? text : `For position revision ${historyRevision}: ${text}`;
                trackTask({ task: await api<Task>(`/games/${game.game_id}/review/questions`, { question: contextualQuestion, request_id: requestId() }), purpose: "question", game_id: game.game_id, question: contextualQuestion });
                setQuestion("");
              });
            }}>
              <div><textarea id="review-question" aria-label="Review question" value={question} maxLength={1900} onChange={(event) => setQuestion(event.target.value)} placeholder={historyRevision === null ? "Ask about this game…" : historyRevision === 0 ? "Ask about the starting position…" : `Ask about position ${historyRevision}…`} required /><button className="primary" disabled={!!busy || !question.trim()}>Ask</button></div>
            </form>
          </> : null}
        </section>
      )}
      {game?.status === "finished" && historyRevision !== null && (
        <section className="branch-panel">
          {awaitingPass && <p>Select a position after the pass.</p>}
          {displayedTurn === null && <p>Select a position before the game ends.</p>}
          <div className="branch-actions">
            <button disabled={!!busy || branchUnavailable} onClick={() => void perform("Creating branch", async () => acceptGame(await api<GameState>(`/games/${game.game_id}/branches`, {
              revision: branchRevision, mode: "manual", request_id: requestId(),
            })))}>Continue from here</button>
            <button className="primary" disabled={!!busy || branchPending || branchUnavailable} onClick={() => void perform("Starting hint replay", async () => trackTask({
              task: await api<Task>(`/games/${game.game_id}/branches`, { revision: branchRevision, mode: "follow_hints", request_id: requestId() }), purpose: "branch", game_id: game.game_id,
            }))}>{branchPending ? "Replaying" : "Replay with hints"}</button>
          </div>
        </section>
      )}
      <TaskList entries={currentTasks} busy={!!busy} refresh={() => void perform("Refresh tasks", async () => {
        for (const entry of currentTasks) trackTask({ ...entry, task: await api<Task>(`/tasks/${entry.task.task_id}`) });
      })} openGame={(id) => void perform("Loading branch", async () => acceptGame(await api<GameState>(`/games/${id}`)))} repeatQuestion={(text) => {
        setQuestion(text);
        document.getElementById("review-question")?.focus();
      }} />
    </main>
  );
}
