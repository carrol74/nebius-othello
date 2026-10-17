import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../lib/teaching-text.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022}}).outputText;
const {lessonText, comparisonTakeaway, stepText, captureLineText} = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const cases = JSON.parse(readFileSync(new URL("../../backend/tests/fixtures/teaching-native-cases.json", import.meta.url), "utf8"));

test("both languages teach the verified corner threat with the actual response", () => {
  const item = cases["16"], choice = item.choices[0];
  for (const locale of ["en", "zh"]) {
    const text = lessonText(item, choice, locale).join(" ");
    for (const fact of ["b1", "e1", "a1", "9"]) assert.ok(text.includes(fact));
    assert.doesNotMatch(text, /-30|-10|20/);
    assert.ok(comparisonTakeaway(item, locale).includes("b3"));
  }
  assert.match(stepText(choice.frames[2], "zh"), /白方下 e1，翻转 e2/);
  assert.match(stepText(choice.frames[4], "en"), /White plays a1/);
  const ray = captureLineText(choice.capture_lines, "O", "zh");
  assert.match(ray, /e1 的白方棋子封住一端/);
  assert.match(ray, /翻转 b1、c1、d1/);
});

test("shared corner access is never presented as the cause of a score difference", () => {
  assert.match(comparisonTakeaway(cases["22"], "en"), /does not explain the score difference/);
  assert.match(comparisonTakeaway(cases["22"], "zh"), /不能解释它们的评分差/);
});
