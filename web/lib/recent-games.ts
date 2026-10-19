import type { Locale } from "./locale";
import type { Color, GameState } from "./types";

export type RecentGame = {
  game_id: string;
  created_at: string | null;
  human_color: Color | null;
  branch: boolean;
  number: number;
  status?: "finished";
};

export function readRecentGames(saved: string): RecentGame[] {
  const parsed: unknown = JSON.parse(saved);
  if (!Array.isArray(parsed) || !parsed.every((item) => item && typeof item.game_id === "string")) {
    throw new Error("Saved game list is invalid");
  }
  return parsed.slice(0, 20).map((item, index, items) => ({
    game_id: item.game_id,
    created_at: typeof item.created_at === "string" ? item.created_at : null,
    human_color: item.human_color === "X" || item.human_color === "O" ? item.human_color
      : typeof item.label === "string" && item.label.includes("Black") ? "X"
      : typeof item.label === "string" && item.label.includes("White") ? "O" : null,
    branch: typeof item.branch === "boolean" ? item.branch : typeof item.label === "string" && item.label.startsWith("Branch"),
    number: Number.isInteger(item.number) && item.number > 0 ? item.number : items.length - index,
    status: item.status === "finished" ? "finished" : undefined,
  }));
}

export function rememberGame(current: RecentGame[], game: GameState): RecentGame[] {
  if (game.status !== "finished") return current.filter((item) => item.game_id !== game.game_id);
  const previous = current.find((item) => item.game_id === game.game_id);
  return [{
    game_id: game.game_id,
    created_at: game.created_at ?? previous?.created_at ?? null,
    human_color: game.human_color,
    branch: !!game.parent_game_id,
    number: previous?.number ?? Math.max(0, ...current.map((item) => item.number)) + 1,
    status: "finished" as const,
  }, ...current.filter((item) => item.game_id !== game.game_id)].slice(0, 20);
}

export function recentGameLabel(game: RecentGame, locale: Locale): string {
  const zh = locale === "zh";
  const date = game.created_at ? new Date(game.created_at) : null;
  const when = date && Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat(zh ? "zh-CN" : "en-GB", {
    year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
  }).format(date) : zh ? `已保存对局 ${game.number}` : `Saved game ${game.number}`;
  const kind = game.branch ? zh ? "分支" : "Branch" : date ? zh ? "对局" : "Game" : null;
  const color = game.human_color === "X" ? zh ? "黑方" : "Black" : game.human_color === "O" ? zh ? "白方" : "White" : null;
  return [when, kind, color].filter(Boolean).join(" · ");
}
