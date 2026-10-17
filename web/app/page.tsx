"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, requestId } from "@/lib/api";
import { ReviewDetails } from "@/components/review-details";
import { TaskList } from "@/components/task-list";
import type { Color, Difficulty, GameState, Hint, Review, Task, TrackedTask } from "@/lib/types";

type RecentGame = { game_id: string; label: string };
const difficultyName: Record<Difficulty, string> = { easy: "初级", medium: "中级", hard: "高级" };
const colorName = (color: Color) => color === "X" ? "黑方" : "白方";

function message(error: unknown) {
  if (error instanceof ApiError) return `${error.message}${error.detail.request_id ? ` · 请求 ${error.detail.request_id}` : ""}`;
  return error instanceof Error ? error.message : "请求未完成，请重试";
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
      { game_id: next.game_id, label: `${next.parent_game_id ? "分支" : "对局"} · ${colorName(next.human_color)} · ${next.game_id.slice(0, 8)}` },
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
        catch (refreshFailure) { setError(`${message(failure)}；重新获取棋盘失败：${message(refreshFailure)}`); }
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
    void perform("准备对局", async () => {
      await api<{ ready: boolean }>("/session");
      const saved = localStorage.getItem("nemothello_recent_games");
      if (saved) {
        try {
          const parsed: unknown = JSON.parse(saved);
          if (!Array.isArray(parsed) || !parsed.every((item) => item && typeof item.game_id === "string" && typeof item.label === "string")) throw new Error("保存的对局列表格式错误");
          setRecent(parsed);
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

  const requestAi = useCallback((current: GameState) => perform("AI 正在选择落子", async () => {
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
        if (!controller.signal.aborted) setError(`重演棋盘更新失败：${message(failure)}`);
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
        .catch((failure) => { if (!cancelled) setHintError(`提示记录失败：${message(failure)}`); });
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
      if (!Array.isArray(entries) || !entries.every((item) => item && typeof item.task_id === "string" && typeof item.game_id === "string" && ["review", "question", "branch"].includes(item.purpose))) throw new Error("保存的任务列表格式错误");
      void Promise.allSettled(entries.map((entry) => api<Task>(`/tasks/${encodeURIComponent(entry.task_id)}`, undefined, controller.signal))).then((results) => {
        if (controller.signal.aborted) return;
        results.forEach((result, index) => {
          if (result.status === "fulfilled") trackTask({ task: result.value, purpose: entries[index].purpose, game_id: entries[index].game_id, question: entries[index].question });
          else setError(`恢复任务失败：${message(result.reason)}`);
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
          else setError(`任务查询失败：${message(result.reason)}。点击「刷新任务」重新查询。`);
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
        void perform("更新新对局", () => createGame(color, level));
      }
    } else {
      setHumanColor(color);
      setDifficulty(level);
    }
  }

  return (
    <main className="workspace">
      <header className="masthead"><a className="wordmark" href="/">Nemo<span>thello</span><span className="brand-dot" /></a><p>与 AI 对战，在复盘中理解每一步。</p><span className="header-tag">翻转棋 · 8 × 8</span></header>
      {game && <p className="board-note">对手：{game.difficulty ? `${difficultyName[game.difficulty]} · ` : ""}{game.opponent_name} · 提示与复盘分析由 Edax 提供，复盘讲解由 Nemotron 生成。</p>}
      <section className="game-toolbar" aria-label="对局设置"><div className="color-picker"><span>{canChangeOpening ? "你的颜色" : "新对局颜色"}</span><button aria-pressed={humanColor === "X"} onClick={() => changeSettings("X", difficulty)} disabled={!!busy || !loaded}><i className="mini-disc black" />执黑</button><button aria-pressed={humanColor === "O"} onClick={() => changeSettings("O", difficulty)} disabled={!!busy || !loaded}><i className="mini-disc white" />执白</button></div><label className="difficulty-picker">{canChangeOpening ? "对局难度" : "新对局难度"}<select value={difficulty} disabled={!!busy || !loaded} onChange={(event) => changeSettings(humanColor, event.target.value as Difficulty)}><option value="easy">初级</option><option value="medium">中级</option><option value="hard">高级</option></select></label><button className="primary" disabled={!!busy || !loaded} onClick={() => void perform("创建对局", () => createGame(humanColor, difficulty))}>新对局 <span aria-hidden="true">↗</span></button>{recent.length > 0 && <label className="recent-picker">最近对局<select value={game?.game_id ?? ""} disabled={!!busy} onChange={(event) => { const id = event.target.value; if (id) void perform("载入对局", async () => acceptGame(await api<GameState>(`/games/${id}`))); }}><option value="" disabled>选择对局</option>{recent.map((item) => <option key={item.game_id} value={item.game_id}>{item.label}</option>)}</select></label>}</section>
      {error && <div className="error-banner" role="alert"><span>{error}</span><button aria-label="关闭错误提示" onClick={() => setError(null)}>×</button></div>}
      {!loaded && !busy && bootStarted.current && <button className="primary connection-retry" onClick={() => {
        bootStarted.current = false;
        setBootRetry((attempt) => attempt + 1);
      }}>重试连接</button>}
      <div className="play-layout">
        <section className="board-panel" aria-label="翻转棋棋盘"><div className="board-topline"><span className="section-label">对局</span><span className="turn-label" aria-live="polite">{busy ?? (game ? live && game.status === "finished" ? "对局结束" : displayedTurn ? `${colorName(displayedTurn)}行动${live ? game.turn === game.human_color ? " · 轮到你" : " · AI" : " · 历史局面"}` : "对局结束" : "正在准备新对局…")}</span></div>
          <div className="board-with-labels"><div className="column-labels" aria-hidden="true">{"abcdefgh".split("").map((column) => <span key={column}>{column}</span>)}</div><div className="board-rows"><div className="row-labels" aria-hidden="true">{Array.from({ length: 8 }, (_, row) => <span key={row}>{row + 1}</span>)}</div><div className={`board ${board ? "" : "empty-board"}`} role="group" aria-label={board ? "棋盘，坐标 a1 位于左上" : "尚未开始对局"}>{Array.from({ length: 64 }, (_, index) => {
            const row = Math.floor(index / 8), column = index % 8;
            const coordinate = `${"abcdefgh"[column]}${row + 1}`, cell = board?.[row]?.[column] ?? ".";
            const legal = live && !!game?.legal_moves.includes(coordinate), recommended = visibleHint?.recommended_move === coordinate;
            return <button key={coordinate} className={`square ${recommended ? "recommended" : ""}`} disabled={!canMove || !legal} aria-label={`${coordinate}，${cell === "X" ? "黑子" : cell === "O" ? "白子" : "空位"}${legal ? "，合法落子点" : ""}${recommended ? "，推荐点" : ""}`} onClick={() => { if (game) void perform("提交落子", async () => acceptGame(await api<GameState>(`/games/${game.game_id}/moves`, { coordinate, expected_revision: game.revision, request_id: requestId() }))); }}>{cell !== "." && <span className={`disc ${cell === "X" ? "black" : "white"}`} />}{cell === "." && legal && <span className="legal-marker" />}{recommended && <span className="hint-ring" />}</button>;
          })}</div></div></div>
          {!game && <p className="board-note">黑方先行。选择一个合法点，翻转夹住的对方棋子。</p>}
          {game && <div className="board-footer">
            <span>{game.auto_play ? "按提示重演正在推进" : live ? "当前局面" : `历史局面 · 版本 ${historyRevision}`}</span>
            <button onClick={() => setHistoryRevision(null)} disabled={live}>返回当前局面</button>
            {game.status === "active" && !game.auto_play && game.turn !== game.human_color && !busy && <button className="primary" onClick={() => void requestAi(game)}>重试 AI 落子</button>}
          </div>}
        </section>
        <aside className="side-panel"><section className="score-card"><span className="section-label">{live ? "棋子数" : "所选局面棋子数"}</span><div className="score-line"><div><i className="mini-disc black" /><span>黑方 {game?.human_color === "X" && <small>你</small>}</span><strong>{board ? board.join("").split("X").length - 1 : "—"}</strong></div><div><i className="mini-disc white" /><span>白方 {game?.human_color === "O" && <small>你</small>}</span><strong>{board ? board.join("").split("O").length - 1 : "—"}</strong></div></div>{game?.result && <p className="result-label">{!live && "本盘终局 · "}{game.result.winner === "draw" ? "双方和棋" : game.result.winner === game.human_color ? "你赢了这盘" : "AI 赢了这盘"}<span>{game.result.black_count} : {game.result.white_count}</span></p>}</section>
          <section className="tips-card">
            <div className="card-heading">
              <span className="section-label">推荐点</span>
              <button className={`toggle ${tips ? "on" : ""}`} role="switch" aria-checked={tips} aria-label="推荐点提示" disabled={!game || game.auto_play || game.status !== "active"} onClick={() => { tipsRef.current = !tips; setTips(!tips); }}><span /></button>
            </div>
            {tips && <div className="tip-status" aria-live="polite">
              {hintError ? <><span className="inline-error">{hintError}</span><button onClick={() => hint ? setDisplayRetry((value) => value + 1) : setHintRetry((value) => value + 1)}>重试提示</button></> : !live ? "返回当前局面查看提示" : game?.turn !== game?.human_color ? "等待你的回合" : visibleHint ? `推荐 ${visibleHint.recommended_move}${hintConfirmed ? "" : " · 记录展示中"}` : "正在获取推荐点…"}
            </div>}
          </section>
          <section className="history-card"><div className="card-heading"><span className="section-label">棋谱</span><span className="muted">{game?.history.length ?? 0} 个事件</span></div><div className="history-list">{game ? <><button className={historyRevision === 0 ? "selected" : ""} onClick={() => setHistoryRevision(0)}><span>初始局面</span><span>开始</span></button>{game.history.map((event) => <button key={event.event_index} className={historyRevision === event.revision ? "selected" : ""} onClick={() => setHistoryRevision(event.revision)}><span><small>{event.event_index + 1}</small>{colorName(event.actor)}</span><strong>{event.kind === "pass" ? "跳过回合" : event.coordinate}</strong></button>)}</> : <p className="muted">对局开始后，落子会保存在这里。</p>}</div></section>
        </aside>
      </div>
      {game?.status === "finished" && (
        <section className="review-panel">
          <div className="review-heading">
            <div><span className="section-label">独立复盘</span><h2>理解关键手，再试一种走法。</h2></div>
            <button className="primary" disabled={!!busy || reviewPending || !!review} onClick={() => void perform("创建复盘任务", async () => trackTask({
              task: await api<Task>(`/games/${game.game_id}/reviews`, { request_id: requestId() }), purpose: "review", game_id: game.game_id,
            }))}>{review ? "复盘已生成" : reviewPending ? "正在生成复盘" : "生成 Nemotron 复盘"}</button>
          </div>
          {review ? <>
            <div className="explanation">{review.explanation}</div>
            <ReviewDetails review={review} selectRevision={setHistoryRevision} />
            <form className="question-form" onSubmit={(event) => {
              event.preventDefault();
              const text = question.trim();
              if (text) void perform("提交复盘问题", async () => {
                const contextualQuestion = historyRevision === null ? text : `针对局面版本 ${historyRevision}：${text}`;
                trackTask({ task: await api<Task>(`/games/${game.game_id}/review/questions`, { question: contextualQuestion, request_id: requestId() }), purpose: "question", game_id: game.game_id, question: contextualQuestion });
                setQuestion("");
              });
            }}>
              <label htmlFor="review-question">这一步为什么这样下？</label>
              {historyRevision !== null && <p className="muted">这次追问关联局面版本 {historyRevision}。</p>}
              <div><textarea id="review-question" value={question} maxLength={1900} onChange={(event) => setQuestion(event.target.value)} placeholder="问问这一盘的局势和候选点差别…" required /><button className="primary" disabled={!!busy || !question.trim()}>追问</button></div>
            </form>
          </> : <p className="muted">复盘会结合本盘棋谱与 Edax 分析，解释关键选择。</p>}
        </section>
      )}
      {game && (
        <section className="branch-panel">
          <div>
            <span className="section-label">从这里重新尝试</span>
            <h2>{historyRevision === null ? "选择棋谱中的一个局面" : `从版本 ${historyRevision} 创建分支`}</h2>
            <p>原对局保留，对手会重新计算每一步。按提示重演会保存新棋谱的真实结果。</p>
            {awaitingPass && <p>这一方需要跳过回合。请选择棋谱中跳过回合后的局面。</p>}
            {displayedTurn === null && <p>这个局面已经结束。请选择终局之前的局面。</p>}
          </div>
          <div className="branch-actions">
            <button disabled={!!busy || branchUnavailable} onClick={() => void perform("创建手动分支", async () => acceptGame(await api<GameState>(`/games/${game.game_id}/branches`, {
              revision: branchRevision, mode: "manual", request_id: requestId(),
            })))}>亲自尝试</button>
            <button className="primary" disabled={!!busy || branchPending || branchUnavailable} onClick={() => void perform("创建提示重演任务", async () => trackTask({
              task: await api<Task>(`/games/${game.game_id}/branches`, { revision: branchRevision, mode: "follow_hints", request_id: requestId() }), purpose: "branch", game_id: game.game_id,
            }))}>{branchPending ? "正在重演" : "按提示重演"}</button>
          </div>
        </section>
      )}
      <TaskList entries={currentTasks} busy={!!busy} refresh={() => void perform("刷新任务", async () => {
        for (const entry of currentTasks) trackTask({ ...entry, task: await api<Task>(`/tasks/${entry.task.task_id}`) });
      })} openGame={(id) => void perform("载入分支", async () => acceptGame(await api<GameState>(`/games/${id}`)))} repeatQuestion={(text) => {
        setQuestion(text);
        document.getElementById("review-question")?.focus();
      }} />
      <footer className="site-footer"><span>Nemothello</span><p>AI 落子 · 自由选择提示 · 终局独立复盘</p></footer>
    </main>
  );
}
