"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, requestId } from "@/lib/api";
import { LanguageSwitch, useLocale } from "@/lib/locale";
import { readRecentGames, recentGameLabel, rememberGame, restoreRecentGames } from "@/lib/recent-games";
import type { SavedGame } from "@/lib/types";
import type { RecentGame } from "@/lib/recent-games";
import { canTeachPosition, moveFlips, placedBoard, reviewPosition, savedPosition } from "@/lib/game-view";
import { ReviewCoach } from "@/components/review-coach";
import { ReviewNavigation } from "@/components/review-navigation";
import { LessonStart } from "@/components/lesson-start";
import { GameSummaryCard } from "@/components/game-summary";
import { GameRules } from "@/components/game-rules";
import { TermHelp } from "@/components/term-help";
import { coachingFailure } from "@/lib/teaching-text";
import type { Variation } from "@/components/review-coach";
import type { CornerPractice, EarlierDecisionResult, Color, Difficulty, GameState, GameSummary, Hint, HistoryEvent, KeyMove, LessonView, PositionLesson, QuestionResult, ReviewSummary, Task, TrackedTask } from "@/lib/types";

type Mode = "play" | "review";
type Speed = "normal" | "slow";
type Playback = {board: string[]; event: HistoryEvent; flipped: string[]; phase: "placed" | "flipped"};
const lessonKey = (gameId: string, revision: number, language: string) => `${gameId}:${revision}:${language}`;

// The service caps Nemotron tasks per day; hitting the cap is shown as a note, not an error
function dailyLimit(failure: unknown) {
  return failure instanceof ApiError && failure.detail.code === "MODEL_DAILY_LIMIT";
}

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
  // The review position; null is the final board, where the game summary is shown
  const [historyRevision, setHistoryRevision] = useState<number | null>(null);
  const [variation, setVariation] = useState<Variation | null>(null);
  const [lessons, setLessons] = useState<Record<string, PositionLesson | null>>({});
  const [keyMoves, setKeyMoves] = useState<Record<string, KeyMove[]>>({});
  const [summaries, setSummaries] = useState<Record<string, GameSummary | null>>({});
  const [tasks, setTasks] = useState<TrackedTask[]>([]);
  const [taskPollRetry, setTaskPollRetry] = useState(0);
  const gameRef = useRef<GameState | null>(null);
  const busyRef = useRef(false);
  const modeRef = useRef<Mode>("play");
  const speedRef = useRef<Speed>("normal");
  const tipsRef = useRef(false);
  const attemptedAi = useRef<string | null>(null);
  const bootStarted = useRef(false);
  const autoCoached = useRef(new Set<string>());
  const [modelLimited, setModelLimited] = useState(false);

  const acceptGame = useCallback((next: GameState) => {
    const previous = gameRef.current;
    const isNew = previous?.game_id !== next.game_id;
    if (isNew) {
      setHumanColor(next.human_color);
      if (next.difficulty) setDifficulty(next.difficulty);
      const nextMode = modeRef.current === "review" && next.status === "finished" ? "review" : "play";
      setMode(nextMode); modeRef.current = nextMode;
      setHistoryRevision(null); setVariation(null); setPlayback(null);
      setTips(false); tipsRef.current = false;
    } else if (speedRef.current === "slow" && modeRef.current === "play") {
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
      if (dailyLimit(failure)) setModelLimited(true);
      else setError(message(failure));
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
      const stored = await api<SavedGame[]>("/games");
      setRecent(restoreRecentGames(stored, saved ? readRecentGames(saved) : []));
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
    if (!game || mode !== "play" || busy || playback || game.status !== "active" || game.turn === game.human_color) return;
    const key = `${game.game_id}:${game.revision}`;
    if (attemptedAi.current === key) return;
    const timer = setTimeout(() => {attemptedAi.current = key; void requestAi(game);}, speed === "slow" ? 400 : 0);
    return () => clearTimeout(timer);
  }, [game, mode, busy, playback, speed, requestAi]);

  useEffect(() => {
    setHint(null); setHintConfirmed(false); setHintError(null);
    if (mode !== "play" || !tips || busy || playback || !game || game.status !== "active" || game.turn !== game.human_color) return;
    const controller = new AbortController();
    void api<Hint>(`/games/${game.game_id}/hint`, {expected_revision: game.revision}, controller.signal).then((next) => {
      if (!controller.signal.aborted && tipsRef.current && modeRef.current === "play" && gameRef.current?.game_id === next.game_id && gameRef.current?.revision === next.revision) setHint(next);
    }).catch((failure) => {if (!controller.signal.aborted) setHintError(message(failure));});
    return () => controller.abort();
  }, [mode, tips, busy, playback, game?.game_id, game?.revision, game?.status, game?.turn, game?.human_color, hintRetry]);

  useEffect(() => {
    if (!hint || !tips || mode !== "play") return;
    let cancelled = false, painted = 0;
    const frame = requestAnimationFrame(() => {painted = requestAnimationFrame(() => {
      if (cancelled || modeRef.current !== "play" || !tipsRef.current || gameRef.current?.game_id !== hint.game_id || gameRef.current?.revision !== hint.revision) return;
      void api(`/games/${hint.game_id}/hint-displays`, {hint_id: hint.hint_id, expected_revision: hint.revision, request_id: requestId()}).then(() => {if (!cancelled) setHintConfirmed(true);}).catch((failure) => {if (!cancelled) setHintError(message(failure));});
    });});
    return () => {cancelled = true; cancelAnimationFrame(frame); cancelAnimationFrame(painted);};
  }, [hint, tips, mode]);

  const loadLesson = useCallback(async (id: string, revision: number, language: string) => {
    const saved = await api<PositionLesson | {task: Task | null}>(`/games/${id}/lessons?revision=${revision}&language=${language}`);
    setLessons((current) => ({...current, [lessonKey(id, revision, language)]: "task" in saved ? null : saved}));
    return saved;
  }, []);

  const acceptReview = useCallback((review: ReviewSummary) => {
    setKeyMoves((current) => ({...current, [review.game_id]: review.key_moves}));
  }, []);

  const loadSummary = useCallback(async (id: string, language: string) => {
    const saved = await api<GameSummary | {task: Task | null}>(`/games/${id}/summary?language=${language}`);
    setSummaries((current) => ({...current, [`${id}:${language}`]: "task" in saved ? null : saved}));
    return saved;
  }, []);

  const trackTask = useCallback((entry: TrackedTask) => {
    setTasks((current) => [entry, ...current.filter((item) => item.task.task_id !== entry.task.task_id)].slice(0, 50));
    if (entry.task.kind === "lesson" && entry.revision !== undefined) {
      void loadLesson(entry.game_id, entry.revision, entry.task.language).catch((failure) => setError(message(failure)));
    }
    if (entry.task.kind === "review" && entry.task.result) acceptReview(entry.task.result);
    if (entry.task.kind === "summary") void loadSummary(entry.game_id, entry.task.language).catch((failure) => setError(message(failure)));
  }, [loadLesson, acceptReview, loadSummary]);

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

  const reviewReady = !!game && !!keyMoves[game.game_id];
  const reviewPending = tasks.some((entry) => entry.purpose === "review" && entry.game_id === game?.game_id && ["queued", "running"].includes(entry.task.status));
  // A finished game gets an engine-only review that picks the moves worth studying
  useEffect(() => {
    if (mode !== "review" || !game || game.status !== "finished" || keyMoves[game.game_id]) return;
    const id = game.game_id;
    let cancelled = false;
    void api<ReviewSummary | {task: Task | null}>(`/games/${id}/review`).then(async (saved) => {
      if (cancelled) return;
      if (!("task" in saved)) {acceptReview(saved); return;}
      const running = saved.task && ["queued", "running"].includes(saved.task.status) ? saved.task : null;
      const task = running ?? await api<Task>(`/games/${id}/reviews`, {request_id: requestId()});
      if (!cancelled) trackTask({task, game_id: id, purpose: "review"});
    }).catch((failure) => {if (!cancelled) setError(message(failure));});
    return () => {cancelled = true;};
  }, [mode, game?.game_id, game?.status, keyMoves, acceptReview, trackTask]);

  // Summarize every completed review, including games with no key mistakes
  const gameKeyMoves = game ? keyMoves[game.game_id] : undefined;
  useEffect(() => {
    if (mode !== "review" || !game || !gameKeyMoves || !game.history.some((event) => event.kind === "move" && event.actor === game.human_color)) return;
    const id = game.game_id;
    let cancelled = false;
    void loadSummary(id, locale).then(async (saved) => {
      if (cancelled || !("task" in saved)) return;
      const running = saved.task && ["queued", "running"].includes(saved.task.status) ? saved.task : null;
      if (!running && modelLimited) return;
      const task = running ?? await api<Task>(`/games/${id}/summaries`, {language: locale, request_id: requestId()});
      if (!cancelled) trackTask({task, game_id: id, purpose: "summary"});
    }).catch((failure) => {if (!cancelled) {if (dailyLimit(failure)) setModelLimited(true); else setError(message(failure));}});
    return () => {cancelled = true;};
  }, [mode, game?.game_id, gameKeyMoves, locale, loadSummary, trackTask, modelLimited]);

  useEffect(() => {
    if (mode !== "review" || historyRevision === null || !game || !canTeachPosition(game, historyRevision)) return;
    let cancelled = false;
    void loadLesson(game.game_id, historyRevision, locale).then((saved) => {
      if (!cancelled && "task" in saved && saved.task) trackTask({task: saved.task, game_id: game.game_id, purpose: "lesson", revision: historyRevision});
      else if (!cancelled && !("task" in saved) && saved.coaching_status === "pending" && saved.task_id) {
        void api<Task>(`/tasks/${saved.task_id}`).then((task) => {
          if (!cancelled) trackTask({task, game_id: game.game_id, purpose: "lesson", revision: historyRevision});
        }).catch((failure) => {if (!cancelled) setError(message(failure));});
      }
    }).catch((failure) => {if (!cancelled) setError(message(failure));});
    return () => {cancelled = true;};
  }, [mode, game?.game_id, historyRevision, loadLesson, trackTask, reviewReady, locale]);

  const summaryView = mode === "review" && historyRevision === null;
  const position = game && mode === "review" && historyRevision !== null ? reviewPosition(game, historyRevision) : game;
  const teachingFrame = variation?.lesson_frames[variation.frame];
  const board = teachingFrame?.board ?? (mode === "play" ? playback?.board : null) ?? position?.board;
  const turn = teachingFrame ? teachingFrame.turn : position?.turn;
  const nextEvent = historyRevision === null ? undefined : game?.history.find((item) => item.revision === historyRevision + 1);
  // The revision whose lesson is open, if any
  const taught = mode === "review" && game && historyRevision !== null && canTeachPosition(game, historyRevision) ? historyRevision : null;
  const canTeach = taught !== null;
  const summary = game ? summaries[`${game.game_id}:${locale}`] : null;
  const summaryPending = tasks.some((entry) => entry.purpose === "summary" && entry.game_id === game?.game_id && entry.task.language === locale && ["queued", "running"].includes(entry.task.status));
  const canPractice = mode === "review" && !!variation?.exercise && !variation.exercise.attempt && !busy;
  const captureFrame = variation?.capture_frame ?? (variation ? variation.lesson_frames.length - 2 : -1);
  const capturePreview = !!variation && !canPractice && variation.frame === captureFrame && !!variation.capture_lines?.length;
  const comparisonRay = !canPractice && variation?.comparison_ray?.frame === variation?.frame ? variation?.comparison_ray?.squares : null;
  const visibleHint = mode === "play" && hint?.game_id === game?.game_id && hint?.revision === game?.revision ? hint : null;
  const canMove = mode === "play" && !!game && !busy && !playback && game.status === "active" && game.turn === game.human_color && (!tips || (!!visibleHint && hintConfirmed));
  const lastMove = mode === "play" ? game?.history.findLast((item) => item.kind === "move") : canTeach ? nextEvent : null;
  // Review shows the board after your move, so ring the discs that move flipped
  const reviewFlips = taught !== null && game && nextEvent ? moveFlips(savedPosition(game, taught).board, nextEvent) : [];
  const currentLesson = taught !== null && game ? lessons[lessonKey(game.game_id, taught, locale)] : null;
  const currentTasks = tasks.filter((entry) => entry.game_id === game?.game_id && entry.revision === historyRevision && entry.task.language === locale);
  const pendingLesson = currentTasks.some((entry) => entry.purpose === "lesson" && ["queued", "running"].includes(entry.task.status));
  const latestLessonTask = currentTasks.find((entry) => entry.purpose === "lesson");
  const latestQuestion = currentTasks.find((entry) => entry.purpose === "question");
  const lessonFailure = currentLesson?.coaching_status === "failed" ? coachingFailure(currentLesson.coaching_error_code, currentLesson.coaching_error, "lesson", locale) : null;
  const questionFailure = latestQuestion?.task.error ? coachingFailure(latestQuestion.task.error.code, latestQuestion.task.error.message, "question", locale) : null;
  const questionAnswer = latestQuestion?.task.kind === "question" ? latestQuestion.task.result as QuestionResult | null : null;
  // Moves worth reviewing are coached as soon as they are opened; other moves wait for the button
  const autoCoach = !!game && !modelLimited && currentLesson?.coaching_status === "not_requested" && !pendingLesson
    && !!keyMoves[game.game_id]?.some((move) => move.revision === historyRevision);
  useEffect(() => {
    if (!autoCoach || busyRef.current || !game || taught === null) return;
    const key = lessonKey(game.game_id, taught, locale);
    if (autoCoached.current.has(key)) return;
    autoCoached.current.add(key);
    teach();
  });
  const canChangeOpening = !!game && !game.parent_game_id && game.status === "active" && !game.history.some((item) => item.kind === "move" && item.actor === game.human_color);

  function selectPosition(revision: number | null) {setHistoryRevision(revision); setVariation(null); setError(null);}
  function switchMode(value: Mode) {
    modeRef.current = value; setMode(value); setVariation(null); setPlayback(null); setError(null);
    if (value === "review") setHistoryRevision(null);
  }
  function changeSettings(color: Color, level: Difficulty) {
    if (canChangeOpening) {if (color !== game?.human_color || level !== game?.difficulty) void perform(() => createGame(color, level));}
    else {setHumanColor(color); setDifficulty(level);}
  }
  function teach(question?: string, view?: LessonView) {
    if (!game || taught === null) return;
    const id = game.game_id, revision = taught;
    void perform(async () => trackTask({task: await api<Task>(`/games/${id}/lessons`, {revision, question, view, language: locale, request_id: requestId()}), game_id: id, revision, purpose: question ? "question" : "lesson", question}));
  }
  function startPractice(move: string) {
    if (!game || !currentLesson) return;
    if (taught === null) return;
    const id = game.game_id, revision = taught, choice = currentLesson.comparison.choices.find((item) => item.coordinate === move)!;
    void perform(async () => {
      const practice = await api<CornerPractice>(`/games/${id}/lessons/corner-practice?revision=${revision}&move=${move}`);
      setVariation({revision, coordinate: move, frame: 0, lesson_frames: [choice.frames[0]], assessment: choice.assessment,
        exercise: {options: practice.options, target: practice.target, attempt: null}});
    });
  }
  function retrySummary() {
    if (!game) return;
    const id = game.game_id;
    void perform(async () => trackTask({task: await api<Task>(`/games/${id}/summaries`, {language: locale, request_id: requestId()}), game_id: id, purpose: "summary"}));
  }
  function findEarlier() {
    if (!game || !currentLesson) return;
    if (taught === null) return;
    const id = game.game_id, revision = taught, key = lessonKey(id, revision, locale);
    void perform(async () => {
      const earlier = await api<EarlierDecisionResult>(`/games/${id}/lessons/earlier?revision=${revision}&language=${locale}`);
      setLessons((current) => current[key] ? {...current, [key]: {...current[key], earlier_decision:earlier}} : current);
    });
  }
  function continueGame(revision: number, line: string[]) {
    if (!game) return;
    const id = game.game_id;
    void perform(async () => acceptGame(await api<GameState>(`/games/${id}/branches`, {revision, line, request_id: requestId()})));
  }

  return <main className="workspace">
    <header className="masthead"><a className="wordmark" href="/">Nemo<span>thello</span><span className="brand-dot" /></a><div className="mode-switch" role="group" aria-label={t("Mode", "模式")}><button aria-pressed={mode === "play"} disabled={!loaded} onClick={() => switchMode("play")}>{t("Play", "对战")}</button><button aria-pressed={mode === "review"} disabled={!loaded || game?.status !== "finished"} title={game?.status === "finished" ? undefined : t("Finish this game to review it", "下完这盘才能复盘")} onClick={() => switchMode("review")}>{t("Review", "复盘")}</button></div><div className="header-tools"><GameRules /><LanguageSwitch /></div></header>
    <section className="game-toolbar" aria-label={t("Game settings", "对局设置")}>
      {mode === "play" && <><div className="color-picker"><button aria-pressed={humanColor === "X"} disabled={busy || !loaded || !!playback} onClick={() => changeSettings("X", difficulty)}><i className="mini-disc black" />{t("Black", "黑方")}</button><button aria-pressed={humanColor === "O"} disabled={busy || !loaded || !!playback} onClick={() => changeSettings("O", difficulty)}><i className="mini-disc white" />{t("White", "白方")}</button></div><select aria-label={t("Difficulty", "难度")} value={difficulty} disabled={busy || !loaded || !!playback} onChange={(event) => changeSettings(humanColor, event.target.value as Difficulty)}><option value="easy">{t("Beginner", "初级")}</option><option value="medium">{t("Intermediate", "中级")}</option><option value="hard">{t("Advanced", "高级")}</option></select><button className="primary" disabled={busy || !loaded || !!playback} onClick={() => void perform(() => createGame(humanColor, difficulty))}>{t("New game", "新对局")}</button></>}
      {recent.length > 0 && <label className="recent-picker">{t("Finished games", "已完局")}<select aria-label={t("Finished games", "已完局")} value={recent.some((item) => item.game_id === game?.game_id) ? game?.game_id : ""} disabled={busy} onChange={(event) => void perform(async () => acceptGame(await api<GameState>(`/games/${event.target.value}`)))}><option value="" disabled>{t("Select a game", "选择对局")}</option>{recent.map((item) => <option key={item.game_id} value={item.game_id}>{recentGameLabel(item, locale)}</option>)}</select></label>}
    </section>
    {error && <div className="error-banner" role="alert"><span>{error}</span><button aria-label={t("Dismiss error", "关闭错误信息")} onClick={() => setError(null)}>×</button></div>}
    {!loaded && !busy && <button onClick={() => {bootStarted.current = false; setBootRetry((n) => n + 1);}}>{t("Reconnect", "重新连接")}</button>}
    <div className={`play-layout ${mode === "review" ? "review-layout" : ""}`}>
      <section className="board-panel" id="game-board" aria-label={t("Othello board", "翻转棋棋盘")}>
        <div className="board-topline"><span className="turn-label">{variation ? t("Analysis line", "分析演示") : mode === "review" ? t("Game history", "对局记录") : game?.difficulty ? ({easy: t("Beginner", "初级"), medium: t("Intermediate", "中级"), hard: t("Advanced", "高级")})[game.difficulty] : ""}</span><span className="turn-label" aria-live="polite">{mode === "review" ? null : playback ? t(`${colorName(playback.event.actor)} plays ${playback.event.coordinate}`, `${colorName(playback.event.actor)}下 ${playback.event.coordinate}`) : !loaded ? t("Preparing game…", "正在准备对局…") : turn ? mode === "play" ? turn === game?.human_color ? t("Your turn", "轮到你") : t("AI's turn", "轮到 AI") : t(`${colorName(turn)} to move`, `轮到${colorName(turn)}`) : t("Game over", "对局结束")}</span></div>
        <div className="board-with-labels"><div className="column-labels" aria-hidden="true">{"abcdefgh".split("").map((column) => <span key={column}>{column}</span>)}</div><div className="board-rows"><div className="row-labels" aria-hidden="true">{Array.from({length: 8}, (_, row) => <span key={row}>{row + 1}</span>)}</div><div className="board" role="group" aria-label={t("Board, a1 is at the top left", "棋盘，左上角为 a1")}>{Array.from({length: 64}, (_, index) => {
          const row = Math.floor(index / 8), column = index % 8, coordinate = `${"abcdefgh"[column]}${row + 1}`, cell = board?.[row]?.[column] ?? ".";
          const legal = canPractice ? !!variation?.exercise?.options.some((item) => item.coordinate === coordinate) : canMove && !!game?.legal_moves.includes(coordinate);
          const recommended = mode === "play" && visibleHint?.recommended_move === coordinate;
          const placed = teachingFrame?.coordinate === coordinate || (!teachingFrame && lastMove?.coordinate === coordinate);
          const flipped = teachingFrame ? teachingFrame.flipped.includes(coordinate) : reviewFlips.includes(coordinate) || (mode === "play" && playback?.phase === "flipped" && playback.flipped.includes(coordinate));
          const target = !!teachingFrame && variation?.focus_square === coordinate;
          const ray = comparisonRay?.includes(coordinate) || capturePreview && variation?.capture_lines?.some((line) => line.includes(coordinate));
          return <button key={coordinate} className={`square ${recommended ? "recommended" : ""} ${placed ? "lesson-placed" : ""} ${flipped ? "lesson-flipped" : ""} ${target ? "lesson-target" : ""} ${ray ? "lesson-ray" : ""} ${flipped && playback ? "slow-flip" : ""}`} disabled={!legal} aria-label={`${coordinate}, ${cell === "X" ? t("black disc", "黑棋") : cell === "O" ? t("white disc", "白棋") : t("empty", "空位")}${legal ? t(", legal move", "，合法落点") : ""}${recommended ? t(", recommended move", "，推荐落点") : ""}${placed ? t(", last move", "，最近落子") : ""}${flipped ? t(", flipped this step", "，本步翻转") : ""}`} onClick={() => {
            if (canPractice && variation?.exercise) {const option = variation.exercise.options.find((item) => item.coordinate === coordinate); if (option) setVariation({...variation, frame: 1, lesson_frames: option.frames, capture_lines: option.capture_lines, capture_frame: option.frames.length - 2, focus_square: option.safe ? null : variation.exercise.target, exercise: {...variation.exercise, attempt: coordinate}});}
            else if (game && canMove) void perform(async () => acceptGame(await api<GameState>(`/games/${game.game_id}/moves`, {coordinate, expected_revision: game.revision, request_id: requestId()})));
          }}>{cell !== "." && <span className={`disc ${cell === "X" ? "black" : "white"}`} />}{cell === "." && legal && (canPractice || showLegalMoves) && <span className="legal-marker" />}{recommended && <span className="hint-ring" />}{mode === "play" && (placed || target || ray || recommended) && <span className="lesson-coordinate">{coordinate}</span>}</button>;
        })}</div></div></div>
        {mode === "review" && game && <ReviewNavigation game={game} revision={historyRevision} select={selectPosition} />}
      </section>
      <aside className="side-panel">
        <section className="score-card" aria-label={t("Disc count", "棋子数量")}><div className="score-line">{(["X", "O"] as Color[]).map((color) => <div key={color}><i className={`mini-disc ${color === "X" ? "black" : "white"}`} /><span>{colorName(color)}</span><strong>{board ? [...board.join("")].filter((cell) => cell === color).length : "—"}</strong></div>)}</div>{mode === "play" && game?.result && <p className="result-label">{game.result.winner === "draw" ? t("Draw", "和棋") : game.result.winner === game.human_color ? t("You win", "你获胜") : t("AI wins", "AI 获胜")}</p>}</section>
        {mode === "play" ? <section className="tips-card"><label className="speed-picker">{t("Move speed", "落子速度")}<select aria-label={t("Move speed", "落子速度")} value={speed} onChange={(event) => {const value = event.target.value as Speed; speedRef.current = value; setSpeed(value); localStorage.setItem("nemothello_speed", value);}}><option value="normal">{t("Normal", "普通")}</option><option value="slow">{t("Slow", "慢速")}</option></select></label>{game?.status === "active" && <><div className="card-heading"><span>{t("Legal moves", "可落子点")}</span><button className={`toggle ${showLegalMoves ? "on" : ""}`} role="switch" aria-checked={showLegalMoves} aria-label={t("Legal moves", "可落子点")} onClick={() => {const next = !showLegalMoves; setShowLegalMoves(next); localStorage.setItem("nemothello_legal_moves", String(next));}}><span /></button></div><div className="card-heading"><span>{t("Recommended move", "推荐点")}</span><button className={`toggle ${tips ? "on" : ""}`} role="switch" aria-checked={tips} aria-label={t("Move hints", "落点提示")} onClick={() => {tipsRef.current = !tips; setTips(!tips);}}><span /></button></div></>}{hintError && <p role="alert">{hintError}<button onClick={() => setHintRetry((n) => n + 1)}>{t("Retry hint", "重试提示")}</button></p>}</section> : <section className="teaching-panel" aria-label={t("Teaching", "教学")}>
          <TermHelp />
          {modelLimited && <p className="muted" role="status">{t("Today's Nemotron coaching limit has been reached; it resets tomorrow (UTC). Board demonstrations still work.", "今天的 Nemotron 讲解次数已用完，明天（UTC 时间）恢复。棋盘推演照常可以看。")}</p>}
          {summaryView && game ? <GameSummaryCard game={game} keyMoves={keyMoves[game.game_id]} summary={summary} pending={summaryPending} busy={busy} select={selectPosition} retry={retrySummary} reviewTask={tasks.find((entry) => entry.purpose === "review" && entry.game_id === game.game_id)?.task} /> : <>
          {game && <button className="summary-back" onClick={() => selectPosition(null)}>{t("← Game summary", "← 整盘总结")}</button>}
          {currentLesson && game ? <>
            <ReviewCoach key={`${game.game_id}:${historyRevision}:${locale}`} request={currentLesson.coaching_status !== "ready" && !pendingLesson && !autoCoach
              && currentLesson.comparison.choices[0].assessment.status !== "forced"
              && <LessonStart busy={busy} retry={!!lessonFailure} note={lessonFailure?.quiet ? lessonFailure.text : undefined} start={() => teach()} />} game={game} lesson={currentLesson} variation={variation} pending={pendingLesson} busy={busy} showVariation={setVariation} ask={(text, view) => teach(text, view)} answer={questionAnswer} answerTaskId={latestQuestion?.task.task_id} asked={latestQuestion?.question} questionPending={!!latestQuestion && ["queued", "running"].includes(latestQuestion.task.status)} continueGame={continueGame} findEarlier={findEarlier} revisit={selectPosition} practice={startPractice} />
            {lessonFailure && !lessonFailure.quiet && <p className="inline-error" role="alert">{lessonFailure.text}</p>}
          </> : canTeach && game ? reviewPending ? <p className="teaching-empty" role="status">{t("Analyzing this game…", "正在分析这盘棋…")}</p>
            : <LessonStart key={`${game.game_id}:${historyRevision}:${locale}`} busy={busy || pendingLesson} retry={latestLessonTask?.task.status === "failed"} start={() => teach()} />
            : <p className="teaching-empty" role="status">{t("You have no played moves to review in this game yet.", "你在这盘对局中还没有落子可供复盘。")}</p>}
          {canTeach && currentLesson?.coaching_status !== "failed" && latestLessonTask?.task.error && !coachingFailure(latestLessonTask.task.error.code, null, "lesson", locale).quiet && <p role="alert" className="inline-error">{latestLessonTask.task.error.message}</p>}
          {canTeach && questionFailure && <p role={questionFailure.quiet ? "status" : "alert"} className={questionFailure.quiet ? "muted" : "inline-error"}>{questionFailure.text}</p>}
          </>}
        </section>}
      </aside>
    </div>
  </main>;
}
