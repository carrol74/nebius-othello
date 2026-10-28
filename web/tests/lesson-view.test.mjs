import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../lib/lesson-view.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.ESNext}}).outputText;
const {answerMatchesView, teachingView, sameTeachingView, lessonFocus, reasonView, canonicalFrames, coachedFrames, displayedTeachingView} = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const cases = JSON.parse(readFileSync(new URL("../../backend/tests/fixtures/teaching-native-cases.json", import.meta.url), "utf8"));

test("an answer stays visible through its demonstration but not an unrelated line or a new answer", () => {
  const [played, alternative] = cases["16"].choices;
  const asked = teachingView(played.coordinate, played.frames, 1);
  assert.equal(answerMatchesView(asked, asked, "question-1", undefined), true);
  for (let frame = 1; frame < alternative.frames.length; frame++) {
    const shown = teachingView(alternative.coordinate, alternative.frames, frame);
    assert.equal(answerMatchesView(asked, shown, "question-1", "question-1"), true);
    assert.equal(answerMatchesView(asked, shown, "question-1", undefined), false);
    assert.equal(answerMatchesView(asked, shown, "question-2", "question-1"), false);
  }
  assert.equal(answerMatchesView(null, asked, undefined, undefined), false);
});

test("a cited tool line supplies the exact displayed frames", () => {
  const comparison = cases["16"];
  const choice = comparison.choices[0];
  const frames = choice.frames.slice(0, 3);
  const lesson = {revision:16, comparison, coaching:[{facts:[{id:"t1", frames}]}]};
  assert.equal(coachedFrames(lesson, choice), frames);
  const focus = lessonFocus(lesson);
  assert.equal(focus.choice.frames, frames);
  assert.equal(focus.frame, 2);
  assert.equal(canonicalFrames(choice, frames), false);
  assert.equal(canonicalFrames(choice, structuredClone(choice.frames)), true);
  assert.deepEqual(displayedTeachingView(choice, {lesson_frames:frames, frame:2}).line, ["b1", "e1"]);
});

test("a verified comparison opens at its causal step and retains its board highlights", () => {
  const comparison = cases["16"];
  const choice = comparison.choices.find(move => move.coordinate === comparison.reason.move);
  const lesson = {comparison, coaching:[{facts:[{id:comparison.reason.fact, frames:choice.frames}]}]};
  const focus = lessonFocus(lesson);
  assert.equal(focus.frame, comparison.reason.frame);
  assert.equal(canonicalFrames(choice, focus.choice.frames), true);
  assert.deepEqual(reasonView(comparison, focus.choice).ray.squares, comparison.reason.marks[choice.coordinate]);
});

test("question and continuation requests follow every visible board, including a different first move", () => {
  const {practice} = JSON.parse(readFileSync(new URL("../../backend/tests/fixtures/corner-practice-native.json", import.meta.url), "utf8"));
  const original = cases["16"].choices[0];
  for (const option of practice.options) {
    for (let frame = 1; frame < option.frames.length; frame++) {
      const view = displayedTeachingView(original, {lesson_frames:option.frames, frame});
      assert.equal(view.selected_move, option.coordinate);
      assert.deepEqual(view.line, option.frames.slice(1, frame + 1).map(step => step.coordinate));
      assert.equal(view.line.at(-1), option.frames[frame].coordinate);
    }
  }
  assert.deepEqual(displayedTeachingView(original, {lesson_frames:[original.frames[0]], frame:0}).line, []);
});

test("question context follows the selected move and frame", () => {
  const [actual, alternative] = cases["16"].choices;
  const first = teachingView(actual.coordinate, actual.frames, 1);
  const root = teachingView(actual.coordinate, actual.frames, 0);
  assert.deepEqual(root.line, []);
  assert.equal(sameTeachingView(first, root), false);
  const reply = teachingView(actual.coordinate, actual.frames, 2);
  assert.deepEqual(reply.line, ["b1", "e1"]);
  assert.equal(sameTeachingView(first, reply), false);
  assert.equal(sameTeachingView(null, reply), false);
  assert.equal(sameTeachingView(reply, {...reply, line: [...reply.line]}), true);
  assert.equal(sameTeachingView(reply, teachingView(alternative.coordinate, alternative.frames, 2)), false);
});

test("without a demonstrated line, the board opens on the move that shows the primary reason", () => {
  for (const comparison of Object.values(cases)) {
    const focus = lessonFocus({revision: comparison.revision, comparison, coaching: []});
    if (!comparison.reason) {
      assert.equal(focus, null);
      continue;
    }
    assert.equal(focus.choice.coordinate, comparison.reason.move);
    assert.equal(focus.frame, Math.min(comparison.reason.frame, focus.choice.frames.length - 1));
  }
});

test("reply consequences compare both boards after the same opponent response", () => {
  const {comparison} = JSON.parse(readFileSync(new URL("../../backend/tests/fixtures/reply-consequence-native.json", import.meta.url), "utf8"));
  const focus = lessonFocus({comparison, coaching: []});
  assert.equal(focus.choice.coordinate, "d3");
  assert.equal(focus.frame, 2);
  for (const choice of comparison.choices) {
    const view = reasonView(comparison, choice);
    assert.equal(view.key_frame, 2);
    assert.equal(choice.frames[view.key_frame].coordinate, "f4");
    assert.deepEqual(displayedTeachingView(choice, {lesson_frames: choice.frames, frame: 2}).line, [choice.coordinate, "f4"]);
  }
});

test("corner comparisons highlight the same capture line at the same step on both boards", () => {
  for (const comparison of Object.values(cases)) {
    const witness = comparison.insight.witness;
    if (!witness) continue;
    for (const choice of comparison.choices) {
      const shown = reasonView(comparison, choice);
      assert.equal(shown.key_frame, witness.prefix.length + 1);
      assert.deepEqual(shown.ray.squares, witness.opportunity.capture_line);
      assert.deepEqual(choice.frames.slice(2, shown.key_frame + 1).map((frame) => frame.coordinate), witness.prefix);
    }
  }
});

test("the key step is where the primary reason shows on the board", () => {
  const g7 = cases["earlier-h8"].choices.find((choice) => choice.coordinate === "g7");
  assert.equal(reasonView(cases["earlier-h8"], g7).key_frame, 3);
  assert.deepEqual(reasonView(cases["47"], cases["47"].choices[0]), {key_frame: 2, ray: {frame: 2, squares: ["d6", "d5", "d4", "d3"]}});
  const b1 = cases["16"].choices.find((choice) => choice.coordinate === "b1");
  assert.equal(b1.kind, "corner_forced");
  assert.equal(reasonView(cases["16"], b1).key_frame, 2);
  for (const choice of cases["2"].choices) assert.deepEqual(reasonView(cases["2"], choice).ray, {frame: 1, squares: ["b5", "c5", "d5"]});
  assert.equal(reasonView(cases["0"], cases["0"].choices[0]), null);
  assert.equal(reasonView(cases["22"], cases["22"].choices[0]), null);
});
