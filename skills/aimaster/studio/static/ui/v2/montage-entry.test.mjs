// node --test skills/aimaster/studio/static/ui/v2/montage-entry.test.mjs
//
// Что экран видит о монтаже: чей отказ главнее, свежа ли схема и давно ли
// отстала — таблицей.

import test from "node:test";
import assert from "node:assert/strict";

import { composeEntry, readEntry, staleTicksAfter } from "./montage-entry.js";
import { keyOf } from "./montage-model-tracker.js";

const S = (key, patch = {}) => ({
  applicable: true, exists: true, engine: { state: "installed" }, index_key: key, current_version: "v001", revision: 1, ...patch,
});
const K = (key, patch) => keyOf(S(key, patch));
const MODEL = { index_key: "k1", layers: [] };
const DOWN = { ok: false, code: "http_502" };
const REFUSED = { ok: false, code: "montage_refused", message: "в папке монтажа есть ссылки на другие места" };

const CASES = [
  { name: "ещё ничего нет", input: {}, error: null, modelFresh: false },
  { name: "отказ статуса главнее отказа схемы",
    input: { status: S("k1"), statusError: DOWN, modelKey: K("k1"), modelError: REFUSED }, error: DOWN },
  { name: "отказ статуса главнее и поздней удачной схемы",
    input: { status: S("k1"), statusError: DOWN, model: MODEL, shownKey: K("k1"), modelKey: K("k1") }, error: DOWN, modelFresh: true },
  { name: "отказ схемы виден на своём ключе", input: { status: S("k1"), modelKey: K("k1"), modelError: REFUSED }, error: REFUSED },
  { name: "отказ схемы не виден на чужом ключе", input: { status: S("k2"), modelKey: K("k1"), modelError: REFUSED }, error: null },
  { name: "отказ схемы не виден, пока статус неприменим",
    input: { status: S("k1", { engine: { state: "missing" } }), modelKey: K("k1"), modelError: REFUSED }, error: null },
  { name: "схема для ключа статуса — свежая", input: { status: S("k1"), model: MODEL, shownKey: K("k1") }, modelFresh: true },
  { name: "статус ушёл на другой index_key — не свежая", input: { status: S("k2"), model: MODEL, shownKey: K("k1") }, modelFresh: false },
  { name: "собрали новую версию — не свежая",
    input: { status: S("k1", { current_version: "v002" }), model: MODEL, shownKey: K("k1") }, modelFresh: false },
  { name: "статус неприменим — не свежая",
    input: { status: S("k1", { engine: { state: "missing" } }), model: MODEL, shownKey: K("k1") }, modelFresh: false },
  { name: "схемы нет — не свежая", input: { status: S("k1"), shownKey: K("k1") }, modelFresh: false },
  { name: "отстала на один опрос — пометки нет",
    input: { status: S("k2"), model: MODEL, shownKey: K("k1"), staleTicks: 1 }, modelFresh: false, modelLagging: false },
  { name: "отстала дольше одного опроса — «обновляется…»",
    input: { status: S("k2"), model: MODEL, shownKey: K("k1"), staleTicks: 2 }, modelFresh: false, modelLagging: true },
  { name: "свежая схема не «обновляется», какой бы ни был счёт",
    input: { status: S("k1"), model: MODEL, shownKey: K("k1"), staleTicks: 5 }, modelFresh: true, modelLagging: false },
  { name: "схемы нет — и пометки нет", input: { status: S("k1"), staleTicks: 5 }, modelLagging: false },
];

for (const { name, input, ...expected } of CASES) {
  test(`entry: ${name}`, () => {
    const entry = composeEntry(input);
    assert.deepEqual(Object.keys(entry), ["status", "model", "error", "modelFresh", "modelLagging"]);
    assert.equal(entry.status, input.status ?? null);
    assert.equal(entry.model, input.model ?? null);
    if ("error" in expected) assert.deepEqual(entry.error, expected.error);
    if ("modelFresh" in expected) assert.equal(entry.modelFresh, expected.modelFresh);
    if ("modelLagging" in expected) assert.equal(entry.modelLagging, expected.modelLagging);
  });
}

test("счёт отставшей схемы: растёт только с опросом статуса, свежая или никакая — ноль", () => {
  const stale = { model: MODEL, modelFresh: false };
  assert.equal(staleTicksAfter(0, stale, true), 1);
  assert.equal(staleTicksAfter(1, stale, true), 2);
  assert.equal(staleTicksAfter(2, stale, false), 2); // ответ схемы, всё ещё не свежей, — не опрос
  assert.equal(staleTicksAfter(3, { model: MODEL, modelFresh: true }, true), 0);
  assert.equal(staleTicksAfter(3, { model: null, modelFresh: false }, true), 0);
});

test("экран читает entry: плашкам и длине — только свежая схема, рисунку слоёв — и отставшая", () => {
  const status = S("k2");
  const stale = readEntry(composeEntry({ status, model: MODEL, shownKey: K("k1"), staleTicks: 2 }));
  assert.deepEqual(stale, { status, model: null, schema: MODEL, lagging: true, error: null });
  const fresh = readEntry(composeEntry({ status: S("k1"), model: MODEL, shownKey: K("k1") }));
  assert.equal(fresh.model, MODEL);
  assert.equal(fresh.lagging, false);
  const photo = readEntry(composeEntry({ status: { applicable: false }, statusError: null }));
  assert.equal(photo.status, null);
  assert.deepEqual(readEntry(null), { status: null, model: null, schema: null, lagging: false, error: null });
  assert.deepEqual(readEntry(composeEntry({ status, statusError: DOWN })).error, DOWN);
});
