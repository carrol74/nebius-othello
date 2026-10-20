import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../lib/review-text.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022}}).outputText;
const {factText, positionFactText} = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const {review} = JSON.parse(readFileSync(new URL("../../backend/tests/fixtures/review-native-positions.json", import.meta.url), "utf8"));

test("saved exact scores use the correct player perspective", () => {
  const text = factText({id:"p47:score",revision:47,text:"",topic:"comparison"}, review, "zh");
  assert.match(text, /白方视角/);
  assert.match(text, /剩余空格计入胜方/);
  assert.match(text, /实际棋子数量/);
});

test("saved pass facts translate without inventing a score", () => {
  const text = factText({id:"p30:pass",revision:30,text:"",topic:"pass"}, review, "zh");
  assert.match(text, /黑方没有合法落点/);
  assert.doesNotMatch(text, /评分/);
});

test("Chinese answers use the backend decision status for tied moves", () => {
  const cases = JSON.parse(readFileSync(new URL("../../backend/tests/fixtures/teaching-native-cases.json", import.meta.url), "utf8"));
  const opening = review.evidence.find((item) => item.revision === 0);
  const text = positionFactText({id:"p0:decision", revision:0, text:"",topic:"comparison"}, opening, "zh", cases["0"].choices[0].assessment);
  assert.match(text, /并列最高评分/);
  assert.doesNotMatch(text, /引擎推荐/);
});

test("single-move Chinese score facts never repeat the move as its own comparison", () => {
  const cases = JSON.parse(readFileSync(new URL("../../backend/tests/fixtures/teaching-native-cases.json", import.meta.url), "utf8"));
  for (const revision of [0, 47]) {
    const item = review.evidence.find((item) => item.revision === revision);
    const entry = {...item, recommended_move:item.actual_move, score_loss:0};
    for (const kind of ["score", "endgame"]) {
      const text = positionFactText({id:`p${revision}:${kind}`,revision,text:"",topic:"comparison"}, entry, "zh", cases[String(revision)].choices[0].assessment);
      assert.equal(text.split(item.actual_move).length - 1, 1);
      assert.doesNotMatch(text, /相差/);
    }
  }
});
