import { useState } from "react";
import { useLocale } from "@/lib/locale";

export function LessonStart({played, busy, retry, start}: {
  played: boolean; busy: boolean; retry: boolean; start: (reflection?: string) => void;
}) {
  const {t} = useLocale();
  const [reflection, setReflection] = useState("");
  return <form className="lesson-start" onSubmit={(event) => {event.preventDefault(); start(reflection.trim() || undefined);}}>
    <details>
      <summary>{played ? t("What did you want this move to do? (optional)", "你当时想通过这一步做到什么？（选填）") : t("What would you like to achieve? (optional)", "你想在这一步做到什么？（选填）")}</summary>
      <textarea aria-label={t("Your thinking about this move", "你对这一步的想法")} maxLength={1000} value={reflection} disabled={busy} onChange={(event) => setReflection(event.target.value)} placeholder={t("What did you notice or expect the opponent to do?", "你注意到了什么，或者预期对手会怎么应对？")} />
    </details>
    <button className="primary" disabled={busy}>{busy ? t("Analyzing…", "分析中…") : retry ? t("Retry teaching", "重试教学") : t("Teach this position", "教学")}</button>
  </form>;
}
