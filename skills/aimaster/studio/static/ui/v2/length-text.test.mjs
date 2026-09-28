// node --test skills/aimaster/studio/static/ui/v2/length-text.test.mjs
//
// Длина ролика: шапка и пилюля превью говорят одно и то же число.

import test from "node:test";
import assert from "node:assert/strict";

import { lengthClock, lengthWords, sceneSeconds } from "./length-text.js";

const CASES = [
  [3.5, "00:03,5", "3,5 с"],
  [3, "00:03", "3 с"],
  [3.04, "00:03", "3 с"],
  [9.94, "00:09,9", "9,9 с"],
  [9.96, "00:10", "10 с"],
  [14.6, "00:15", "15 с"],
  [35.4, "00:35", "35 с"],
  [65, "01:05", "65 с"],
  [0, "00:00", "0 с"],
];

for (const [seconds, clock, words] of CASES) {
  test(`длина ${seconds} с — «${clock}» и «${words}»`, () => {
    assert.equal(lengthClock(seconds), clock);
    assert.equal(lengthWords(seconds), words);
  });
}

test("не число — пустая строка; длина по сценам — конец последней", () => {
  assert.equal(lengthClock(null), "");
  assert.equal(lengthWords(Number.NaN), "");
  assert.equal(sceneSeconds({ scenes: [{ end_ms: 2000 }, { end_ms: 3500 }] }), 3.5);
  assert.equal(sceneSeconds({ scenes: [] }), null);
  assert.equal(sceneSeconds(null), null);
});
