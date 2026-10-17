import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../lib/teaching-text.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022}}).outputText;
const {lessonText, lessonPrompt, defenseFeedback, comparisonTakeaway, stepText, captureLineText} = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const cases = JSON.parse(readFileSync(new URL("../../backend/tests/fixtures/teaching-native-cases.json", import.meta.url), "utf8"));

test("both languages teach the verified corner threat with the actual response", () => {
  const item = cases["16"], choice = item.choices[0];
  for (const locale of ["en", "zh"]) {
    const text = lessonText(item, choice, locale).join(" ");
    for (const fact of ["b1", "e1", "a1"]) assert.ok(text.includes(fact));
    assert.doesNotMatch(text, /-30|-10|20/);
    assert.ok(comparisonTakeaway(item, locale).includes("b3"));
  }
  assert.match(stepText(choice.frames[2], "zh"), /白方下 e1，翻转 e2/);
  assert.match(stepText(choice.frames[4], "en"), /White plays a1/);
  const ray = captureLineText(choice.capture_lines, "O", "zh");
  assert.match(ray, /e1 已经有一颗白方棋子/);
  assert.match(ray, /b1、c1、d1 夹住/);
});

test("shared corner access is never presented as the cause of a score difference", () => {
  assert.match(comparisonTakeaway(cases["22"], "en"), /alone does not tell us which move is better/);
  assert.match(comparisonTakeaway(cases["22"], "zh"), /光看谁能占角还分不出优劣/);
});

test("the opening question invites a defense without revealing the outcome", () => {
  for (const locale of ["en", "zh"]) {
    const text = lessonPrompt(cases["16"], cases["16"].choices[0], locale);
    assert.ok(text.includes("e1") && text.includes("a1"));
    assert.doesNotMatch(text, /9|cannot|挡不住|来不及/);
  }
});

test("feedback names the attempted move and points back to the earlier decision", () => {
  const branch = cases["16"].choices[0];
  assert.ok(branch.defense_lines.some((defense) => defense.coordinate === "g6"));
  for (const locale of ["en", "zh"]) {
    const text = defenseFeedback(branch.coordinate, "g6", branch.target, locale);
    for (const fact of ["g6", "a1", "b1"]) assert.ok(text.includes(fact));
  }
  assert.match(comparisonTakeaway(cases["16"], "zh"), /b1 仍然空着/);
});
