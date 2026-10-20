import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import ts from "typescript";

const source = readFileSync(new URL("../lib/earlier-decision.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.ESNext}}).outputText;
const {earlierDecisionText} = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const cases = JSON.parse(readFileSync(new URL("../../backend/tests/fixtures/earlier-decisions-native.json", import.meta.url), "utf8")).cases;

test("earlier-choice explanations use game move numbers and bound the corner defense", () => {
  for (const entry of cases) {
    const link = entry.result.link;
    for (const locale of ["en", "zh"]) {
      const text = earlierDecisionText(link, entry.move_number, locale);
      for (const value of [String(entry.move_number), link.recorded_move, link.recommended_move, link.target]) assert.ok(text.includes(value));
      assert.match(text, /next two turns|两次行动/);
      assert.match(text, /recorded continuation|实际续着/);
      assert.match(text, /not a prediction|不能推断/);
      assert.doesNotMatch(text, /guarantee|必胜|第 42/);
      if (locale === "zh") assert.doesNotMatch(text, /Black|White|At move/);
    }
  }
});
