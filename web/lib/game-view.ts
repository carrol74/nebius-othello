import type { GameState, HistoryEvent } from "./types";

export function savedPosition(game: GameState, revision: number) {
  if (revision === 0) return {board: game.initial_board, turn: game.initial_turn};
  const event = game.history.find((item) => item.revision === revision);
  if (!event) throw new Error("This position is not in the saved game");
  return {board: event.board, turn: event.turn};
}

export function moveFlips(before: string[], event: HistoryEvent): string[] {
  return event.board.flatMap((row, y) => [...row].flatMap((cell, x) =>
    cell !== before[y][x] && `${"abcdefgh"[x]}${y + 1}` !== event.coordinate ? [`${"abcdefgh"[x]}${y + 1}`] : []));
}

export function placedBoard(before: string[], event: HistoryEvent): string[] {
  if (!event.coordinate) return before;
  const row = Number(event.coordinate[1]) - 1, column = event.coordinate.charCodeAt(0) - 97;
  return before.map((line, index) => index === row ? line.slice(0, column) + event.actor + line.slice(column + 1) : line);
}
