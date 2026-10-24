import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../lib/teaching-text.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022}}).outputText;
const {lessonText, lessonPrompt, defenseFeedback, comparisonTakeaway, stepText, captureLineText, teachingChoiceLabel, teachingFactText, continuationText, teachingNote} = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const cases = JSON.parse(readFileSync(new URL("../../backend/tests/fixtures/teaching-native-cases.json", import.meta.url), "utf8"));
const {review} = JSON.parse(readFileSync(new URL("../../backend/tests/fixtures/review-native-positions.json", import.meta.url), "utf8"));
const forced = JSON.parse(readFileSync(new URL("../../backend/tests/fixtures/forced-move-native.json", import.meta.url), "utf8"));
const ordinary = JSON.parse(readFileSync(new URL("../../backend/tests/fixtures/ordinary-move-native.json", import.meta.url), "utf8"));

test("analysis limits have one shared note while lessons retain concrete move explanations", () => {
  for (const locale of ["en", "zh"]) {
    assert.match(teachingNote(locale), /before your move|落子前/);
    assert.match(teachingNote(locale), /not win probabilities|不代表胜率/);
    assert.match(teachingNote(locale), /every score difference|全部评分差距/);
    for (const comparison of [...Object.values(cases), ordinary.comparison]) {
      const body = comparison.choices.flatMap((choice) => lessonText(comparison, choice, locale)).join(" ")
        + (comparisonTakeaway(comparison, locale) ?? "");
      assert.doesNotMatch(body, /This covers that short sequence|available evidence does not explain|do not explain the full score gap|结论只覆盖|不代表这个角以后|现有证据还不足以|不能单独解释完整评分差距/);
    }
  }
});

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

test("the recommendation stays paired with the lower-rated history without promising a win", () => {
  const comparison = cases["16-best"], best = comparison.choices[0];
  assert.ok(best.assessment.legal_move_count > 1 && best.score < 0);
  assert.equal(comparison.choices.length, 2);
  assert.equal(comparison.reference_move, "b1");
  const text = lessonText(comparison, best, "en").join(" ");
  assert.match(text, /highest|equally best/);
  assert.doesNotMatch(text, /position still favors|局面仍偏向/);
  assert.doesNotMatch(text, /only legal/);
  const opening = cases["0"].choices[0];
  assert.equal(teachingChoiceLabel(opening, "en"), "Your game move");
  assert.equal(teachingChoiceLabel(best, "zh"), "推荐走法");
  assert.equal(teachingChoiceLabel(best, "en"), "Recommended move");
});

test("an ordinary highest-rated move teaches a concrete continuation instead of stating an unexplained advantage", () => {
  const comparison = ordinary.comparison, choice = comparison.choices[0];
  for (const locale of ["en", "zh"]) {
    const text = lessonText(comparison, choice, locale).join(" ");
    assert.ok(text.includes("e5") && text.includes("c6"));
    assert.match(text, /anchor|夹击/);
    assert.doesNotMatch(text, /position still favors|偏向白方|because.*score|所以.*评分/);
    assert.equal(teachingFactText(comparison, "p8:continuation_f5", locale), continuationText(choice, locale));
    const explanation = captureLineText([choice.continuation_lesson.capture_line], "X", locale);
    for (const coordinate of ["e2", "e3", "e4", "e5"]) assert.ok(explanation.includes(coordinate));
  }
  assert.equal(choice.continuation_lesson.frame_index, 3);
  assert.equal(choice.frames[2].coordinate, "c6");
  assert.equal(choice.frames[3].coordinate, "e2");
});

test("every displayed ordinary move has a lesson about the local mechanism or the final count", () => {
  for (const comparison of [...Object.values(cases), ordinary.comparison]) {
    for (const choice of comparison.choices.filter((choice) => choice.kind === "line")) {
      for (const locale of ["en", "zh"]) {
        const text = lessonText(comparison, choice, locale);
        const explainedByComparison = !!comparison.decision_contrast || ["corner_defense", "corner_access", "shared_corner"].includes(comparison.insight.kind);
        if (!explainedByComparison) assert.ok(text.length > 1);
        assert.doesNotMatch(text.join(" "), /position still favors|局面仍偏向/);
      }
    }
  }
});

test("decision explanations include both the reply removed and the reply opened, with no claim about score causation", () => {
  for (const comparison of [cases["2"], cases["2-best"]]) {
    for (const locale of ["en", "zh"]) {
      const text = comparisonTakeaway(comparison, locale);
      for (const coordinate of ["b6", "e6", "b5", "c5", "f5"]) assert.ok(text.includes(coordinate));
      assert.match(text, /also opens|也开放/);
      assert.doesNotMatch(text, /do not explain the full score gap|不能单独解释完整评分差距/);
      assert.doesNotMatch(text, /fewer.*better|少.*所以.*更好|wins|必胜/);
      assert.equal(teachingFactText(comparison, "p2:decision_contrast", locale), text);
      for (const choice of comparison.choices) {
        assert.equal(lessonText(comparison, choice, locale).length, 1);
      }
    }
  }
});

test("a tied-best historical move is shown alone without an unnecessary alternative", () => {
  const opening = cases["0"];
  assert.equal(opening.insight.kind, "best");
  assert.equal(opening.choices.length, 1);
  assert.equal(opening.reference_move, null);
  assert.equal(opening.recommended_move, opening.choices[0].coordinate);
  for (const locale of ["en", "zh"]) {
    const text = lessonText(opening, opening.choices[0], locale).join(" ");
    assert.match(text, /tied for the highest|并列/);
    assert.doesNotMatch(text, /失误|mistake|only legal/);
  }
  assert.equal(comparisonTakeaway(opening, "en"), null);
});

test("a highest-rated historical endgame move is shown alone and remains distinct from forced", () => {
  const comparison = cases["47"];
  assert.equal(comparison.choices.length, 1);
  assert.equal(comparison.insight.kind, "best");
  assert.ok(comparison.choices[0].assessment.legal_move_count > 1);
  for (const locale of ["en", "zh"]) {
    assert.doesNotMatch(lessonText(comparison, comparison.choices[0], locale).join(" "), /only legal|唯一/);
    assert.equal(comparisonTakeaway(comparison, locale), null);
  }
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

test("defense feedback names the root and attempted move without requiring another alternative", () => {
  const branch = cases["16"].choices[0];
  assert.ok(branch.defense_lines.some((defense) => defense.coordinate === "g6"));
  for (const locale of ["en", "zh"]) {
    const text = defenseFeedback(branch.coordinate, "g6", branch.target, locale);
    for (const fact of ["g6", "a1", "b1"]) assert.ok(text.includes(fact));
    assert.doesNotMatch(text, /other line|另一条/);
  }
  assert.match(comparisonTakeaway(cases["16"], "zh"), /全部合法回应/);
  assert.match(comparisonTakeaway(cases["16"], "zh"), /e1.*b1 防守/);
  assert.doesNotMatch(comparisonTakeaway(cases["16"], "en"), /not the rest of the game/);
});

test("verified proof facts keep their scope and coordinates in both languages", () => {
  for (const locale of ["en", "zh"]) {
    const proof = teachingFactText(cases["16"], "p16:proof_b1", locale);
    for (const coordinate of ["b1", "e1", "a1"]) assert.ok(proof.includes(coordinate));
    assert.match(proof, /on their next turn|再下一手/);
    const defense = teachingFactText(cases["16"], "p16:defense", locale);
    assert.match(defense, /every legal next reply|全部合法回应/);
  }
  assert.doesNotMatch(teachingFactText(cases["16"], "p16:proof_b1", "zh"), /Black|White|After|verified/);
  assert.equal(teachingFactText(cases["16"], "p16:score", "zh"), null);
});

test("a corner defense stays focused on h8 while disclosing the independent a8 threat", () => {
  for (const comparison of [cases['earlier-h8'], cases['earlier-h8-best']]) {
    const better = comparison.choices.find((choice) => choice.coordinate === 'd7');
    assert.equal(better.kind, 'corner_defense');
    assert.equal(better.target, 'h8');
    assert.equal(better.frames.length, 4);
    assert.deepEqual(better.frames.slice(1).map((frame) => frame.coordinate), comparison.insight.example);
    for (const locale of ['en', 'zh']) {
      const text = comparisonTakeaway(comparison, locale);
      for (const coordinate of ['g7', 'd7', 'h8', 'a8', ...comparison.insight.example]) assert.ok(text.includes(coordinate));
      assert.match(text, /within its next two turns|两次行动内/);
      assert.equal(teachingFactText(comparison, 'p12:proof_d7', locale), null);
      assert.ok(teachingFactText(comparison, 'p12:other_corners', locale).includes('a8'));
    }
  }
});

test('corner geometry comparisons name the common sequence without allowing an out-of-turn capture', () => {
  for (const comparison of Object.values(cases)) {
    const witness = comparison.insight.witness;
    if (!witness) continue;
    for (const locale of ['en', 'zh']) {
      const text = teachingFactText(comparison, `p${comparison.revision}:corner_contrast`, locale);
      for (const square of witness.opportunity.capture_line) assert.ok(text.includes(square));
      for (const move of witness.prefix.filter((move) => move !== 'pass')) assert.ok(text.includes(move));
      if (witness.prefix.length === 1) assert.match(text, /wait for their turn|等待各自回合/);
      assert.ok(comparisonTakeaway(comparison, locale).includes(text));
    }
  }
});
