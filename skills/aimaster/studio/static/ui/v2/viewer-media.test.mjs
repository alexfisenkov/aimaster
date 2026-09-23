// node --test skills/aimaster/studio/static/ui/v2/viewer-media.test.mjs
//
// Где файл есть — превью по виду материала; где нет — заглушка с подписью.

import test from "node:test";
import assert from "node:assert/strict";

import { PLACEHOLDER_TEXT, mediaPlan } from "./viewer-media.js";

test("клип — `<video>` с якорем первого кадра, а не `<img>`", () => {
  assert.deepEqual(mediaPlan("/assets/asset-1", "video"), {
    tag: "video", src: "/assets/asset-1#t=0.1", kind: "video", placeholder: "",
  });
});

test("картинка и звук — своими тегами", () => {
  assert.equal(mediaPlan("/assets/asset-1", "image").tag, "img");
  assert.equal(mediaPlan("/assets/asset-1").tag, "img", "вид по умолчанию — картинка");
  assert.equal(mediaPlan("/assets/asset-1", "audio").tag, "audio");
});

test("нет файла или чужой адрес — заглушка с подписью по виду", () => {
  assert.deepEqual(mediaPlan(null, "video"), {
    tag: null, src: "", kind: "video", placeholder: PLACEHOLDER_TEXT.missing.video,
  });
  assert.equal(mediaPlan("", "image").placeholder, "Картинки пока нет");
  assert.equal(mediaPlan("https://example.com/x.png", "image").tag, null, "только свои /assets/");
  assert.equal(mediaPlan(undefined, "audio").placeholder, "Звука пока нет");
});
