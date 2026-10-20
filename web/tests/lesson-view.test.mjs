import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../lib/lesson-view.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.ESNext}}).outputText;
const {teachingView, sameTeachingView, coachFocus} = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const cases = JSON.parse(readFileSync(new URL("../../backend/tests/fixtures/teaching-native-cases.json", import.meta.url), "utf8"));

test("question context follows the selected move, frame and defense attempt", () => {
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
  const defense = actual.defense_lines.find((line) => line.coordinate === "g6");
  const attempted = teachingView(actual.coordinate, defense.frames, 4);
  assert.deepEqual(attempted.line, ["b1", "e1", "g6", "a1"]);
  assert.equal(sameTeachingView(attempted, teachingView(actual.coordinate, actual.frames, 4)), false);
});

test("coach focus uses a verified canonical continuation and ignores unavailable moves", () => {
  const comparison = cases["2"];
  const choice = comparison.choices.find((move) => move.continuation_lesson);
  const lesson = {revision: comparison.revision, comparison, coaching: [{facts: [
    {id: `p${comparison.revision}:continuation_${choice.coordinate}`},
  ]}]};
  const focus = coachFocus(lesson);
  assert.equal(focus.choice, choice);
  assert.equal(focus.frame, choice.continuation_lesson.frame_index - 1);
  assert.equal(focus.choice.frames[focus.frame + 1].coordinate, choice.continuation_lesson.capture_line[0]);
  assert.equal(coachFocus({...lesson, coaching: []}), null);
  assert.equal(coachFocus({...lesson, coaching: [{facts: [{id: "p2:continuation_a1"}]}]}), null);
});
