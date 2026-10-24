import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import ts from "typescript";

const source = readFileSync(new URL("../lib/recent-games.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {restoreRecentGames, rememberGame, readRecentGames, recentGameLabel} = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const saved = {game_id:"saved-game", human_color:"X", parent_game_id:null, status:"finished"};

test("server history is available after the browser loses its cached list", () => {
  const restored = restoreRecentGames([saved], []);
  assert.equal(restored.length, 1);
  assert.equal(restored[0].game_id, saved.game_id);
  assert.equal(restored[0].status, "finished");
  assert.match(recentGameLabel(restored[0], "en"), /Saved game 1/);
  assert.match(recentGameLabel(restored[0], "zh"), /已保存对局 1/);
});

test("server history replaces stale entries while preserving legacy game labels", () => {
  const current = readRecentGames(JSON.stringify([
    {game_id:"unavailable-in-this-session", status:"finished", number:8},
    {...saved, number:4},
  ]));
  const restored = restoreRecentGames([saved], current);
  assert.equal(restored.length, 1);
  assert.equal(restored[0].number, 4);
  assert.equal(restored[0].game_id, saved.game_id);
  assert.deepEqual(restoreRecentGames([], current), []);
});

test("opening an unfinished game does not add it to completed history", () => {
  const current = restoreRecentGames([saved], []);
  assert.deepEqual(rememberGame(current, {...saved, game_id:"new-game", status:"active"}), current);
});
