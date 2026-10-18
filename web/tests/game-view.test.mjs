import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import ts from "typescript";

const source = readFileSync(new URL("../lib/game-view.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {savedPosition, placedBoard, moveFlips} = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const native = JSON.parse(readFileSync(new URL("../../backend/tests/fixtures/teaching-native-cases.json", import.meta.url), "utf8"));
const frames = native["16"].choices[0].defense_lines.find((item) => item.coordinate === "g6").frames;
const history = frames.slice(1).map((frame, index) => ({...frame, revision:index+1, kind:"move"}));

test("reviewing every native snapshot leaves the current game unchanged", () => {
  const game = {initial_board:frames[0].board, initial_turn:frames[0].turn, board:frames.at(-1).board, history};
  const before = JSON.stringify(game);
  for (let revision=history.length;revision>=0;revision--) assert.deepEqual(savedPosition(game,revision).board,frames[revision].board);
  assert.equal(JSON.stringify(game),before);
});

test("slow placement preserves discs until the authoritative flip phase", () => {
  for (let index=0;index<history.length;index++) {
    const before = frames[index].board, event = history[index], placed = placedBoard(before,event);
    assert.deepEqual(moveFlips(before,event).sort(),[...frames[index+1].flipped].sort());
    for (const coordinate of frames[index+1].flipped) {
      const row=Number(coordinate[1])-1, col=coordinate.charCodeAt(0)-97;
      assert.equal(placed[row][col],before[row][col]);
      assert.notEqual(placed[row][col],event.board[row][col]);
    }
    assert.deepEqual(before,frames[index].board);
  }
});
