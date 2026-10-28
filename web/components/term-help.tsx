"use client";

import { useRef } from "react";
import { useLocale } from "@/lib/locale";

const TERMS: [string, string, string, string][] = [
  ["Legal move", "合法落点",
    "An empty square where your new disc traps a line of opponent discs against another of your discs, horizontally, vertically or diagonally.",
    "你能下的空格。下在这里，新棋子要和你已有的一颗棋子，在横线、竖线或斜线上把对手的棋子夹在中间。"],
  ["Flip", "夹住、翻转",
    "Opponent discs trapped between your new disc and your other disc all turn to your color.",
    "被你的新棋子和另一颗你的棋子夹在中间的对手棋子，全部变成你的颜色。"],
  ["Capture line", "夹击线",
    "A line with one side's disc at one end and the other side's discs in the middle. Playing the open end flips the middle.",
    "一条线上，一端已经是某一方的棋子，中间连着另一方的棋子。只要在另一端的空格落子，中间的棋子就全部翻转。"],
  ["Reply", "应对",
    "The move the opponent makes right after yours.",
    "你下完一步后，对手接着下的那一步。"],
  ["Recommended move", "推荐走法",
    "The best move the Edax engine found in this position.",
    "Edax 引擎在这个局面找到的最好一步。"],
  ["Game assessment", "整盘评价",
    "Compares your choices with this game's saved search analysis. Forced moves are excluded, ties count as top choices, and displayed hints are noted. It describes this game's decisions, not a long-term skill rating or your intentions.",
    "依据这盘保存的搜索分析比较你的选择。被迫落子不计入选择质量，并列首选都算好选择，看过提示的回合会注明。评价描述本盘表现，不代表长期棋力等级，也不推断你的真实想法。"],
  ["Corner", "角",
    "a1, h1, a8 and h8. No square lies beyond a corner, so a corner disc can never be trapped or flipped.",
    "a1、h1、a8、h8 四个格子。角的外侧没有格子，对手没法从两头夹住角上的棋子，所以它永远不会被翻转。"],
  ["Continuation", "推演",
    "A few moves played forward from this position to show what can happen. It is one possible line; the opponent can choose other moves.",
    "从这个局面往后摆几步，看看会发生什么。这只是其中一种下法，对手也可以下别的。"],
  ["Key step", "关键一步",
    "The step in a continuation where the reason appears, such as a capture line forming or a corner becoming available.",
    "推演中讲解原因出现的那一步，比如一条夹击线连上了，或者对手可以抢角了。"],
  ["Disc next to an empty square", "挨着空格的棋子",
    "Your disc with at least one empty square beside it. The opponent may play on that square and flip it if a line through it ends in an opponent disc.",
    "旁边至少有一个空格的你的棋子。对手可以下在这个空格上；如果穿过这颗棋子的那条线另一头是对手的棋子，它就会被翻走。"],
  ["Quiet move", "安静的一步",
    "A move whose flipped discs, away from the edge, are all surrounded by discs. It gives the opponent few new places to attack.",
    "这一步翻过来的棋子（边上的不算）四周都已经有棋子，没有新增挨着空格的棋子，对手就很少有新的地方可以下。"],
  ["Safe reply", "安全落点",
    "An opponent reply that does not let you take a corner you could not take before.",
    "对手下了以后，不会让你拿到一个原来拿不到的角，这样的落点对对手来说是安全的。对手的安全落点越少，越容易被逼着下坏棋。"],
  ["Stable disc", "稳定子",
    "A disc that can never be flipped again, such as a corner disc or discs packed against a corner along the edge.",
    "以后再也不会被翻转的棋子，比如角上的棋子，以及沿着边和角连成一片的棋子。"],
  ["Empty region", "空地",
    "A group of touching empty squares near the end of the game. Playing first into a region with an odd number of squares often lets you make the last move there too.",
    "终局时连在一起的一片空格。先下进空格数是奇数的空地，往往也能在这块空地下最后一步。"],
  ["Pass", "跳过回合",
    "A side with no legal move cannot play, so the other side moves again.",
    "一方没有合法落点时不能下，由另一方接着下。"],
];

export function TermHelp() {
  const {locale, t} = useLocale();
  const dialog = useRef<HTMLDialogElement>(null);
  const zh = locale === "zh";

  return <>
    <button className="term-help-button" aria-haspopup="dialog" aria-label={t("Glossary", "名词解释")} title={t("Glossary", "名词解释")} onClick={() => dialog.current?.showModal()}>?</button>
    <dialog className="rules-dialog" ref={dialog} aria-labelledby="terms-title" onClick={(event) => {
      if (event.target === event.currentTarget) dialog.current?.close();
    }}>
      <div className="rules-content">
        <div className="rules-heading"><h2 id="terms-title">{t("Glossary", "名词解释")}</h2><button aria-label={t("Close glossary", "关闭名词解释")} onClick={() => dialog.current?.close()}>×</button></div>
        <dl className="term-list">
          {TERMS.map(([english, chinese, englishText, chineseText]) => <div key={english}>
            <dt>{zh ? chinese : english}</dt>
            <dd>{zh ? chineseText : englishText}</dd>
          </div>)}
        </dl>
      </div>
    </dialog>
  </>;
}
