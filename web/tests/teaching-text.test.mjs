import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../lib/teaching-text.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022}}).outputText;
const {lessonText, lessonPrompt, defenseFeedback, comparisonTakeaway, stepText, captureLineText, teachingChoiceLabel, teachingFactText} = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const cases = JSON.parse(readFileSync(new URL("../../backend/tests/fixtures/teaching-native-cases.json", import.meta.url), "utf8"));
const {review} = JSON.parse(readFileSync(new URL("../../backend/tests/fixtures/review-native-positions.json", import.meta.url), "utf8"));
const forced = JSON.parse(readFileSync(new URL("../../backend/tests/fixtures/forced-move-native.json", import.meta.url), "utf8"));

test("both languages teach the verified corner threat with the actual response", () => {
  const item = cases["16"], choice = item.choices[0];
  for (const locale of ["en", "zh"]) {
    const text = [...lessonText(item, choice, locale), comparisonTakeaway(item, locale)].join(" ");
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

test("a forced move is labeled as played and compulsory with no recommendation or blame", () => {
  const item = forced.evidence, choice = forced.comparison.choices[0];
  assert.equal(item.analysis.candidates.length, 1);
  assert.equal(teachingChoiceLabel(choice, "en"), "Your game move");
  assert.equal(teachingChoiceLabel(choice, "zh"), "你当时下的");
  for (const locale of ["en", "zh"]) {
    const text = lessonText(forced.comparison, choice, locale).join(" ");
    assert.ok(text.includes("d8") && text.includes("h8"));
    assert.match(text, /only legal move|唯一的合法落点/);
    assert.doesNotMatch(text, /Recommended|lets White|gives White|选错|失误|推荐/);
  }
});

test("a highest-rated move retains an alternative and does not promise a favorable position", () => {
  const comparison = cases["16-best"], best = comparison.choices[0];
  assert.ok(best.assessment.legal_move_count > 1 && best.score < 0);
  assert.equal(comparison.choices.length, 2);
  assert.equal(comparison.reference_move, "b1");
  const text = lessonText(comparison, best, "en").join(" ");
  assert.match(text, /highest|equally best/);
  assert.match(text, /position still favors White/);
  assert.doesNotMatch(text, /only legal/);
  const opening = cases["0"].choices[0];
  assert.equal(teachingChoiceLabel(opening, "en"), "Your game move");
  assert.equal(teachingChoiceLabel(best, "zh"), "假设改下");
});

test("equally rated alternatives have no score-based preference in either language", () => {
  const opening = cases["0"];
  assert.equal(opening.insight.kind, "equal");
  assert.notEqual(opening.choices[0].coordinate, opening.choices[1].coordinate);
  for (const locale of ["en", "zh"]) {
    const text = lessonText(opening, opening.choices[1], locale).join(" ");
    assert.match(text, /tied for the highest|并列/);
    assert.doesNotMatch(text, /失误|mistake|only legal/);
  }
  assert.equal(comparisonTakeaway(opening, "en"), null);
});

test("exact outcomes and search estimates keep different labels", () => {
  const exact = cases["47"], estimate = cases["16"];
  assert.match(lessonText(exact, exact.choices[0], "en")[0], /exact endgame analysis/i);
  assert.match(lessonText(estimate, estimate.choices[0], "en")[0], /current search/);
});

test("step narration is reserved for the board and choice labels describe their origin", () => {
  for (const locale of ["en", "zh"]) {
    const comparison = cases["16-best"];
    for (const choice of comparison.choices) {
      const label = teachingChoiceLabel(choice, locale);
      assert.doesNotMatch(label, /selected|Your choice|所选|评分|highest/);
      assert.doesNotMatch(lessonText(comparison, choice, locale).join(" "), /Black plays|White plays|黑方下|白方下/);
    }
  }
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
  assert.match(comparisonTakeaway(cases["16"], "zh"), /全部合法回应/);
  assert.match(comparisonTakeaway(cases["16"], "zh"), /e1.*b1 防守/);
  assert.match(comparisonTakeaway(cases["16"], "en"), /not the rest of the game/);
});

test("verified proof facts keep their scope and coordinates in both languages", () => {
  for (const locale of ["en", "zh"]) {
    const proof = teachingFactText(cases["16"], "p16:proof_b1", locale);
    for (const coordinate of ["b1", "e1", "a1"]) assert.ok(proof.includes(coordinate));
    assert.match(proof, /three plies|三步/);
    const defense = teachingFactText(cases["16"], "p16:defense", locale);
    assert.match(defense, /every legal next reply|全部合法回应/);
  }
  assert.doesNotMatch(teachingFactText(cases["16"], "p16:proof_b1", "zh"), /Black|White|After|verified/);
  assert.equal(teachingFactText(cases["16"], "p16:score", "zh"), null);
});
