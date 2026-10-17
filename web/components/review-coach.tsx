import { useState } from "react";
import { useLocale } from "@/lib/locale";
import { compareMoves } from "@/lib/review-text";
import type { Review } from "@/lib/types";

export type Practice = { revision: number; coordinate: string | null };
export type Variation = { revision: number; coordinate: string; frame: number };

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
  const focused = review.evidence.find((item) => item.revision === selectedRevision);
  const activePractice = practice?.revision === focused?.revision ? practice : null;
  const hidden = !!activePractice && activePractice.coordinate === null;
  const move = activePractice?.coordinate ?? (choice && choice.revision === focused?.revision ? choice.move : focused?.actual_move);
  const best = focused?.analysis.candidates.find((item) => item.coordinate === focused.recommended_move);
  const selected = focused?.analysis.candidates.find((item) => item.coordinate === move);
  const lesson = review.coaching?.find((card) => card.revision === focused?.revision);
  const moves = [...new Set([move, best?.coordinate])].filter((item): item is string => !!item);
  const summary = review.result;

  return <div className="review-coach">
    <p className="compact-result">{t("Black", "黑方")} {summary.black_count} : {summary.white_count} {t("White", "白方")}<span>{t("Hints followed", "提示采用")} {review.hint_adoption.adopted_turns}/{review.hint_adoption.shown_turns}</span></p>
    {review.key_moves.length > 0 && <div className="decision-picker" aria-label={t("Key decisions", "关键落子")}>
      {review.key_moves.map((entry) => <button key={entry.revision} aria-pressed={focused?.revision === entry.revision} onClick={() => select(entry.revision)}>{t("Position", "局面")} {entry.revision}</button>)}
    </div>}
    {focused && selected && best ? <article className="coach-decision">
      <div className="comparison-controls"><label>{t("Compare move", "对比落点")}<select aria-label={t("Compare move", "对比落点")} value={move} disabled={hidden} onChange={(event) => { select(focused.revision); setChoice({revision: focused.revision, move: event.target.value}); }}>
        {focused.analysis.candidates.map((candidate) => <option key={candidate.coordinate} value={candidate.coordinate}>{candidate.coordinate}{candidate.coordinate === focused.actual_move ? t(" · Played", " · 实际落子") : ""}</option>)}
      </select></label><button disabled={busy || focused.actor !== review.human_color} onClick={() => startPractice(focused.revision)}>{t("Try on board", "在棋盘上尝试")}</button></div>
      {hidden ? <p role="status">{t("Choose a move on the board.", "在棋盘上选择一个落点。")}</p> : <>
        <div className="table-scroll"><table className="move-comparison"><thead><tr><th>{t("Move", "落点")}</th><th>{t("Score", "评分")} ({focused.actor === "X" ? t("Black", "黑方") : t("White", "白方")})</th><th>{t("Opponent replies", "对手合法落点")}</th></tr></thead>
          <tbody>{moves.map((coordinate) => {
            const candidate = focused.analysis.candidates.find((item) => item.coordinate === coordinate)!;
            const details = focused.comparisons?.find((item) => item.coordinate === coordinate);
            return <tr key={coordinate}><td><strong>{coordinate}</strong><span className="comparison-label">{coordinate === best.coordinate ? t("Engine recommendation", "引擎推荐") : coordinate === focused.actual_move ? t("Played", "实际落子") : t("Selected", "所选落点")}</span></td><td>{candidate.score}</td><td>{details?.opponent_moves ?? "—"}</td></tr>;
          })}</tbody></table></div>
        <div className="move-reason">{compareMoves(focused, selected.coordinate, locale, lesson?.lesson_id).map((text) => <p key={text}>{text}</p>)}</div>
        <div className="comparison-actions"><button disabled={busy} onClick={() => continueGame(focused.revision, selected.coordinate)}>{t("Play on from", "从此处续下")} {selected.coordinate}</button>
          {focused.comparisons?.length ? <details><summary>{t("Search continuations", "搜索续着")}</summary><div className="variation-moves">{moves.map((coordinate) => <button key={coordinate} aria-pressed={variation?.revision === focused.revision && variation.coordinate === coordinate} onClick={() => showVariation({revision: focused.revision, coordinate, frame: 1})}>{coordinate}</button>)}</div></details> : null}</div>
      </>}
    </article> : <p>{t("Select a move to compare its alternatives.", "选择一步落子，查看不同落点的对比。")}</p>}
  </div>;
}
