"use client";

import { useRef } from "react";
import { useLocale } from "@/lib/locale";

export function GameRules() {
  const {t} = useLocale();
  const dialog = useRef<HTMLDialogElement>(null);

  return <>
    <button className="rules-button" aria-haspopup="dialog" onClick={() => dialog.current?.showModal()}>{t("Rules", "规则")}</button>
    <dialog className="rules-dialog" ref={dialog} aria-labelledby="rules-title" onClick={(event) => {
      if (event.target === event.currentTarget) dialog.current?.close();
    }}>
      <div className="rules-content">
        <div className="rules-heading"><h2 id="rules-title">{t("How to play", "游戏规则")}</h2><button aria-label={t("Close rules", "关闭规则")} onClick={() => dialog.current?.close()}>×</button></div>
        <ul>
          <li>{t("Black goes first. Take turns placing one disc on an empty square.", "黑方先手，双方轮流在空格放置一枚棋子。")}</li>
          <li>{t("Your new disc must trap an unbroken line of opposing discs against another of your discs, horizontally, vertically or diagonally. Flip all discs trapped in every direction.", "新落下的棋子必须与己方棋子在横线、竖线或斜线上夹住连续的对方棋子。所有方向上被夹住的棋子都要翻转。")}</li>
          <li>{t("If you have no legal move, you must pass and your opponent plays again. You cannot pass when a legal move is available.", "没有合法落点时必须跳过回合，由对方继续；有合法落点时不能跳过。")}</li>
          <li>{t("The game ends when neither side can move, even if empty squares remain. The side with more discs wins; equal counts are a draw.", "双方都没有合法落点时结束，即使还有空格。棋子多的一方获胜，数量相同则为和棋。")}</li>
        </ul>
      </div>
    </dialog>
  </>;
}
