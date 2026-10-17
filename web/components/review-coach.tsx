import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useLocale } from "@/lib/locale";
import { comparisonTakeaway, lessonText } from "@/lib/teaching-text";
import type { Review, TeachingComparison, TeachingFrame } from "@/lib/types";

export type Practice = { revision: number; coordinate: string | null };
export type Variation = { revision: number; coordinate: string; frame: number; lesson_frames?: TeachingFrame[]; focus_square?: string | null; capture_lines?: string[][] };

export function ReviewCoach({ review, selectedRevision, practice, variation, busy, select, startPractice, continueGame, showVariation }: {
  review: Review;
  selectedRevision: number | null;
  practice: Practice | null;
  variation: Variation | null;
  busy: boolean;
  select: (revision: number) => void;
  startPractice: (revision: number) => void;
  continueGame: (revision: number, coordinate: string) => void;
  showVariation: (value: Variation | null) => void;
}) {
  const {locale, t} = useLocale();
  const [choice, setChoice] = useState<{revision: number; move: string} | null>(null);
  const [lesson, setLesson] = useState<TeachingComparison | null>(null);
  const [lessonError, setLessonError] = useState(false);
  const [retry, setRetry] = useState(0);
  const [demonstration, setDemonstration] = useState<string | null>(null);
  const focused = review.evidence.find((item) => item.revision === selectedRevision);
  const activePractice = practice?.revision === focused?.revision ? practice : null;
  const hidden = !!activePractice && activePractice.coordinate === null;
  const move = activePractice?.coordinate ?? (choice && choice.revision === focused?.revision ? choice.move : focused?.actual_move);
  const ready = lesson?.revision === focused?.revision && lesson?.selected_move === move ? lesson : null;
  const activeMove = ready?.choices.find((item) => item.coordinate === demonstration) ?? ready?.choices[0];
  const best = focused?.analysis.candidates.find((item) => item.coordinate === focused.recommended_move);
  const selected = focused?.analysis.candidates.find((item) => item.coordinate === move);
  const takeaway = ready ? comparisonTakeaway(ready, locale) : null;

  useEffect(() => {
    setLessonError(false);
    setDemonstration(null);
    if (!focused || !move || hidden) return;
    const controller = new AbortController();
    void api<TeachingComparison>(`/games/${review.game_id}/review/lesson?revision=${focused.revision}&move=${move}`, undefined, controller.signal)
      .then((result) => { if (!controller.signal.aborted) setLesson(result); })
      .catch(() => { if (!controller.signal.aborted) setLessonError(true); });
    return () => controller.abort();
  }, [review.game_id, focused?.revision, move, hidden, retry]);

  function demonstrate(coordinate: string, frame: number) {
    const branch = ready?.choices.find((item) => item.coordinate === coordinate);
    if (!branch || !focused) return;
    setDemonstration(coordinate);
    showVariation({revision: focused.revision, coordinate, frame, lesson_frames: branch.frames, focus_square: branch.target ?? ready?.choices[0].target, capture_lines: branch.capture_lines});
  }

  return <div className="review-coach">
    <p className="compact-result">{t("Black", "黑方")} {review.result.black_count} : {review.result.white_count} {t("White", "白方")}<span>{t("Hints followed", "提示采用")} {review.hint_adoption.adopted_turns}/{review.hint_adoption.shown_turns}</span></p>
    <div className="decision-picker" aria-label={t("Key decisions", "关键落子")}>{review.key_moves.map((entry) => <button key={entry.revision} aria-pressed={focused?.revision === entry.revision} onClick={() => select(entry.revision)}>{t("Position", "局面")} {entry.revision}</button>)}</div>
    {focused && selected && best ? <article className="coach-decision">
      <div className="comparison-controls"><label>{t("Compare move", "对比落点")}<select aria-label={t("Compare move", "对比落点")} value={move} disabled={hidden} onChange={(event) => { select(focused.revision); setChoice({revision: focused.revision, move: event.target.value}); }}>
        {focused.analysis.candidates.map((candidate) => <option key={candidate.coordinate} value={candidate.coordinate}>{candidate.coordinate}{candidate.coordinate === focused.actual_move ? t(" · Played", " · 实际落子") : ""}</option>)}
      </select></label><button disabled={busy || focused.actor !== review.human_color} onClick={() => startPractice(focused.revision)}>{t("Try on board", "在棋盘上尝试")}</button></div>
      {hidden ? <p role="status">{t("Choose a move on the board.", "在棋盘上选择一个落点。")}</p> : <>
        {lessonError ? <p role="alert">{t("Could not load the demonstration.", "落子演示加载失败。")} <button onClick={() => setRetry((value) => value + 1)}>{t("Retry", "重试")}</button></p> : ready && activeMove ? <>
          <div className="teaching-choices" role="group" aria-label={t("Compare demonstrations", "对比落子演示")}>{ready.choices.map((branch) => <button key={branch.coordinate} aria-pressed={branch.coordinate === activeMove.coordinate} onClick={() => { setDemonstration(branch.coordinate); if (variation?.lesson_frames) demonstrate(branch.coordinate, 1); }}>
            {t("Play", "下在")} {branch.coordinate}<span>{branch.coordinate === ready.recommended_move ? t("Engine recommendation", "引擎推荐") : t("Your comparison", "所选落点")}</span>
          </button>)}</div>
          <div className="concrete-lesson">{lessonText(ready, activeMove, locale).map((text) => <p key={text}>{text}</p>)}</div>
          <div className="teaching-steps" role="group" aria-label={t("Demonstration steps", "落子演示步骤")}>{activeMove.frames.slice(1).map((frame, index) => <button key={index} aria-pressed={variation?.coordinate === activeMove.coordinate && variation?.frame === index + 1 && !!variation.lesson_frames} onClick={() => demonstrate(activeMove.coordinate, index + 1)}>
            <small>{index + 1}</small>{frame.actor === "X" ? t("Black", "黑方") : t("White", "白方")} <strong>{frame.coordinate === "pass" ? t("Pass", "跳过") : frame.coordinate}</strong>
          </button>)}</div>
          {activeMove.kind === "corner_forced" && activeMove.checked_defenses.length > 0 && <details className="checked-defenses"><summary>{t(`Check all ${activeMove.checked_defenses.length} defenses`, `检查全部 ${activeMove.checked_defenses.length} 种应对`)}</summary><p>{t(`After ${activeMove.opponent_reply}, choose any defense below. The opponent can still play ${activeMove.target}:`, `${activeMove.opponent_reply} 后，点击任意应对，在棋盘上检查为什么对手下一回合仍能下 ${activeMove.target}：`)}</p><div className="defense-list">{activeMove.defense_lines.map((defense) => <button key={defense.coordinate} onClick={() => showVariation({revision: focused.revision, coordinate: activeMove.coordinate, frame: 3, lesson_frames: defense.frames, focus_square: activeMove.target, capture_lines: activeMove.capture_lines})}>{defense.coordinate}</button>)}</div></details>}
          {takeaway && <p className="concrete-takeaway">{takeaway}</p>}
          <p className="line-attribution">{activeMove.line_source === "rules" ? t("Legal tactical demonstration, checked by the rules engine.", "以上为棋规逐步校验的战术演示。") : t("One searched continuation; the opponent can choose other replies.", "以上为引擎的一条搜索续着，对手也可以选择其他回应。")}</p>
        </> : <p role="status">{t("Checking the moves…", "正在检查落子变化…")}</p>}
        <details className="comparison-scores"><summary>{t("View search scores", "查看搜索评分")}</summary><div className="table-scroll"><table className="move-comparison"><thead><tr><th>{t("Move", "落点")}</th><th>{t("Score", "评分")} ({focused.actor === "X" ? t("Black", "黑方") : t("White", "白方")})</th></tr></thead><tbody>{[...new Set([selected.coordinate, best.coordinate])].map((coordinate) => <tr key={coordinate}><td>{coordinate}</td><td>{focused.analysis.candidates.find((item) => item.coordinate === coordinate)!.score}</td></tr>)}</tbody></table></div><p>{selected.score_kind === "exact" && best.score_kind === "exact" ? t("Exact final disc differences under best play.", "双方最佳应对下的精确终局子差。") : t("Search estimates, not win probabilities.", "搜索估计值，不代表胜率。")}</p></details>
        <button className="continue-comparison" disabled={busy} onClick={() => continueGame(focused.revision, selected.coordinate)}>{t("Play on from", "从此处续下")} {selected.coordinate}</button>
      </>}
    </article> : <p>{t("Select a move to compare its alternatives.", "选择一步落子，查看不同落点的对比。")}</p>}
  </div>;
}
