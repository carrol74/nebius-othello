import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../lib/teaching-text.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022}}).outputText;
const {lessonText, defenseFeedback, otherCornerText, stepText, captureLineText, teachingChoiceLabel, teachingNote} = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const cases = JSON.parse(readFileSync(new URL("../../backend/tests/fixtures/teaching-native-cases.json", import.meta.url), "utf8"));
const {review} = JSON.parse(readFileSync(new URL("../../backend/tests/fixtures/review-native-positions.json", import.meta.url), "utf8"));
const forced = JSON.parse(readFileSync(new URL("../../backend/tests/fixtures/forced-move-native.json", import.meta.url), "utf8"));
const ordinary = JSON.parse(readFileSync(new URL("../../backend/tests/fixtures/ordinary-move-native.json", import.meta.url), "utf8"));

test("analysis limits have one shared note while lessons retain concrete move explanations", () => {
  for (const locale of ["en", "zh"]) {
    assert.match(teachingNote(locale), /verified local changes|已验证的局部变化/);
    assert.match(teachingNote(locale), /final game result|最终结果/);
    assert.doesNotMatch(teachingNote(locale), /score|评分|胜率/);
    for (const comparison of [...Object.values(cases), ordinary.comparison]) {
      const body = comparison.choices.flatMap((choice) => lessonText(comparison, choice, locale)).join(" ");
      assert.doesNotMatch(body, /This covers that short sequence|available evidence does not explain|do not explain the full score gap|结论只覆盖|不代表这个角以后|现有证据还不足以|不能单独解释完整评分差距/);
    }
  }
});

test("both languages teach the verified corner threat with the actual response", () => {
  const item = cases["16"], choice = item.choices[0];
  for (const locale of ["en", "zh"]) {
    const text = lessonText(item, choice, locale).join(" ");
    for (const fact of ["b1", "b3", "e1", "a1"]) assert.ok(text.includes(fact));
    assert.doesNotMatch(text, /-30|-10|20/);
  }
  assert.match(stepText(choice.frames[2], item.actor, "zh"), /对手下 e1，翻转 e2/);
  assert.match(stepText(choice.frames[4], item.actor, "en"), /The opponent plays a1/);
  assert.match(stepText(choice.frames[1], item.actor, "zh"), /^你下 b1/);
  const ray = captureLineText(choice.capture_lines, "O", item.actor, "zh");
  assert.match(ray, /e1 已经有一颗对手的棋子。对手再下 a1/);
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
  assert.match(text, /After b1, the opponent plays e1 first; whatever you reply, it then plays a1, using e1 to trap b1, c1, d1/);
  assert.doesNotMatch(text, /Step \d/);
  assert.doesNotMatch(text, /position still favors|局面仍偏向/);
  assert.doesNotMatch(text, /only legal/);
  const opening = cases["0"].choices[0];
  assert.equal(teachingChoiceLabel(opening, "en"), "Your game move");
  assert.equal(teachingChoiceLabel(best, "zh"), "推荐走法");
  assert.equal(teachingChoiceLabel(best, "en"), "Recommended move");
});

test("an ordinary move names its flipped discs next to empty squares", () => {
  const comparison = ordinary.comparison, choice = comparison.choices[0];
  assert.deepEqual(choice.concepts.exposed, ["e5"]);
  assert.equal(choice.frames.length, 3);
  assert.equal(lessonText(comparison, choice, "zh")[1], "f5 翻过来的 e5 挨着空格，对手以后可能从旁边的空格下棋，把它翻回去。");
  for (const locale of ["en", "zh"]) {
    const text = lessonText(comparison, choice, locale).join(" ");
    assert.doesNotMatch(text, /c6|position still favors|because.*score|所以.*评分/);
  }
  const recapture = cases["47"], c6 = recapture.choices[0];
  assert.equal(c6.continuation_lesson.kind, "recapture");
  assert.equal(lessonText(recapture, c6, "zh")[1], "对手可以下 d6，借 d3 夹回 d5。");
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
      for (const choice of comparison.choices) {
        const lesson = lessonText(comparison, choice, locale);
        assert.equal(lesson.length, 3);
        const text = lesson.join(" ");
        for (const coordinate of ["b6", "e6", "b5", "c5", "f5"]) assert.ok(text.includes(coordinate));
        assert.match(text, /new reply at f5|e6 也让对手多了 f5/);
        assert.doesNotMatch(text, /fewer.*better|少.*所以.*更好|wins|必胜/);
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
    assert.doesNotMatch(text, /highest|评分/);
    assert.doesNotMatch(text, /失误|mistake|only legal/);
  }
});

test("a highest-rated historical endgame move is shown alone and remains distinct from forced", () => {
  const comparison = cases["47"];
  assert.equal(comparison.choices.length, 1);
  assert.equal(comparison.insight.kind, "best");
  assert.ok(comparison.choices[0].assessment.legal_move_count > 1);
  for (const locale of ["en", "zh"]) {
    assert.doesNotMatch(lessonText(comparison, comparison.choices[0], locale).join(" "), /only legal|唯一/);
  }
});

test("engine scores and rankings stay out of the primary teaching text", () => {
  const exact = cases["47"], estimate = cases["16"];
  for (const comparison of [exact, estimate, ordinary.comparison]) {
    for (const locale of ["en", "zh"]) {
      const text = lessonText(comparison, comparison.choices[0], locale).join(" ");
      assert.doesNotMatch(text, /rating|score|评分|分数|搜索/);
    }
  }
});

test("the corner lesson states the threat once, leaves the steps to the board, then gives the cost", () => {
  for (const key of ["earlier-h8", "earlier-h8-best"]) {
    const comparison = cases[key];
    for (const choice of comparison.choices) {
      const text = lessonText(comparison, choice, "zh");
      assert.equal(text.length, 4);
      assert.match(text[0], /？$/);
      assert.equal(text[1], "g7 之后，对手先下 f8，你怎么应对都挡不住，它接着下 h8，借 f6 夹住 g7，拿到这个角。");
      assert.match(text[2], /^换成 d7，同样应对之后，g7 是空格/);
      assert.match(text[3], /对手可以先下 c5.*a8.*仍然推荐 d7/);
      assert.ok(text.join("").length < 220);
      const english = lessonText(comparison, choice, "en").join(" ");
      assert.match(english, /whatever you reply, it then plays h8/);
      assert.doesNotMatch([...text, english].join(" "), /第 \d 步|Step \d|黑方|白方|Black|White|评分|score/);
    }
    assert.ok(otherCornerText(comparison, "zh").includes("a8"));
  }
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

test("defense feedback names the root and attempted move without requiring another alternative", () => {
  const branch = cases["16"].choices[0];
  assert.ok(branch.defense_lines.some((defense) => defense.coordinate === "g6"));
  for (const locale of ["en", "zh"]) {
    const text = defenseFeedback(branch.coordinate, "g6", branch.target, locale);
    for (const fact of ["g6", "a1", "b1"]) assert.ok(text.includes(fact));
    assert.doesNotMatch(text, /other line|另一条/);
  }
});

test("a corner defense stays focused on h8 while disclosing the independent a8 threat", () => {
  for (const comparison of [cases['earlier-h8'], cases['earlier-h8-best']]) {
    const better = comparison.choices.find((choice) => choice.coordinate === 'd7');
    assert.equal(better.kind, 'corner_defense');
    assert.equal(better.target, 'h8');
    assert.equal(better.frames.length, 4);
    assert.deepEqual(better.frames.slice(1).map((frame) => frame.coordinate), comparison.insight.example);
    for (const locale of ['en', 'zh']) {
      const text = lessonText(comparison, better, locale).join(' ');
      for (const coordinate of ['g7', 'd7', 'h8', 'a8', 'f8', 'c5']) assert.ok(text.includes(coordinate));
      assert.match(text, /can play c5.*a8|先下 c5.*a8/);
    }
  }
});

test('corner lessons name the capture line and the move that sets it up', () => {
  for (const comparison of Object.values(cases)) {
    const witness = comparison.insight.witness;
    if (!witness) continue;
    const choice = comparison.choices.find((move) => move.coordinate === witness.opportunity.available_after);
    for (const locale of ['en', 'zh']) {
      const text = lessonText(comparison, choice, locale).join(' ');
      for (const square of witness.opportunity.capture_line) assert.ok(text.includes(square));
      if (witness.prefix[0] && witness.prefix[0] !== 'pass') assert.ok(text.includes(witness.prefix[0]));
    }
  }
});
