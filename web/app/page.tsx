"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, requestId } from "@/lib/api";
import { LanguageSwitch, useLocale } from "@/lib/locale";
import { ReviewDetails } from "@/components/review-details";
import { ReviewCoach } from "@/components/review-coach";
import type { Practice, Variation } from "@/components/review-coach";
import { TaskList } from "@/components/task-list";
import type { Color, Difficulty, GameState, Hint, Review, Task, TrackedTask } from "@/lib/types";

type RecentGame = { game_id: string; label: string };
const colorName = (color: Color) => color === "X" ? "Black" : "White";

function message(error: unknown) {
  if (error instanceof ApiError) return `${error.message}${error.detail.request_id ? ` · Request ${error.detail.request_id}` : ""}`;
  return error instanceof Error ? error.message : "Request failed. Please try again.";
}

export default function Home() {
  const {locale, t} = useLocale();
  const localizedColor = (color: Color) => color === "X" ? t("Black", "黑方") : t("White", "白方");
  const localizedDifficulty: Record<Difficulty, string> = {easy: t("Beginner", "初级"), medium: t("Intermediate", "中级"), hard: t("Advanced", "高级")};
  const busyMessages: Record<string, string> = {"Preparing game": "准备对局", "AI is choosing a move": "AI 正在落子", "Continuing your retry": "正在创建续下对局", "Updating game": "更新对局", "Creating game": "创建对局", "Loading game": "加载对局", "Playing move": "落子中", "Requesting review": "分析棋局", "Sending question": "发送问题", "Creating branch": "创建分支", "Starting hint replay": "开始提示回放", "Refresh tasks": "刷新任务", "Loading branch": "加载分支"};
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
  const [practice, setPractice] = useState<Practice | null>(null);
  const [variation, setVariation] = useState<Variation | null>(null);
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
    setPractice(null);
    setVariation(null);
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
    if (entry.task.kind === "review" && entry.game_id === gameRef.current?.game_id) {
      if (entry.task.status === "succeeded" && entry.task.result) {
        setReview(entry.task.result);
        const first = entry.task.result.key_moves[0]?.revision ?? null;
        setHistoryRevision((current) => current ?? first);
      } else if (entry.task.status === "running" || entry.task.status === "failed") {
        void api<Review | { task: Task | null }>(`/games/${entry.game_id}/review`).then((result) => {
          if (!("task" in result) && gameRef.current?.game_id === entry.game_id) {
            setReview(result);
            setHistoryRevision((current) => current ?? result.key_moves[0]?.revision ?? null);
          }
        }).catch((failure) => { if (gameRef.current?.game_id === entry.game_id) setError(message(failure)); });
      }
    }
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
      else {
        setReview(result);
        setHistoryRevision((current) => current ?? result.key_moves[0]?.revision ?? null);
      }
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
  const selectedEvidence = review?.evidence.find((entry) => entry.revision === historyRevision);
  const variationComparison = variation && review?.evidence.find((entry) => entry.revision === variation.revision)?.comparisons?.find((entry) => entry.coordinate === variation.coordinate);
  const variationFrame = variation && variationComparison?.frames[variation.frame];
  const board = variationFrame?.board ?? selectedEvidence?.analysis.board ?? (historyRevision === 0 ? game?.initial_board : selectedEvent?.board ?? game?.board);
  const displayedTurn = variationFrame ? variationFrame.turn : selectedEvidence?.actor ?? (historyRevision === 0 ? game?.initial_turn : selectedEvent ? selectedEvent.turn : game?.turn);
  const live = historyRevision === null;
  const canPractice = !!practice && practice.coordinate === null && practice.revision === historyRevision && !!selectedEvidence && selectedEvidence.actor === game?.human_color && !busy && !variation;
  const canMove = canPractice || (!!game && live && !busy && !game.auto_play && game.status === "active" && game.turn === game.human_color && (!hint || hintConfirmed));
  const visibleHint = tips && live && hint?.game_id === game?.game_id && hint?.revision === game?.revision ? hint : null;
  const currentTasks = tasks.filter((entry) => entry.game_id === game?.game_id || (entry.purpose === "branch" && entry.task.game_id === game?.game_id));
  const reviewPending = currentTasks.some((entry) => entry.purpose === "review" && ["queued", "running"].includes(entry.task.status));
  const branchPending = currentTasks.some((entry) => entry.purpose === "branch" && ["queued", "running"].includes(entry.task.status));
  const branchRevision = historyRevision ?? game?.revision;
  const awaitingPass = !!selectedEvent && !!game?.history.some((event) => event.kind === "pass" && event.revision === selectedEvent.revision + 1);
  const branchUnavailable = branchRevision === undefined || displayedTurn === null || awaitingPass || !!game?.auto_play;
  const canChangeOpening = !!game && !game.parent_game_id && !game.auto_play && game.status === "active"
    && !game.history.some((event) => event.kind === "move" && event.actor === game.human_color);

  function selectPosition(revision: number | null) {
    setPractice(null);
    setVariation(null);
    setHistoryRevision(revision);
  }

  function startPractice(revision: number) {
    setHistoryRevision(revision);
    setVariation(null);
    setPractice({revision, coordinate: null});
    document.getElementById("game-board")?.scrollIntoView({block: "start", behavior: "instant"});
  }

  function showVariation(value: Variation | null) {
    setVariation(value);
    if (value) { setPractice(null); setHistoryRevision(value.revision); }
    document.getElementById("game-board")?.scrollIntoView({block: "start", behavior: "instant"});
  }

  function continuePractice(revision: number, coordinate: string) {
    if (!game) return;
    void perform("Continuing your retry", async () => {
      const branch = await api<GameState>(`/games/${game.game_id}/branches`, {
        revision, mode: "manual", request_id: requestId(),
      });
      acceptGame(branch);
      acceptGame(await api<GameState>(`/games/${branch.game_id}/moves`, {
        coordinate, expected_revision: branch.revision, request_id: requestId(),
      }));
    });
  }

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
      <header className="masthead"><a className="wordmark" href="/">Nemo<span>thello</span><span className="brand-dot" /></a><LanguageSwitch /></header>
      <section className="game-toolbar" aria-label={t("Game settings", "对局设置")}><div className="color-picker">{!canChangeOpening && game && <span>{t("Next game color", "下一局执棋")}</span>}<button aria-pressed={humanColor === "X"} onClick={() => changeSettings("X", difficulty)} disabled={!!busy || !loaded}><i className="mini-disc black" />{t("Black", "黑方")}</button><button aria-pressed={humanColor === "O"} onClick={() => changeSettings("O", difficulty)} disabled={!!busy || !loaded}><i className="mini-disc white" />{t("White", "白方")}</button></div><label className="difficulty-picker">{!canChangeOpening && game && t("Next game difficulty", "下一局难度")}<select aria-label={canChangeOpening ? t("Difficulty", "难度") : t("Next game difficulty", "下一局难度")} value={difficulty} disabled={!!busy || !loaded} onChange={(event) => changeSettings(humanColor, event.target.value as Difficulty)}><option value="easy">{t("Beginner", "初级")}</option><option value="medium">{t("Intermediate", "中级")}</option><option value="hard">{t("Advanced", "高级")}</option></select></label><button className="primary" disabled={!!busy || !loaded} onClick={() => void perform("Creating game", () => createGame(humanColor, difficulty))}>{t("New game", "新对局")}</button>{recent.length > 0 && <label className="recent-picker">{t("Recent games", "最近对局")}<select value={game?.game_id ?? ""} disabled={!!busy} onChange={(event) => { const id = event.target.value; if (id) void perform("Loading game", async () => acceptGame(await api<GameState>(`/games/${id}`))); }}><option value="" disabled>{t("Select a game", "选择对局")}</option>{recent.map((item) => <option key={item.game_id} value={item.game_id}>{locale === "zh" ? item.label.replace(/^Branch/, "分支").replace(/^Game/, "对局").replace(/^Saved game/, "已保存对局").replace(/Black/, "黑方").replace(/White/, "白方") : item.label}</option>)}</select></label>}</section>
      {error && <div className="error-banner" role="alert"><span>{error}</span><button aria-label={t("Dismiss error", "关闭错误信息")} onClick={() => setError(null)}>×</button></div>}
      {!loaded && !busy && bootStarted.current && <button className="primary connection-retry" onClick={() => {
        bootStarted.current = false;
        setBootRetry((attempt) => attempt + 1);
      }}>{t("Reconnect", "重新连接")}</button>}
      <div className="play-layout">
        <section className="board-panel" id="game-board" aria-label={t("Othello board", "翻转棋棋盘")}><div className="board-topline">{game?.difficulty && <span className="turn-label" aria-label={t("Opponent difficulty", "对手难度")}>{localizedDifficulty[game.difficulty]}</span>}<span className="turn-label" aria-live="polite">{(busy ? locale === "zh" ? busyMessages[busy] ?? busy : busy : null) ?? (game ? live && game.status === "finished" ? t("Game over", "对局结束") : displayedTurn ? live ? game.turn === game.human_color ? t("Your turn", "轮到你") : t("AI's turn", "轮到 AI") : t(`${localizedColor(displayedTurn)} to move`, `轮到${localizedColor(displayedTurn)}`) : t("Game over", "对局结束") : t("Preparing a new game…", "正在准备新对局…"))}</span></div>
          <div className="board-with-labels"><div className="column-labels" aria-hidden="true">{"abcdefgh".split("").map((column) => <span key={column}>{column}</span>)}</div><div className="board-rows"><div className="row-labels" aria-hidden="true">{Array.from({ length: 8 }, (_, row) => <span key={row}>{row + 1}</span>)}</div><div className={`board ${board ? "" : "empty-board"}`} role="group" aria-label={board ? t("Board, a1 is at the top left", "棋盘，左上角为 a1") : t("No game started", "尚未开始对局")}>{Array.from({ length: 64 }, (_, index) => {
            const row = Math.floor(index / 8), column = index % 8;
            const coordinate = `${"abcdefgh"[column]}${row + 1}`, cell = board?.[row]?.[column] ?? ".";
            const legal = canPractice ? !!selectedEvidence?.analysis.candidates.some((entry) => entry.coordinate === coordinate) : live && !!game?.legal_moves.includes(coordinate);
            const recommended = !variation && (practice?.coordinate ? selectedEvidence?.recommended_move === coordinate : visibleHint?.recommended_move === coordinate);
            return <button key={coordinate} className={`square ${recommended ? "recommended" : ""}`} disabled={!canMove || !legal} aria-label={`${coordinate}, ${cell === "X" ? t("black disc", "黑棋") : cell === "O" ? t("white disc", "白棋") : t("empty", "空位")}${legal ? t(", legal move", "，合法落点") : ""}${recommended ? t(", recommended move", "，推荐落点") : ""}`} onClick={() => { if (canPractice && practice) { setPractice({...practice, coordinate}); document.getElementById("review-coaching")?.scrollIntoView({block: "start", behavior: "instant"}); return; } if (game) void perform("Playing move", async () => acceptGame(await api<GameState>(`/games/${game.game_id}/moves`, { coordinate, expected_revision: game.revision, request_id: requestId() }))); }}>{cell !== "." && <span className={`disc ${cell === "X" ? "black" : "white"}`} />}{cell === "." && legal && <span className="legal-marker" />}{recommended && <span className="hint-ring" />}</button>;
          })}</div></div></div>
          {game && (game.auto_play || !live || (game.status === "active" && game.turn !== game.human_color && !busy)) && <div className="board-footer">
            {!live && !variation && <><span>{historyRevision === 0 ? t("Starting position", "初始局面") : t(`Position ${historyRevision}`, `局面 ${historyRevision}`)}</span><button onClick={() => selectPosition(null)}>{t("Back to final position", "返回终局")}</button></>}
            {variation && variationComparison && <><span>{t("Search line", "搜索续着")} · {variationComparison.frames.slice(1, variation.frame + 1).map((frame) => frame.coordinate).join(" → ") || t("Starting position", "初始局面")}</span><button aria-label={t("Previous search move", "上一步搜索落子")} disabled={variation.frame === 0} onClick={() => setVariation({...variation, frame: variation.frame - 1})}>{t("Previous", "上一步")}</button><span>{variation.frame} / {variationComparison.frames.length - 1}</span><button aria-label={t("Next search move", "下一步搜索落子")} disabled={variation.frame === variationComparison.frames.length - 1} onClick={() => setVariation({...variation, frame: variation.frame + 1})}>{t("Next", "下一步")}</button><button onClick={() => setVariation(null)}>{t("Back to position", "返回局面")}</button></>}
            {game.auto_play && <span>{t("Replaying with hints", "正在按提示回放")}</span>}
            {game.status === "active" && !game.auto_play && game.turn !== game.human_color && !busy && <button className="primary" onClick={() => void requestAi(game)}>{t("Retry AI move", "重试 AI 落子")}</button>}
          </div>}
        </section>
        <aside className="side-panel"><section className="score-card" aria-label={live ? t("Disc count", "棋子数量") : t("Disc count at selected position", "当前局面的棋子数量")}><div className="score-line"><div><i className="mini-disc black" /><span>{t("Black", "黑方")} {game?.human_color === "X" && <small>{t("You", "你")}</small>}</span><strong>{board ? board.join("").split("X").length - 1 : "—"}</strong></div><div><i className="mini-disc white" /><span>{t("White", "白方")} {game?.human_color === "O" && <small>{t("You", "你")}</small>}</span><strong>{board ? board.join("").split("O").length - 1 : "—"}</strong></div></div>{game?.result && <p className="result-label">{!live && t("Final · ", "终局 · ")}{game.result.winner === "draw" ? t("Draw", "和棋") : game.result.winner === game.human_color ? t("You win", "你获胜") : t("AI wins", "AI 获胜")}<span>{game.result.black_count} : {game.result.white_count}</span></p>}</section>
          {game?.status !== "finished" && <section className="tips-card">
            <div className="card-heading">
              <span className="section-label">{t("Hints", "推荐点")}</span>
              <button className={`toggle ${tips ? "on" : ""}`} role="switch" aria-checked={tips} aria-label={t("Move hints", "落点提示")} disabled={!game || game.auto_play || game.status !== "active"} onClick={() => { tipsRef.current = !tips; setTips(!tips); }}><span /></button>
            </div>
            {tips && (hintError || (live && game?.turn === game?.human_color && (!visibleHint || !hintConfirmed))) && <div className="tip-status" aria-live="polite">
              {hintError ? <><span className="inline-error">{hintError}</span><button onClick={() => hint ? setDisplayRetry((value) => value + 1) : setHintRetry((value) => value + 1)}>{t("Retry hint", "重试提示")}</button></> : t("Preparing hint…", "正在计算推荐点…")}
            </div>}
          </section>}
          {game?.status === "finished" && <section className="history-card" aria-label={t("Move history", "棋谱")}><span className="section-label">{t("Move history", "棋谱")}</span><div className="history-list"><button className={historyRevision === 0 ? "selected" : ""} onClick={() => selectPosition(0)}>{t("Starting position", "初始局面")}</button>{game.history.map((event) => <button key={event.event_index} className={historyRevision === event.revision ? "selected" : ""} onClick={() => selectPosition(event.revision)}><span><small>{event.event_index + 1}</small>{localizedColor(event.actor)}</span><strong>{event.kind === "pass" ? t("Pass", "跳过") : event.coordinate}</strong></button>)}</div></section>}
        </aside>
      </div>
      {game?.status === "finished" && (
        <section className="review-panel" id="review-coaching">
          <div className="review-heading">
            <h2>{t("Review", "复盘")}</h2>
            {(!review || review.format_version !== "grounded-v1" || review.coaching_status === "failed") && <button className="primary" disabled={!!busy || reviewPending} onClick={() => void perform("Requesting review", async () => trackTask({
              task: await api<Task>(`/games/${game.game_id}/reviews`, { request_id: requestId() }), purpose: "review", game_id: game.game_id,
            }))}>{reviewPending ? t("Building review", "分析中") : review?.format_version === "grounded-v1" ? t("Retry coaching", "重试讲解") : t("Review game", "分析棋局")}</button>}
          </div>
          {review?.format_version === "grounded-v1" ? <>
            {review.coaching_status === "pending" && <p className="muted" role="status">{t("Choosing lessons. You can already explore the analysis.", "正在生成讲解，可以先查看落点对比。")}</p>}
            {review.coaching_status === "failed" && <p className="inline-error">{review.coaching_error}</p>}
            <ReviewCoach key={game.game_id} review={review} selectedRevision={historyRevision} practice={practice} variation={variation} busy={!!busy} select={selectPosition} startPractice={startPractice} continueGame={continuePractice} showVariation={showVariation} />
            <details className="review-more"><summary>{t("More analysis and questions", "完整分析与追问")}</summary><ReviewDetails review={review} selectRevision={selectPosition} />
            <form className="question-form" onSubmit={(event) => {
              event.preventDefault();
              const text = question.trim();
              if (text) void perform("Sending question", async () => {
                const contextualQuestion = historyRevision === null ? text : `For position revision ${historyRevision}: ${text}`;
                trackTask({ task: await api<Task>(`/games/${game.game_id}/review/questions`, { question: contextualQuestion, request_id: requestId() }), purpose: "question", game_id: game.game_id, question: contextualQuestion });
                setQuestion("");
              });
            }}>
              <div><textarea id="review-question" aria-label={t("Review question", "复盘问题")} value={question} maxLength={1900} onChange={(event) => setQuestion(event.target.value)} placeholder={historyRevision === null ? t("Ask about this game…", "询问这盘棋…") : historyRevision === 0 ? t("Ask about the starting position…", "询问初始局面…") : t(`Ask about position ${historyRevision}…`, `询问局面 ${historyRevision}…`)} required /><button className="primary" disabled={!!busy || !question.trim()}>{t("Ask", "提问")}</button></div>
            </form></details>
          </> : review ? <p className="muted">{t("Generate a new review to explore verified comparisons and coaching.", "重新分析棋局以查看落点对比。")}</p> : null}
        </section>
      )}
      {game?.status === "finished" && historyRevision !== null && !variation && !practice && (
        <details className="branch-options"><summary>{t("Replay options", "回放选项")}</summary><div className="branch-panel">
          {awaitingPass && <p>{t("Select a position after the pass.", "请选择跳过回合之后的局面。")}</p>}
          {displayedTurn === null && <p>{t("Select a position before the game ends.", "请选择终局之前的局面。")}</p>}
          <div className="branch-actions">
            <button disabled={!!busy || branchUnavailable} onClick={() => void perform("Creating branch", async () => acceptGame(await api<GameState>(`/games/${game.game_id}/branches`, {
              revision: branchRevision, mode: "manual", request_id: requestId(),
            })))}>{t("Continue from here", "从此处续下")}</button>
            <button className="primary" disabled={!!busy || branchPending || branchUnavailable} onClick={() => void perform("Starting hint replay", async () => trackTask({
              task: await api<Task>(`/games/${game.game_id}/branches`, { revision: branchRevision, mode: "follow_hints", request_id: requestId() }), purpose: "branch", game_id: game.game_id,
            }))}>{branchPending ? t("Replaying", "回放中") : t("Replay with hints", "按提示回放")}</button>
          </div>
        </div></details>
      )}
      <TaskList review={review} entries={currentTasks} busy={!!busy} refresh={() => void perform("Refresh tasks", async () => {
        for (const entry of currentTasks) trackTask({ ...entry, task: await api<Task>(`/tasks/${entry.task.task_id}`) });
      })} openGame={(id) => void perform("Loading branch", async () => acceptGame(await api<GameState>(`/games/${id}`)))} repeatQuestion={(text) => {
        setQuestion(text);
        document.getElementById("review-question")?.focus();
      }} />
    </main>
  );
}
