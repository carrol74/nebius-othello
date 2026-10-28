import { useLocale } from "@/lib/locale";

export function LessonStart({busy, retry, note, start}: {busy: boolean; retry: boolean; note?: string; start: () => void}) {
  const {t} = useLocale();
  return <div className="lesson-start">
    {note && <p className="muted">{note}</p>}
    <button className="primary" disabled={busy} onClick={start}>{retry ? t("Explain again", "重新讲解") : t("Explain", "讲解")}</button>
  </div>;
}
