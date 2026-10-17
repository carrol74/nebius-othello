"use client";

import { createContext, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";

export type Locale = "en" | "zh";
const LocaleContext = createContext<{ locale: Locale; setLocale: (value: Locale) => void }>({ locale: "en", setLocale: () => {} });

export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, changeLocale] = useState<Locale>("en");
  useEffect(() => {
    const saved = localStorage.getItem("nemothello_locale");
    if (saved === "en" || saved === "zh") changeLocale(saved);
  }, []);
  useEffect(() => { document.documentElement.lang = locale === "zh" ? "zh-CN" : "en"; }, [locale]);
  function setLocale(value: Locale) {
    localStorage.setItem("nemothello_locale", value);
    changeLocale(value);
  }
  return <LocaleContext.Provider value={{locale, setLocale}}>{children}</LocaleContext.Provider>;
}

export function useLocale() {
  const context = useContext(LocaleContext);
  return {...context, t: (english: string, chinese: string) => context.locale === "zh" ? chinese : english};
}

export function LanguageSwitch() {
  const {locale, setLocale} = useLocale();
  return <div className="language-switch" role="group" aria-label="Language / 语言">
    <button lang="en" aria-pressed={locale === "en"} onClick={() => setLocale("en")}>EN</button>
    <button lang="zh-CN" aria-pressed={locale === "zh"} onClick={() => setLocale("zh")}>中文</button>
  </div>;
}
