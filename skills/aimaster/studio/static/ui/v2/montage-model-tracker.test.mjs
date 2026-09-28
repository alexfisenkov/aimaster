// node --test skills/aimaster/studio/static/ui/v2/montage-model-tracker.test.mjs
//
// Когда спрашивать схему слоёв — таблицей: шаги «статус → решение» и
// «ответ схемы → решение», в конце — чей ключ, что летит, какой отказ.
// Схема летит одна; новый ключ спрашивают, как только летящая легла.

import test from "node:test";
import assert from "node:assert/strict";

import {
  MODEL_RETRY_TICKS, applicable, createModelTracker, keyOf, modelFailed, sameKey,
} from "./montage-model-tracker.js";

const S = (key, patch = {}) => ({
  applicable: true, exists: true, engine: { state: "installed" }, index_key: key, current_version: "v001", revision: 1, ...patch,
});
const OK = (key) => ({ ok: true, body: { index_key: key } });
const BROKEN = (key) => ({ ok: true, body: { index_key: key, model_error: "HyperFrames «timeline --json» завершился с кодом 1" } });
const REFUSED = { ok: false, code: "montage_refused", message: "в папке монтажа есть ссылки на другие места" };
const K = (key) => keyOf(S(key));
const repeat = (count, step) => Array.from({ length: count }, () => step);
const failing = [["result", K("k1"), BROKEN("k1"), "idle"]];

const CASES = [
  { name: "первый применимый статус — спросить", steps: [["status", S("k1"), "start"]], flight: "k1", key: null },
  { name: "тот же ключ после удачи — не спрашивать",
    steps: [["status", S("k1"), "start"], ["result", K("k1"), OK("k1"), "idle"], ["status", S("k1"), "idle"]],
    flight: null, key: "k1" },
  { name: "пока схема летит — второй не шлём, и для нового ключа тоже",
    steps: [["status", S("k1"), "start"], ["status", S("k1"), "keep"], ["status", S("k2"), "keep"]], flight: "k1" },
  { name: "легла, а статус ушёл — сразу спросить последний ключ",
    steps: [["status", S("k1"), "start"], ["status", S("k2"), "keep"], ["status", S("k3"), "keep"],
      ["result", K("k1"), OK("k1"), "start"]], flight: "k3", key: "k1" },
  { name: "легла с отказом, а статус ушёл — тоже сразу следующий ключ",
    steps: [["status", S("k1"), "start"], ["status", S("k2"), "keep"], ["result", K("k1"), REFUSED, "start"]],
    flight: "k2", key: "k1", error: REFUSED },
  { name: "сменилась current_version при том же index_key — это новый ключ",
    steps: [["status", S("k1"), "start"], ["result", K("k1"), OK("k1"), "idle"],
      ["status", S("k1", { current_version: "v002" }), "start"]], flight: "k1" },
  { name: "сменилась revision — это новый ключ",
    steps: [["status", S("k1"), "start"], ["result", K("k1"), OK("k1"), "idle"], ["status", S("k1", { revision: 2 }), "start"]],
    flight: "k1" },
  { name: "статус неприменим — не спрашивать, отказ схемы снят",
    steps: [["status", S("k1"), "start"], ["result", K("k1"), REFUSED, "idle"],
      ["status", S("k1", { engine: { state: "missing" } }), "idle"]], flight: null, key: "k1", error: null },
  { name: "легла, пока статус неприменим, — следующую не спрашивать",
    steps: [["status", S("k1"), "start"], ["status", { applicable: false }, "keep"], ["result", K("k1"), OK("k1"), "idle"]],
    flight: null, key: "k1" },
  { name: "отказ запроса держится для своего ключа, удача его снимает",
    steps: [["status", S("k1"), "start"], ["result", K("k1"), REFUSED, "idle"]], key: "k1", error: REFUSED },
  { name: `провал схемы — пауза ${MODEL_RETRY_TICKS.join(", ")} тиков, дальше без роста`,
    steps: [["status", S("k1"), "start"], ...failing,
      ["status", S("k1"), "start"], ...failing,
      ...repeat(5, ["status", S("k1"), "idle"]), ["status", S("k1"), "start"], ...failing,
      ...repeat(11, ["status", S("k1"), "idle"]), ["status", S("k1"), "start"], ...failing,
      ...repeat(11, ["status", S("k1"), "idle"]), ["status", S("k1"), "start"]], flight: "k1" },
  { name: "схема ожила после провала — больше не спрашивать",
    steps: [["status", S("k1"), "start"], ...failing, ["status", S("k1"), "start"], ["result", K("k1"), OK("k1"), "idle"],
      ["status", S("k1"), "idle"]], flight: null },
  { name: "вернулись к ключу с провалом, пока летит другой, — переспросить сразу, как ляжет",
    steps: [["status", S("k1"), "start"], ...failing, ["status", S("k2"), "start"], ["status", S("k1"), "keep"],
      ["result", K("k2"), OK("k2"), "start"]], flight: "k1", key: "k2" },
];

for (const { name, steps, ...expected } of CASES) {
  test(`трекер схемы: ${name}`, () => {
    const tracker = createModelTracker();
    steps.forEach(([kind, ...args], index) => {
      const decision = args.pop();
      const actual = kind === "status" ? tracker.onStatus(...args) : tracker.onResult(...args);
      assert.equal(actual, decision, `шаг ${index + 1} (${kind})`);
    });
    if ("flight" in expected) assert.equal(tracker.flight?.index_key ?? null, expected.flight);
    if ("key" in expected) assert.equal(tracker.key?.index_key ?? null, expected.key);
    if ("error" in expected) assert.deepEqual(tracker.error, expected.error);
  });
}

test("трекер схемы: reset — с чистого листа", () => {
  const tracker = createModelTracker();
  tracker.onStatus(S("k1"));
  tracker.onResult(K("k1"), REFUSED);
  tracker.onStatus(S("k2"));
  tracker.reset();
  assert.deepEqual([tracker.key, tracker.error, tracker.flight, tracker.latest], [null, null, null, null]);
  assert.equal(tracker.onStatus(S("k1")), "start");
});

test("applicable, modelFailed, sameKey — таблицей", () => {
  for (const [body, expected] of [
    [S("k1"), true], [S("k1", { engine: { state: "missing" } }), false], [S(null, { exists: false }), false],
    [{ applicable: false }, false], [null, false],
  ]) assert.equal(applicable(body), expected, JSON.stringify(body));
  for (const [body, expected] of [
    [{ index_key: "k1" }, false], [{ model_error: "код 1" }, true], [{ stale_error: "нет файла" }, true], [null, true],
  ]) assert.equal(modelFailed(body), expected, JSON.stringify(body));
  for (const [a, b, expected] of [
    [K("k1"), K("k1"), true], [K("k1"), K("k2"), false], [K("k1"), keyOf(S("k1", { current_version: "v002" })), false],
    [K("k1"), keyOf(S("k1", { revision: 2 })), false], [null, K("k1"), false], [null, null, false],
  ]) assert.equal(sameKey(a, b), expected);
});
