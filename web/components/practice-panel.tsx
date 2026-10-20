import { useLocale } from "@/lib/locale";
import { captureLineText } from "@/lib/teaching-text";
import type { PracticeFeedback, PracticeQuestion } from "@/lib/types";
import { ReplyPracticePanel } from "@/components/reply-practice-panel";

export type PracticeState = {
  question: PracticeQuestion;
  lesson_move: string;
  move: string | null;
  anchor: string | null;
  alternative: string | null;
  feedback_line: "blocking" | "allowing";
  reason: string;
  feedback: PracticeFeedback | null;
};

export function PracticePanel({practice, busy, change, check, close}: {
  practice: PracticeState; busy: boolean;
  change: (value: PracticeState) => void; check: () => void; close: () => void;
}) {
  const {locale, t} = useLocale();
  const {question, move, anchor, reason} = practice;
  if (question.objective === "reply_access") return <ReplyPracticePanel practice={practice} busy={busy} change={change} check={check} close={close} />;
  const feedback = practice.feedback && !("witness" in practice.feedback) ? practice.feedback : null;
  const color = (actor: string) => actor === "X" ? t("Black", "黑方") : t("White", "白方");
  const goal = question.objective === "anchor"
    ? t("Find a legal capture that uses a disc you gained on your previous turn as its other end.", "找一手合法夹击，利用你上一回合拿到的棋子作为另一端。")
    : question.objective === "recapture"
      ? t("Find a legal capture that flips back a disc the opponent just gained.", "找一手合法夹击，翻回对手刚刚拿到的棋子。")
      : t("Find a legal capture and identify the disc that anchors its other end.", "找一手合法夹击，并指出作为另一端的己方棋子。");
  return <div className="practice-panel">
    <p>{goal}</p>
    <p className="muted">{question.context.map((event) => t(
      `${color(event.actor)} played ${event.coordinate}, flipping ${event.flipped.join(", ")}.`,
      `${color(event.actor)}上一手下 ${event.coordinate}，翻转 ${event.flipped.join("、")}。`,
    )).join(" ")}</p>
    {!feedback ? <>
      <p role="status">{!move ? t("Choose your move on the board.", "在棋盘上选择落点。") : !anchor ? t(`Move: ${move}. Now select your disc at the other end of the capture.`, `落点：${move}。再点击夹击另一端的己方棋子。`) : t(`Move ${move}, anchor ${anchor}. Explain the capture before checking.`, `落点 ${move}，另一端 ${anchor}。检查前，说明你准备怎样夹击。`)}</p>
      <form onSubmit={(event) => {event.preventDefault(); check();}}>
        <textarea aria-label={t("Explain your capture", "说明你的夹击思路")} value={reason} maxLength={1000} rows={3} disabled={busy} onChange={(event) => change({...practice, reason:event.target.value})} placeholder={t("Which discs will these two ends trap?", "这两端会夹住哪些棋子？")} />
        <button className="primary" disabled={busy || !move || !anchor || !reason.trim()}>{t("Check the capture", "检查夹击")}</button>
      </form>
    </> : <div role="status">
      <p>{!feedback.legal ? t("That square is not a legal move here.", "这个格子在当前局面不能合法落子。") : !feedback.move_matches_goal ? t("Your move is legal, but does not meet this exercise's goal.", "你的落点合法，但没有完成这道练习要求的夹击。") : !feedback.anchor_matches ? t("Your move meets the goal, but that disc does not anchor the required capture.", "你的落点符合目标，但选出的棋子不能作为所需夹击的另一端。") : t("Your move and its anchor form the required capture.", "你选出的落点和另一端，能够完成要求的夹击。")}</p>
      <p>{!feedback.anchor_matches && t("One capture that meets the goal: ", "一个符合目标的夹击：")}{captureLineText([feedback.capture_line], question.turn, locale)}</p>
      <p className="muted">{t("The capture is checked; strongest play is not assessed. Your written reason is saved for human review.", "已核验夹击是否成立，尚未评价最优走法。文字理由已保存，待人工评阅。")}</p>
    </div>}
    <button disabled={busy} onClick={close}>{t("Back to the lesson", "返回讲解")}</button>
  </div>;
}
