// node --test skills/aimaster/studio/static/ui/v2/status-tone.test.mjs

import test from "node:test";
import assert from "node:assert/strict";

import { clipBadge, framesBadge, statusTone } from "./status-tone.js";
import { waveHeights } from "./audio-model.js";

test("цвет статуса идёт по тем же правилам, что и слова", () => {
  assert.equal(statusTone({ total: 0, selected: null }), "none");
  assert.equal(statusTone({ total: 3, selected: null }), "warn");
  assert.equal(statusTone({ total: 3, selected: { version_id: "v" } }), "ok");
  assert.equal(statusTone({ total: 0 }, { source: "upload", hasAsset: true }), "own");
  assert.equal(statusTone({ total: 2 }, { source: "upload", hasAsset: false }), "none");
  assert.equal(statusTone(), "none");
});

test("бейдж кадров: готово, только когда выбраны все запланированные слоты", () => {
  assert.equal(framesBadge([]), null);
  assert.deepEqual(framesBadge([{ selected: {} }, { selected: {} }]), { text: "кадры готовы", tone: "ok" });
  assert.deepEqual(framesBadge([{ selected: {} }, { selected: null, total: 2 }]), { text: "нужно выбрать", tone: "warn" });
});

test("бейдж клипа: выбран, нужно выбрать, клипа нет", () => {
  assert.equal(clipBadge({ total: 2, selected: {} }).text, "клип выбран");
  assert.equal(clipBadge({ total: 2, selected: null }).text, "нужно выбрать");
  assert.equal(clipBadge({ total: 0, selected: null }).text, "клипа нет");
});

test("волна слоя не меняется от перерисовки и у пустого слоя плоская", () => {
  assert.deepEqual(waveHeights(1, true), waveHeights(1, true));
  assert.equal(waveHeights(0, true).length, 28);
  assert.ok(waveHeights(0, true).every((value) => value > 0 && value <= 1));
  assert.ok(waveHeights(2, false).every((value) => value === 0.08));
});
