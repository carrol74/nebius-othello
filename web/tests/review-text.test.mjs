import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../lib/review-text.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022}}).outputText;
const {toolCallText} = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

test("coach tool steps describe checked lines and skip invalid calls", () => {
  const line = {name: "play_line", arguments: {revision: 16, moves: ["b3", "a3"]}, fact_id: "t1", error: null};
  const corner = {name: "check_corner_threat", arguments: {revision: 16, move: "b1"}, fact_id: "t2", error: null};
  const invalid = {name: "play_line", arguments: "{not json", fact_id: null, error: "Arguments must be one JSON object"};
  assert.equal(toolCallText(line, "zh"), "推演 b3 → a3");
  assert.equal(toolCallText(corner, "en"), "checked corners after b1");
  assert.equal(toolCallText(invalid, "en"), null);
});
