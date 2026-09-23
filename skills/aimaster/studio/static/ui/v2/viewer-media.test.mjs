// node --test skills/aimaster/studio/static/ui/v2/viewer-media.test.mjs
//
// Тип файла — по общему правилу `preview.previewKind`; где файла нет —
// заглушка с подписью.

import test from "node:test";
import assert from "node:assert/strict";

import { PLACEHOLDER_TEXT, mediaPlan } from "./viewer-media.js";

test("клип по месту — `<video>` с якорем первого кадра, а не `<img>`", () => {
  assert.deepEqual(mediaPlan({ asset_url: "/assets/asset-1" }, "video"), {
    tag: "video", src: "/assets/asset-1#t=0.1", kind: "video", placeholder: "",
  });
});

test("запись сильнее места: тип из `media_type`, расширения и `kind: video`", () => {
  assert.equal(mediaPlan({ asset_url: "/assets/a", media_type: "video" }, "image").tag, "video");
  assert.equal(mediaPlan({ asset_url: "/assets/a.mp3" }, "image").tag, "audio");
  assert.equal(mediaPlan({ asset_url: "/assets/a", kind: "video" }, "image").tag, "video");
});

test("картинка и звук по месту — своими тегами", () => {
  assert.equal(mediaPlan({ asset_url: "/assets/a" }, "image").tag, "img");
  assert.equal(mediaPlan({ asset_url: "/assets/a" }).tag, "img", "по умолчанию — картинка");
  assert.equal(mediaPlan({ asset_url: "/assets/a" }, "audio").tag, "audio");
});

test("нет файла или чужой адрес — заглушка с подписью по месту", () => {
  assert.deepEqual(mediaPlan(null, "video"), {
    tag: null, src: "", kind: "video", placeholder: PLACEHOLDER_TEXT.missing.video,
  });
  assert.equal(mediaPlan({ asset_url: "" }, "image").placeholder, "Картинки пока нет");
  assert.equal(mediaPlan({ asset_url: "https://example.com/x.png" }, "image").tag, null, "только свои /assets/");
  assert.equal(mediaPlan({}, "audio").placeholder, "Звука пока нет");
});
