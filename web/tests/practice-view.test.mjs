import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import ts from "typescript";

async function load(file) {
  const source = readFileSync(new URL(file, import.meta.url), "utf8");
  const compiled = ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
  return import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
}
const {practiceFeedbackFrame, practiceSelection} = await load("../lib/practice-view.ts");
const {replyOpportunityText} = await load("../lib/teaching-text.ts");
const native = JSON.parse(readFileSync(new URL("../../backend/tests/fixtures/reply-practice-native.json", import.meta.url), "utf8"));

test("reply practice keeps both independent choices and original question until feedback", () => {
  for (const entry of native.cases) {
    const initial = {question:entry.question, move:null, alternative:null, anchor:null, reason:"", feedback:null, feedback_line:"blocking"};
    const original = JSON.stringify(initial);
    const first = practiceSelection(initial, entry.move, ".");
    assert.equal(first.move, entry.move);
    assert.equal(first.alternative, null);
    assert.equal(practiceFeedbackFrame(first), null);
    const second = practiceSelection(first, entry.alternative, ".");
    assert.equal(second.move, entry.move);
    assert.equal(second.alternative, entry.alternative);
    assert.equal(practiceSelection(second, entry.move, ".").alternative, null);
    assert.equal(JSON.stringify(initial), original);
    const answered = {...second, feedback:entry.feedback};
    assert.equal(practiceFeedbackFrame(answered), entry.feedback.blocking_frame);
    assert.equal(practiceFeedbackFrame({...answered, feedback_line:"allowing"}), entry.feedback.allowing_frame);
    assert.equal(practiceSelection(answered, entry.move, "."), answered);
    assert.deepEqual(answered.question.board, entry.question.board);
  }
});

test("reply feedback names the verified root choices and changed ray cell in both languages", () => {
  for (const entry of native.cases) {
    const witness = entry.feedback.witness;
    for (const locale of ["en", "zh"]) {
      const text = replyOpportunityText(witness, locale);
      assert.ok(text.includes(witness.available_after));
      assert.ok(text.includes(witness.blocked_after));
      assert.ok(text.includes(witness.coordinate));
      assert.ok(witness.changes.some((change) => text.includes(change.coordinate)));
      assert.doesNotMatch(text, /strongest|best move|guarantee|最优|必胜/);
      if (locale === "zh") assert.doesNotMatch(text, /Black|White|After/);
    }
  }
});
