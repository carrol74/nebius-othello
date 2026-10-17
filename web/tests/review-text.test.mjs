import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../lib/review-text.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022}}).outputText;
const {compareMoves, factText} = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const {review} = JSON.parse(readFileSync(new URL("../../backend/tests/fixtures/review-native-positions.json", import.meta.url), "utf8"));

test("both languages preserve scores and omit unavailable mobility data", () => {
  const entry = review.evidence.find((item) => item.revision === 16);
  const english = compareMoves(entry, "b1", "en").join(" ");
  const chinese = compareMoves(entry, "b1", "zh").join(" ");
  for (const text of [english, chinese]) {
    for (const number of ["-10", "-30", "20"]) assert.ok(text.includes(number));
  }
  assert.doesNotMatch(english, /legal replies/);
  assert.doesNotMatch(chinese, /合法落点/);
});

test("tied endgame choices stay equally rated and use the right player perspective", () => {
  const entry = review.evidence.find((item) => item.revision === 47);
  assert.match(compareMoves(entry, "b8", "en").join(" "), /equally rated/);
  assert.match(compareMoves(entry, "b8", "zh").join(" "), /同样可以选择/);
  assert.match(factText({id:"p47:score",revision:47,text:"",topic:"comparison"}, review, "zh"), /白方视角/);
});

test("saved pass facts translate without inventing a score", () => {
  const text = factText({id:"p30:pass",revision:30,text:"",topic:"pass"}, review, "zh");
  assert.match(text, /黑方没有合法落点/);
  assert.doesNotMatch(text, /评分/);
});
