import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../lib/teaching-text.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022}}).outputText;
const {coachingFailure, reasonLabel, practiceFeedback, practicePrompt, stepText, stepNote, captureLineText, teachingChoiceLabel, teachingNote} = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const cases = JSON.parse(readFileSync(new URL("../../backend/tests/fixtures/teaching-native-cases.json", import.meta.url), "utf8"));
const forced = JSON.parse(readFileSync(new URL("../../backend/tests/fixtures/forced-move-native.json", import.meta.url), "utf8"));
const {comparison: lost} = JSON.parse(readFileSync(new URL("../../backend/tests/fixtures/lost-corner-native.json", import.meta.url), "utf8"));

test("the analysis limit note names local changes and no score", () => {
  for (const locale of ["en", "zh"]) {
    assert.match(teachingNote(locale), /verified local changes|已验证的局部变化/);
    assert.match(teachingNote(locale), /final game result|最终结果/);
    assert.doesNotMatch(teachingNote(locale), /score|评分|胜率/);
  }
});

test("demonstration steps name the move, its flips, and the capture line", () => {
  const item = cases["16"], choice = item.choices[0];
  assert.match(stepText(choice.frames[2], item.actor, "zh"), /对手下 e1，翻转 e2/);
  assert.match(stepText(choice.frames[4], item.actor, "en"), /The opponent plays a1/);
  assert.match(stepText(choice.frames[1], item.actor, "zh"), /^你下 b1/);
  const ray = captureLineText(choice.capture_lines, "O", item.actor, "zh");
  assert.match(ray, /e1 已经有一颗对手的棋子。对手再下 a1/);
  assert.match(ray, /b1、c1、d1 夹住/);
});

test("choice labels say where each move comes from", () => {
  const choice = forced.comparison.choices[0];
  assert.equal(teachingChoiceLabel(choice, "en"), "Your game move");
  assert.equal(teachingChoiceLabel(choice, "zh"), "你当时下的");
  const best = cases["16-best"].choices[0];
  assert.equal(teachingChoiceLabel(best, "zh"), "推荐走法");
  assert.equal(teachingChoiceLabel(best, "en"), "Recommended move");
  assert.equal(teachingChoiceLabel({assessment: {is_played: false, best_moves: ["d7", "e7"]}}, "zh"), "推荐走法之一");
});

test("the key step note follows the primary reason, and both compared lines get one", () => {
  const corner = cases["16"], b1 = corner.choices.find((choice) => choice.coordinate === "b1");
  const b3 = corner.choices.find((choice) => choice.coordinate === "b3");
  assert.equal(stepNote(corner, b1, 2, "zh"), "现在 a1 到 e1 这条线连上了：对手下 a1 就能夹住 b1、c1、d1。");
  assert.equal(stepNote(corner, b3, 2, "zh"), "换成 b3，a1 到 e1 这条线连不上，对手下不了 a1。");
  assert.equal(stepNote(corner, b1, 3, "zh"), "这只是你的一种应对。这时你共有 9 种下法，换成哪一种都挡不住。");
  assert.equal(stepNote(corner, b1, 4, "en"), "It uses e1 to trap b1, c1, d1 and takes the corner.");
  const h8 = cases["earlier-h8"], g7 = h8.choices.find((choice) => choice.coordinate === "g7");
  assert.equal(stepNote(h8, g7, 2, "zh"), "对手下了这一步以后，你怎么应对都挡不住它下 h8。");
  assert.equal(stepNote(cases["47"], cases["47"].choices[0], 2, "zh"), "对手借 d3 把你刚翻到的 d5 夹了回去。");
  for (const choice of cases["2"].choices) assert.match(stepNote(cases["2"], choice, 1, "zh"), /b5 到 d5 这条线/);
  assert.equal(stepNote(cases["0"], cases["0"].choices[0], 1, "zh"), null);
});

test("a corner lost before the move says so, and a corner both moves lose gets no notes", () => {
  assert.equal(lost.choices[0].defendable, false);
  assert.equal(stepNote(lost, lost.choices[0], 1, "zh"), "现在对手可以直接下 a8，借 d5 夹住 b7、c6。在这一步之前，这个角就已经保不住了。");
  for (const choice of cases["22"].choices) assert.equal(stepNote(cases["22"], choice, 1, "zh"), null);
});

test("a reply the other move blocks by taking that square says the square is occupied", () => {
  const {comparison} = JSON.parse(readFileSync(new URL("../../backend/tests/fixtures/occupied-reply-native.json", import.meta.url), "utf8"));
  const [g2, f2] = ["g2", "f2"].map((move) => comparison.choices.find((choice) => choice.coordinate === move));
  assert.match(stepNote(comparison, g2, 1, "zh"), /^现在 f2 到 a7 这条线连上了：对手下 f2 就能夹住/);
  assert.equal(stepNote(comparison, f2, 1, "zh"), "换成 f2，f2 已经有棋子，对手下不了这里。");
});

test("reply consequences explain the marked own choices after the shared response", () => {
  const {comparison} = JSON.parse(readFileSync(new URL("../../backend/tests/fixtures/reply-consequence-native.json", import.meta.url), "utf8"));
  const played = comparison.choices.find(choice => choice.coordinate === "d3");
  const alternative = comparison.choices.find(choice => choice.coordinate === "c5");
  for (const locale of ["en", "zh"]) {
    assert.match(stepNote(comparison, played, 2, locale), /全部可选的落点|all your next legal moves/);
    assert.match(stepNote(comparison, alternative, 2, locale), /e3/);
    assert.doesNotMatch(stepNote(comparison, played, 2, locale), /c3/);
    assert.equal(stepNote(comparison, played, 1, locale), null);
  }
  assert.equal(reasonLabel(comparison.reason, "zh"), "关键：给下一手保留落点");
});

test("corner practice says whether each first move blocks the corner, and how the corner falls if not", () => {
  const {practice} = JSON.parse(readFileSync(new URL("../../backend/tests/fixtures/corner-practice-native.json", import.meta.url), "utf8"));
  const option = (move) => practice.options.find((item) => item.coordinate === move);
  assert.equal(practicePrompt(practice.options, "a1", "zh"), "回到你落子之前：选一步，试着不让对手拿到左上角 a1。");
  assert.equal(practiceFeedback(option("b3"), "a1", "b3", "zh"), "挡住了：下 b3 之后，对手三步之内拿不到左上角 a1。这也是推荐走法。");
  assert.match(practiceFeedback(option("g3"), "a1", "b3", "zh"), /^挡住了：.*引擎更推荐 b3。$/);
  assert.equal(practiceFeedback(option("b1"), "a1", "b3", "zh"), "没挡住：下 b1 之后，对手先下 e1，你怎么应对都挡不住它拿左上角 a1。");
  assert.equal(practiceFeedback(option("b2"), "a1", "b3", "en"), "Not blocked: after b2, the opponent can take the top-left corner a1 right away.");
  const unsafe = practice.options.filter((item) => !item.safe);
  assert.match(practicePrompt(unsafe, "a1", "zh"), /每一步都会让对手能拿到左上角 a1/);
  const tied = {coordinate: "d7", safe: true, recommended: true, attack: null, replies: 0, frames: [], capture_lines: []};
  assert.equal(practiceFeedback(tied, "a8", "e7", "zh"), "挡住了：下 d7 之后，对手三步之内拿不到左下角 a8。引擎认为它和 e7 一样好。");
});

test("failed checks and a missing model stay quiet, while real errors keep their reason", () => {
  assert.deepEqual(coachingFailure("COACH_UNGROUNDED", "Correct these problems: ...", "lesson", "zh"),
    {quiet: true, text: "Nemotron 这次没能给出可靠的讲解。可以先在棋盘上看推演，或者再讲解一次。"});
  assert.equal(coachingFailure("COACH_ROUNDS", null, "question", "zh").text, "Nemotron 这次没能给出可靠的回答，可以换个问法再问一次。");
  assert.deepEqual(coachingFailure("REVIEW_NOT_CONFIGURED", "Token Factory is not configured for coaching", "lesson", "zh"),
    {quiet: true, text: "这个服务没有接入 Nemotron，可以在棋盘上看推演。"});
  assert.deepEqual(coachingFailure("TOKEN_FACTORY_AUTH", "Coaching authentication failed", "summary", "zh"),
    {quiet: false, text: "Coaching authentication failed"});
});

test("a failed summary allows navigation even without selected key moves", () => {
  assert.deepEqual(coachingFailure("COACH_UNGROUNDED", null, "summary", "zh"),
    {quiet: true, text: "Nemotron 这次没能写出可靠的总结。可以在棋盘上选择自己的回合，或者重新总结。"});
  assert.match(coachingFailure("REVIEW_NOT_CONFIGURED", null, "summary", "en").text, /select one of your turns/);
});

test("each move worth reviewing is labeled with its primary reason", () => {
  assert.equal(reasonLabel(cases["16"].reason, "zh"), "关键：左上角 a1");
  assert.equal(reasonLabel(cases["2"].reason, "zh"), "关键：对手的落点 b5");
  assert.equal(reasonLabel(cases["47"].reason, "en"), "Key: discs flipped straight back");
  assert.equal(reasonLabel(cases["0"].reason, "zh"), null);
});
