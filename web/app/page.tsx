"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, requestId } from "@/lib/api";
import { LanguageSwitch, useLocale } from "@/lib/locale";
import { captureLineText, cornerName, defenseFeedback, stepText } from "@/lib/teaching-text";
import { readRecentGames, recentGameLabel, rememberGame } from "@/lib/recent-games";
import type { RecentGame } from "@/lib/recent-games";
import { canTeachPosition, moveFlips, placedBoard, savedPosition } from "@/lib/game-view";
import { ReviewCoach } from "@/components/review-coach";
import { GameRules } from "@/components/game-rules";
import type { Variation } from "@/components/review-coach";
import type { Color, Difficulty, GameState, Hint, HistoryEvent, LessonView, PositionLesson, QuestionResult, Task, TrackedTask } from "@/lib/types";

type Mode = "play" | "review";
type Speed = "normal" | "slow";
type Playback = {board: string[]; event: HistoryEvent; flipped: string[]; phase: "placed" | "flipped"};
const lessonKey = (gameId: string, revision: number) => `${gameId}:${revision}`;

function message(error: unknown) {
  return error instanceof Error ? error.message : "Request failed. Please try again.";
}

export default function Home() {
  const {locale, t} = useLocale();
  const colorName = (color: Color) => color === "X" ? t("Black", "黑方") : t("White", "白方");
  const [game, setGame] = useState<GameState | null>(null);
  const [mode, setMode] = useState<Mode>("play");
  const [speed, setSpeed] = useState<Speed>("normal");
  const [playback, setPlayback] = useState<Playback | null>(null);
  const [humanColor, setHumanColor] = useState<Color>("X");
  const [difficulty, setDifficulty] = useState<Difficulty>("medium");
  const [recent, setRecent] = useState<RecentGame[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [bootRetry, setBootRetry] = useState(0);
  const [tips, setTips] = useState(false);
  const [showLegalMoves, setShowLegalMoves] = useState(true);
  const [hint, setHint] = useState<Hint | null>(null);
  const [hintConfirmed, setHintConfirmed] = useState(false);
  const [hintError, setHintError] = useState<string | null>(null);
  const [hintRetry, setHintRetry] = useState(0);
  const [historyRevision, setHistoryRevision] = useState(0);
  const [variation, setVariation] = useState<Variation | null>(null);
  const [lessons, setLessons] = useState<Record<string, PositionLesson | null>>({});
  const [tasks, setTasks] = useState<TrackedTask[]>([]);
  const [taskPollRetry, setTaskPollRetry] = useState(0);
  const gameRef = useRef<GameState | null>(null);
  const busyRef = useRef(false);
  const modeRef = useRef<Mode>("play");
  const speedRef = useRef<Speed>("normal");
  const tipsRef = useRef(false);
  const attemptedAi = useRef<string | null>(null);
  const bootStarted = useRef(false);

  const acceptGame = useCallback((next: GameState) => {
    const previous = gameRef.current;
    const isNew = previous?.game_id !== next.game_id;
    if (isNew) {
      setHumanColor(next.human_color);
      if (next.difficulty) setDifficulty(next.difficulty);
      setMode("play"); modeRef.current = "play";
      setHistoryRevision(next.revision); setVariation(null); setPlayback(null);
      setTips(false); tipsRef.current = false;
    } else if (speedRef.current === "slow" && modeRef.current === "play" && !next.auto_play && !previous.auto_play) {
      const event = next.history.find((item) => item.revision > previous.revision && item.kind === "move" && item.actor !== next.human_color);
      if (event) setPlayback({board: placedBoard(previous.board, event), event, flipped: moveFlips(previous.board, event), phase: "placed"});
    }
    if (attemptedAi.current !== `${next.game_id}:${next.revision}`) attemptedAi.current = null;
    gameRef.current = next; setGame(next); setHint(null); setHintConfirmed(false);
    setRecent((current) => rememberGame(current, next));
    localStorage.setItem("nemothello_active_game", next.game_id);
    window.history.replaceState(null, "", `?game=${encodeURIComponent(next.game_id)}`);
  }, []);

  const perform = useCallback(async (action: () => Promise<void>) => {
    if (busyRef.current) return;
    busyRef.current = true; setBusy(true); setError(null);
    try { await action(); }
    catch (failure) {
      setError(message(failure));
      if (failure instanceof ApiError && failure.status === 409 && gameRef.current) {
        try { acceptGame(await api<GameState>(`/games/${gameRef.current.game_id}`)); }
        catch (refreshFailure) { setError(message(refreshFailure)); }
      }
    } finally { busyRef.current = false; setBusy(false); }
  }, [acceptGame]);

  const createGame = useCallback(async (color: Color, level: Difficulty) => {
    acceptGame(await api<GameState>("/games", {human_color: color, difficulty: level, request_id: requestId()}));
  }, [acceptGame]);

  useEffect(() => {
    if (bootStarted.current) return;
    bootStarted.current = true;
    void perform(async () => {
      await api("/session");
      const saved = localStorage.getItem("nemothello_recent_games");
      if (saved) {
        const restored = await Promise.all(readRecentGames(saved).map(async (item) => {
          if (item.status === "finished") return item;
          try {
            const stored = await api<GameState>(`/games/${encodeURIComponent(item.game_id)}`);
            return stored.status === "finished" ? {...item, status: "finished" as const,
              created_at: stored.created_at ?? item.created_at, human_color: stored.human_color,
              branch: !!stored.parent_game_id} : null;
          } catch (failure) {
            if (failure instanceof ApiError && failure.status === 404) return null;
            throw failure;
          }
        }));
        setRecent(restored.filter((item) => item !== null));
      }
      const savedSpeed = localStorage.getItem("nemothello_speed");
      if (savedSpeed === "slow" || savedSpeed === "normal") {setSpeed(savedSpeed); speedRef.current = savedSpeed;}
      const savedLegalMoves = localStorage.getItem("nemothello_legal_moves");
      if (savedLegalMoves === "true" || savedLegalMoves === "false") setShowLegalMoves(savedLegalMoves === "true");
      const id = new URLSearchParams(window.location.search).get("game");
      if (id) {
        try { acceptGame(await api<GameState>(`/games/${encodeURIComponent(id)}`)); }
        catch (failure) {
          if (failure instanceof ApiError && failure.status === 404) {
            localStorage.removeItem("nemothello_active_game");
            setRecent((current) => current.filter((item) => item.game_id !== id));
            window.history.replaceState(null, "", window.location.pathname);
          }
          throw failure;
        }
      } else await createGame("X", "medium");
      setLoaded(true);
    });
  }, [acceptGame, createGame, perform, bootRetry]);

  useEffect(() => {if (loaded) localStorage.setItem("nemothello_recent_games", JSON.stringify(recent));}, [recent, loaded]);

  useEffect(() => {
    if (!playback) return;
    const timer = setTimeout(() => setPlayback(playback.phase === "placed" ? {...playback, board: playback.event.board, phase: "flipped"} : null), playback.phase === "placed" ? 500 : 900);
    return () => clearTimeout(timer);
  }, [playback]);

  const requestAi = useCallback((current: GameState) => perform(async () => {
    acceptGame(await api<GameState>(`/games/${current.game_id}/ai-move`, {expected_revision: current.revision, request_id: requestId()}));
  }), [acceptGame, perform]);

  useEffect(() => {
    if (!game || mode !== "play" || busy || playback || game.auto_play || game.status !== "active" || game.turn === game.human_color) return;
    const key = `${game.game_id}:${game.revision}`;
    if (attemptedAi.current === key) return;
    const timer = setTimeout(() => {attemptedAi.current = key; void requestAi(game);}, speed === "slow" ? 400 : 0);
    return () => clearTimeout(timer);
  }, [game, mode, busy, playback, speed, requestAi]);

  useEffect(() => {
    if (!game?.auto_play) return;
    const controller = new AbortController();
    let pending = false;
    const timer = setInterval(() => {
      if (pending || document.visibilityState === "hidden") return;
      pending = true;
      void api<GameState>(`/games/${game.game_id}`, undefined, controller.signal).then((next) => {
        if (!controller.signal.aborted && gameRef.current?.game_id === next.game_id) acceptGame(next);
      }).catch((failure) => {if (!controller.signal.aborted) setError(message(failure));}).finally(() => {pending = false;});
    }, 1600);
    return () => {clearInterval(timer); controller.abort();};
  }, [game?.game_id, game?.auto_play, acceptGame]);

  useEffect(() => {
    setHint(null); setHintConfirmed(false); setHintError(null);
    if (mode !== "play" || !tips || busy || playback || !game || game.auto_play || game.status !== "active" || game.turn !== game.human_color) return;
    const controller = new AbortController();
    void api<Hint>(`/games/${game.game_id}/hint`, {expected_revision: game.revision}, controller.signal).then((next) => {
      if (!controller.signal.aborted && tipsRef.current && modeRef.current === "play" && gameRef.current?.game_id === next.game_id && gameRef.current?.revision === next.revision) setHint(next);
    }).catch((failure) => {if (!controller.signal.aborted) setHintError(message(failure));});
    return () => controller.abort();
  }, [mode, tips, busy, playback, game?.game_id, game?.revision, game?.status, game?.turn, game?.human_color, game?.auto_play, hintRetry]);

  useEffect(() => {
    if (!hint || !tips || mode !== "play") return;
    let cancelled = false, painted = 0;
    const frame = requestAnimationFrame(() => {painted = requestAnimationFrame(() => {
      if (cancelled || modeRef.current !== "play" || !tipsRef.current || gameRef.current?.game_id !== hint.game_id || gameRef.current?.revision !== hint.revision) return;
      void api(`/games/${hint.game_id}/hint-displays`, {hint_id: hint.hint_id, expected_revision: hint.revision, request_id: requestId()}).then(() => {if (!cancelled) setHintConfirmed(true);}).catch((failure) => {if (!cancelled) setHintError(message(failure));});
    });});
    return () => {cancelled = true; cancelAnimationFrame(frame); cancelAnimationFrame(painted);};
  }, [hint, tips, mode]);

  const loadLesson = useCallback(async (id: string, revision: number) => {
    const saved = await api<PositionLesson | {task: Task | null}>(`/games/${id}/lessons?revision=${revision}`);
    setLessons((current) => ({...current, [lessonKey(id, revision)]: "task" in saved ? null : saved}));
    return saved;
  }, []);

  const trackTask = useCallback((entry: TrackedTask) => {
    setTasks((current) => [entry, ...current.filter((item) => item.task.task_id !== entry.task.task_id)].slice(0, 50));
    if (entry.task.kind === "lesson" && entry.revision !== undefined) {
      void loadLesson(entry.game_id, entry.revision).catch((failure) => setError(message(failure)));
    }
  }, [loadLesson]);

  useEffect(() => {
    if (!loaded) return;
    const raw = localStorage.getItem("nemothello_tasks");
    if (!raw) return;
    const controller = new AbortController();
    try {
      const saved: unknown = JSON.parse(raw);
      if (!Array.isArray(saved) || !saved.every((item) => item && typeof item.task_id === "string" && typeof item.game_id === "string")) throw new Error("Saved tasks are invalid");
      void Promise.allSettled(saved.map((entry) => api<Task>(`/tasks/${encodeURIComponent(entry.task_id)}`, undefined, controller.signal))).then((results) => {
        if (controller.signal.aborted) return;
        results.forEach((result, index) => {if (result.status === "fulfilled") trackTask({...saved[index], task: result.value});});
      });
    } catch (failure) {setError(message(failure));}
    return () => controller.abort();
  }, [loaded, trackTask]);

  useEffect(() => {
    if (tasks.length) localStorage.setItem("nemothello_tasks", JSON.stringify(tasks.map((entry) => ({task_id: entry.task.task_id, game_id: entry.game_id, purpose: entry.purpose, revision: entry.revision, question: entry.question}))));
  }, [tasks]);

  useEffect(() => {
    const pending = tasks.filter((entry) => ["queued", "running"].includes(entry.task.status));
    if (!pending.length) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      void Promise.allSettled(pending.map((entry) => api<Task>(`/tasks/${entry.task.task_id}`, undefined, controller.signal))).then((results) => {
        if (controller.signal.aborted) return;
        results.forEach((result, index) => {if (result.status === "fulfilled") trackTask({...pending[index], task: result.value}); else setError(message(result.reason));});
        setTaskPollRetry((current) => results.some((result) => result.status === "rejected") ? current + 1 : 0);
      });
    }, 1200 * 2 ** Math.min(taskPollRetry, 3));
    return () => {clearTimeout(timer); controller.abort();};
  }, [tasks, trackTask, taskPollRetry]);

  useEffect(() => {
    if (mode !== "review" || !game || !canTeachPosition(game, historyRevision)) return;
    let cancelled = false;
    void loadLesson(game.game_id, historyRevision).then((saved) => {
      if (!cancelled && "task" in saved && saved.task) trackTask({task: saved.task, game_id: game.game_id, purpose: "lesson", revision: historyRevision});
      else if (!cancelled && !("task" in saved) && saved.coaching_status === "pending" && saved.task_id) {
        void api<Task>(`/tasks/${saved.task_id}`).then((task) => {
          if (!cancelled) trackTask({task, game_id: game.game_id, purpose: "lesson", revision: historyRevision});
        }).catch((failure) => {if (!cancelled) setError(message(failure));});
      }
    }).catch((failure) => {if (!cancelled) setError(message(failure));});
    return () => {cancelled = true;};
  }, [mode, game?.game_id, historyRevision, loadLesson, trackTask]);

  const position = game && mode === "review" ? savedPosition(game, historyRevision) : game;
  const teachingFrame = variation?.lesson_frames[variation.frame];
  const board = teachingFrame?.board ?? (mode === "play" ? playback?.board : null) ?? position?.board;
  const turn = teachingFrame ? teachingFrame.turn : position?.turn;
  const nextEvent = game?.history.find((item) => item.revision === historyRevision + 1);
  const canTeach = mode === "review" && !!game && canTeachPosition(game, historyRevision);
  const canDefend = mode === "review" && !!variation?.exercise && variation.frame === 2 && !variation.exercise.attempt && !busy;
  const capturePreview = !!variation && !canDefend && variation.frame === variation.lesson_frames.length - 2 && !!variation.capture_lines?.length;
  const visibleHint = mode === "play" && hint?.game_id === game?.game_id && hint?.revision === game?.revision ? hint : null;
  const canMove = mode === "play" && !!game && !busy && !playback && !game.auto_play && game.status === "active" && game.turn === game.human_color && (!tips || (!!visibleHint && hintConfirmed));
  const lastMove = mode === "play" ? game?.history.findLast((item) => item.kind === "move") : null;
  const currentLesson = canTeach && game ? lessons[lessonKey(game.game_id, historyRevision)] : null;
  const reviewMoveNumber = (game?.history.filter((event) => event.kind === "move" && event.revision <= historyRevision).length ?? 0) + 1;
  const currentTasks = tasks.filter((entry) => entry.game_id === game?.game_id && entry.revision === historyRevision);
  const pendingLesson = currentTasks.some((entry) => entry.purpose === "lesson" && ["queued", "running"].includes(entry.task.status));
  const latestLessonTask = currentTasks.find((entry) => entry.purpose === "lesson");
  const latestQuestion = currentTasks.find((entry) => entry.purpose === "question");
  const questionAnswer = latestQuestion?.task.kind === "question" ? latestQuestion.task.result as QuestionResult | null : null;
  const branchTask = tasks.find((entry) => entry.purpose === "branch" && entry.game_id === game?.game_id);
  const canChangeOpening = !!game && !game.parent_game_id && !game.auto_play && game.status === "active" && !game.history.some((item) => item.kind === "move" && item.actor === game.human_color);

  function selectPosition(revision: number) {setHistoryRevision(revision); setVariation(null); setError(null);}
  function switchMode(value: Mode) {
    modeRef.current = value; setMode(value); setVariation(null); setPlayback(null); setError(null);
    if (value === "review" && game) setHistoryRevision(game.revision);
  }
  function changeSettings(color: Color, level: Difficulty) {
    if (canChangeOpening) {if (color !== game?.human_color || level !== game?.difficulty) void perform(() => createGame(color, level));}
    else {setHumanColor(color); setDifficulty(level);}
  }
  function teach(question?: string, view?: LessonView) {
    if (!game || !canTeach) return;
    const id = game.game_id, revision = historyRevision;
    void perform(async () => trackTask({task: await api<Task>(`/games/${id}/lessons`, {revision, question, view, request_id: requestId()}), game_id: id, revision, purpose: question ? "question" : "lesson", question}));
  }
  function continueGame(revision: number, replay: boolean) {
    if (!game) return;
    const id = game.game_id;
    void perform(async () => {
      const result = await api<GameState | Task>(`/games/${id}/branches`, {revision, mode: replay ? "follow_hints" : "manual", request_id: requestId()});
      if ("task_id" in result) trackTask({task: result, game_id: id, revision, purpose: "branch"});
      else acceptGame(result);
    });
  }

  return <main className="workspace">
    <header className="masthead"><a className="wordmark" href="/">Nemo<span>thello</span><span className="brand-dot" /></a><div className="mode-switch" role="group" aria-label={t("Mode", "模式")}><button aria-pressed={mode === "play"} disabled={!loaded} onClick={() => switchMode("play")}>{t("Play", "对战")}</button><button aria-pressed={mode === "review"} disabled={!loaded} onClick={() => switchMode("review")}>{t("Review", "复盘")}</button></div><div className="header-tools"><GameRules /><LanguageSwitch /></div></header>
    <section className="game-toolbar" aria-label={t("Game settings", "对局设置")}>
      {mode === "play" && <><div className="color-picker"><button aria-pressed={humanColor === "X"} disabled={busy || !loaded || !!playback} onClick={() => changeSettings("X", difficulty)}><i className="mini-disc black" />{t("Black", "黑方")}</button><button aria-pressed={humanColor === "O"} disabled={busy || !loaded || !!playback} onClick={() => changeSettings("O", difficulty)}><i className="mini-disc white" />{t("White", "白方")}</button></div><select aria-label={t("Difficulty", "难度")} value={difficulty} disabled={busy || !loaded || !!playback} onChange={(event) => changeSettings(humanColor, event.target.value as Difficulty)}><option value="easy">{t("Beginner", "初级")}</option><option value="medium">{t("Intermediate", "中级")}</option><option value="hard">{t("Advanced", "高级")}</option></select><button className="primary" disabled={busy || !loaded || !!playback} onClick={() => void perform(() => createGame(humanColor, difficulty))}>{t("New game", "新对局")}</button></>}
      {recent.length > 0 && <label className="recent-picker">{t("Finished games", "已完局")}<select aria-label={t("Finished games", "已完局")} value={recent.some((item) => item.game_id === game?.game_id) ? game?.game_id : ""} disabled={busy} onChange={(event) => void perform(async () => acceptGame(await api<GameState>(`/games/${event.target.value}`)))}><option value="" disabled>{t("Select a game", "选择对局")}</option>{recent.map((item) => <option key={item.game_id} value={item.game_id}>{recentGameLabel(item, locale)}</option>)}</select></label>}
    </section>
    {error && <div className="error-banner" role="alert"><span>{error}</span><button aria-label={t("Dismiss error", "关闭错误信息")} onClick={() => setError(null)}>×</button></div>}
    {!loaded && !busy && <button onClick={() => {bootStarted.current = false; setBootRetry((n) => n + 1);}}>{t("Reconnect", "重新连接")}</button>}
    <div className={`play-layout ${mode === "review" ? "review-layout" : ""}`}>
      <section className="board-panel" id="game-board" aria-label={t("Othello board", "翻转棋棋盘")}>
        <div className="board-topline"><span className="turn-label">{variation ? t("Analysis line", "分析演示") : mode === "review" ? t("Game history", "对局记录") : game?.difficulty ? ({easy: t("Beginner", "初级"), medium: t("Intermediate", "中级"), hard: t("Advanced", "高级")})[game.difficulty] : ""}</span><span className="turn-label" aria-live="polite">{variation ? null : playback ? t(`${colorName(playback.event.actor)} plays ${playback.event.coordinate}`, `${colorName(playback.event.actor)}下 ${playback.event.coordinate}`) : !loaded ? t("Preparing game…", "正在准备对局…") : turn ? mode === "play" ? turn === game?.human_color ? t("Your turn", "轮到你") : t("AI's turn", "轮到 AI") : t(`${colorName(turn)} to move`, `轮到${colorName(turn)}`) : t("Game over", "对局结束")}</span></div>
        <div className="board-with-labels"><div className="column-labels" aria-hidden="true">{"abcdefgh".split("").map((column) => <span key={column}>{column}</span>)}</div><div className="board-rows"><div className="row-labels" aria-hidden="true">{Array.from({length: 8}, (_, row) => <span key={row}>{row + 1}</span>)}</div><div className="board" role="group" aria-label={t("Board, a1 is at the top left", "棋盘，左上角为 a1")}>{Array.from({length: 64}, (_, index) => {
          const row = Math.floor(index / 8), column = index % 8, coordinate = `${"abcdefgh"[column]}${row + 1}`, cell = board?.[row]?.[column] ?? ".";
          const legal = canDefend ? !!variation?.exercise?.defenses.some((item) => item.coordinate === coordinate) : canMove && !!game?.legal_moves.includes(coordinate);
          const recommended = mode === "play" && visibleHint?.recommended_move === coordinate;
          const placed = teachingFrame?.coordinate === coordinate || (!teachingFrame && lastMove?.coordinate === coordinate);
          const flipped = teachingFrame?.flipped.includes(coordinate) || (mode === "play" && playback?.phase === "flipped" && playback.flipped.includes(coordinate));
          const target = !!teachingFrame && variation?.focus_square === coordinate;
          const ray = capturePreview && variation?.capture_lines?.some((line) => line.includes(coordinate));
          return <button key={coordinate} className={`square ${recommended ? "recommended" : ""} ${placed ? "lesson-placed" : ""} ${flipped ? "lesson-flipped" : ""} ${target ? "lesson-target" : ""} ${ray ? "lesson-ray" : ""} ${flipped && playback ? "slow-flip" : ""}`} disabled={!legal} aria-label={`${coordinate}, ${cell === "X" ? t("black disc", "黑棋") : cell === "O" ? t("white disc", "白棋") : t("empty", "空位")}${legal ? t(", legal move", "，合法落点") : ""}${recommended ? t(", recommended move", "，推荐落点") : ""}${placed ? t(", last move", "，最近落子") : ""}${flipped ? t(", flipped this step", "，本步翻转") : ""}`} onClick={() => {
            if (canDefend && variation?.exercise) {const defense = variation.exercise.defenses.find((item) => item.coordinate === coordinate); if (defense) setVariation({...variation, frame: 3, lesson_frames: defense.frames, capture_lines: defense.capture_lines, exercise: {...variation.exercise, attempt: coordinate}});}
            else if (game && canMove) void perform(async () => acceptGame(await api<GameState>(`/games/${game.game_id}/moves`, {coordinate, expected_revision: game.revision, request_id: requestId()})));
          }}>{cell !== "." && <span className={`disc ${cell === "X" ? "black" : "white"}`} />}{cell === "." && legal && (canDefend || showLegalMoves) && <span className="legal-marker" />}{recommended && <span className="hint-ring" />}{(placed || target || ray || recommended) && <span className="lesson-coordinate">{coordinate}</span>}</button>;
        })}</div></div></div>
        {mode === "review" && game && <div className="review-navigation">
          <div className="timeline-buttons"><button aria-label={t("First position", "初始局面")} disabled={historyRevision === 0} onClick={() => selectPosition(0)}>⇤</button><button aria-label={t("Previous move", "上一手")} disabled={historyRevision === 0} onClick={() => selectPosition(historyRevision - 1)}>←</button><input type="range" aria-label={t("Game progress", "棋局进度")} min={0} max={game.revision} step={1} value={historyRevision} onChange={(event) => selectPosition(Number(event.target.value))} /><button aria-label={t("Next move", "下一手")} disabled={historyRevision === game.revision} onClick={() => selectPosition(historyRevision + 1)}>→</button><button aria-label={t("Final position", "最终局面")} disabled={historyRevision === game.revision} onClick={() => selectPosition(game.revision)}>⇥</button></div>
          <div className="timeline-caption"><span>{(variation || currentLesson) ? t(`Before move ${reviewMoveNumber}`, `第 ${reviewMoveNumber} 手之前`) : nextEvent?.kind === "pass" ? t(`${colorName(nextEvent.actor)} must pass`, `${colorName(nextEvent.actor)}必须跳过回合`) : nextEvent ? t(`Next: ${colorName(nextEvent.actor)} ${nextEvent.coordinate}`, `下一手：${colorName(nextEvent.actor)} ${nextEvent.coordinate}`) : turn ? t("Current position", "当前局面") : t("Final position", "终局")}</span>{canTeach && <button className="primary" disabled={busy || pendingLesson || currentLesson?.coaching_status === "ready"} onClick={() => teach()}>{pendingLesson ? t("Analyzing…", "分析中…") : currentLesson?.coaching_status === "failed" || latestLessonTask?.task.status === "failed" ? t("Retry teaching", "重试教学") : currentLesson ? t("Teaching", "教学") : t("Teach this position", "教学")}</button>}</div>
        </div>}
        {variation && <div className="board-footer"><button disabled={canDefend || variation.frame === 0} onClick={() => setVariation({...variation, frame: variation.frame - 1})}>{t("Previous step", "上一步")}</button><span>{variation.frame}/{variation.lesson_frames.length - 1}</span><button disabled={canDefend || variation.frame === variation.lesson_frames.length - 1} onClick={() => setVariation({...variation, frame: variation.frame + 1})}>{variation.exercise?.attempt && variation.frame === 3 ? t("See the reply", "看对手应对") : t("Next step", "下一步")}</button><button onClick={() => setVariation(null)}>{t("Back to before the move", "返回落子前局面")}</button>
          {teachingFrame && <p className="board-teaching-text" role="status">{canDefend && variation.exercise ? t(`Choose a defense against the ${cornerName(variation.exercise.target, locale)} capture.`, `选择一步，试着守住${cornerName(variation.exercise.target, locale)}。`) : stepText(teachingFrame, locale)}{!canDefend && variation.frame === variation.lesson_frames.length - 2 && variation.capture_lines?.length ? <span className="capture-explanation">{captureLineText(variation.capture_lines, variation.lesson_frames.at(-1)!.actor!, locale)}</span> : null}</p>}
          {variation.exercise?.attempt && variation.frame >= 3 && <><p className="defense-feedback">{defenseFeedback(variation.coordinate, variation.exercise.attempt, variation.exercise.target, locale)}</p><button onClick={() => setVariation({...variation, frame: 2, exercise: {...variation.exercise!, attempt: null}})}>{t("Try another defense", "换一步试试")}</button></>}
        </div>}
      </section>
      <aside className="side-panel">
        <section className="score-card" aria-label={t("Disc count", "棋子数量")}><div className="score-line">{(["X", "O"] as Color[]).map((color) => <div key={color}><i className={`mini-disc ${color === "X" ? "black" : "white"}`} /><span>{colorName(color)}</span><strong>{board ? [...board.join("")].filter((cell) => cell === color).length : "—"}</strong></div>)}</div>{mode === "play" && game?.result && <p className="result-label">{game.result.winner === "draw" ? t("Draw", "和棋") : game.result.winner === game.human_color ? t("You win", "你获胜") : t("AI wins", "AI 获胜")}</p>}</section>
        {mode === "play" ? <section className="tips-card"><label className="speed-picker">{t("Move speed", "落子速度")}<select aria-label={t("Move speed", "落子速度")} value={speed} onChange={(event) => {const value = event.target.value as Speed; speedRef.current = value; setSpeed(value); localStorage.setItem("nemothello_speed", value);}}><option value="normal">{t("Normal", "普通")}</option><option value="slow">{t("Slow", "慢速")}</option></select></label>{game?.status === "active" && <><div className="card-heading"><span>{t("Legal moves", "可落子点")}</span><button className={`toggle ${showLegalMoves ? "on" : ""}`} role="switch" aria-checked={showLegalMoves} aria-label={t("Legal moves", "可落子点")} onClick={() => {const next = !showLegalMoves; setShowLegalMoves(next); localStorage.setItem("nemothello_legal_moves", String(next));}}><span /></button></div><div className="card-heading"><span>{t("Recommended move", "推荐点")}</span><button className={`toggle ${tips ? "on" : ""}`} role="switch" aria-checked={tips} aria-label={t("Move hints", "落点提示")} disabled={game.auto_play} onClick={() => {tipsRef.current = !tips; setTips(!tips);}}><span /></button></div></>}{hintError && <p role="alert">{hintError}<button onClick={() => setHintRetry((n) => n + 1)}>{t("Retry hint", "重试提示")}</button></p>}</section> : <section className="teaching-panel" aria-label={t("Teaching", "教学")}>
          {currentLesson && game ? <><ReviewCoach key={lessonKey(game.game_id, historyRevision)} game={game} lesson={currentLesson} variation={variation} pending={pendingLesson} busy={busy} showVariation={setVariation} ask={(text, view) => teach(text, view)} answer={questionAnswer} questionPending={!!latestQuestion && ["queued", "running"].includes(latestQuestion.task.status)} continueGame={(revision) => continueGame(revision, false)} replay={(revision) => continueGame(revision, true)} revisit={selectPosition} />{currentLesson.coaching_status === "failed" && <p className="inline-error" role="alert">{currentLesson.coaching_error}</p>}</> : <p className="teaching-empty" role="status">{!turn ? t("Step back to one of your moves, then choose Teach this position.", "回退到自己的落子，再点击教学。") : nextEvent?.kind === "pass" ? t("No legal move. This turn is passed to the opponent.", "本回合无合法落点，跳过后由对方继续。") : !canTeach ? t("Choose one of your own turns for teaching.", "选择自己的回合查看教学。") : pendingLesson ? t("Analyzing this position…", "正在分析这个局面…") : t("Use the arrows or timeline to choose one of your moves, then choose Teach this position.", "用箭头或进度条选择自己的落子，再点击教学。")}</p>}
          {canTeach && currentLesson?.coaching_status !== "failed" && latestLessonTask?.task.error && <p role="alert" className="inline-error">{latestLessonTask.task.error.message}</p>}
          {canTeach && latestQuestion?.task.error && <p role="alert" className="inline-error">{latestQuestion.task.error.message}</p>}
          {branchTask && <div className="branch-status" role="status">{["queued", "running"].includes(branchTask.task.status) ? t("Replaying with hints…", "正在按提示回放…") : branchTask.task.error?.message}<button disabled={busy} onClick={() => void perform(async () => acceptGame(await api<GameState>(`/games/${branchTask.task.game_id}`)))}>{t("Open replay", "查看回放")}</button></div>}
        </section>}
      </aside>
    </div>
  </main>;
}
