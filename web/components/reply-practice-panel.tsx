import { useLocale } from "@/lib/locale";
import { replyOpportunityText } from "@/lib/teaching-text";
import type { PracticeState } from "./practice-panel";

export function ReplyPracticePanel({practice, busy, change, check, close}: {
  practice: PracticeState; busy: boolean;
  change: (value: PracticeState) => void; check: () => void; close: () => void;
}) {
  const {locale, t} = useLocale();
  const {question, move, alternative, reason} = practice;
  if (question.objective !== "reply_access") return null;
  const feedback = practice.feedback && "witness" in practice.feedback ? practice.feedback : null;
  const other = question.turn === "X" ? t("White", "白方") : t("Black", "黑方");
  return <div className="practice-panel">
    {!feedback ? <>
      <p>{t(`How do your moves change ${other}'s ability to play ${question.target} next?`, `你的走法会怎样影响${other}下一回合下 ${question.target} 的机会？`)}</p>
      <p role="status">{!move ? t("Choose the move that blocks the reply.", "先选择准备封住回应的走法。") : !alternative
        ? t(`You chose ${move} to block. Now choose a move that would allow the reply.`, `你选了 ${move} 来封住回应。再选一手准备作对照、允许该回应的走法。`)
        : t(`You chose ${move} to block and ${alternative} to allow the reply. Explain what changes.`, `你选了 ${move} 来封住回应，${alternative} 来允许回应。请说明两者改变了什么。`)}</p>
      <form onSubmit={(event) => {event.preventDefault(); check();}}>
        <textarea aria-label={t("Explain the difference between your choices", "解释两种走法的差别")} value={reason} maxLength={1000} rows={3} disabled={busy} onChange={(event) => change({...practice, reason:event.target.value})} placeholder={t("Which square changes, and how does it affect the capture?", "哪个格子发生了变化？它怎样影响夹击？")} />
        <div className="practice-actions"><button className="primary" disabled={busy || !move || !alternative || !reason.trim()}>{t("Check the comparison", "检查对比")}</button>
          {move && <button type="button" disabled={busy} onClick={() => change({...practice, move:null, alternative:null})}>{t("Choose again", "重新选择")}</button>}</div>
      </form>
    </> : <div role="status">
      <p>{!feedback.legal ? t("Your blocking choice is not a legal move.", "你选择用来封住回应的走法不合法。")
        : !feedback.move_matches_goal ? t("Your first move still allows the target reply.", "你的第一手仍然允许指定的回应。")
        : !feedback.alternative_legal ? t("Your comparison move is not legal.", "你选择作对照的走法不合法。")
        : !feedback.alternative_matches ? t("Your first move blocks the reply, but your comparison does not allow it.", "你的第一手封住了回应，但对照走法也没有允许该回应。")
        : t("Your two moves change the opponent's opportunity as you predicted.", "你的两手确实像你预期的那样，改变了对手的落子机会。")}</p>
      {!(feedback.move_matches_goal && feedback.alternative_matches) && <p>{t("Explore one pair that meets the goal:", "下面展示一组符合目标的走法：")}</p>}
      <div className="teaching-choices" role="group" aria-label={t("Compare the two boards", "对比两个棋盘")}>
        <button aria-pressed={practice.feedback_line === "blocking"} onClick={() => change({...practice, feedback_line:"blocking"})}>{t("Reply blocked", "回应被封住")}</button>
        <button aria-pressed={practice.feedback_line === "allowing"} onClick={() => change({...practice, feedback_line:"allowing"})}>{t("Reply allowed", "回应可以成立")}</button>
      </div>
      <p>{replyOpportunityText(feedback.witness, locale)}</p>
      {feedback.added_reply && <p>{t(`The blocking move also opens ${feedback.added_reply.coordinate}, which the other move does not allow.`, `封住指定回应的走法，也开放了 ${feedback.added_reply.coordinate}；另一手原本不允许这个回应。`)}</p>}
      <p className="muted">{t("Both complete immediate reply sets were checked. Meeting this goal does not identify the strongest move. Your written reason awaits human review.", "已核验两种走法后全部合法的即时回应。完成这个目标不能说明哪手最强；文字理由仍待人工评阅。")}</p>
    </div>}
    <button disabled={busy} onClick={close}>{t("Back to the lesson", "返回讲解")}</button>
  </div>;
}
