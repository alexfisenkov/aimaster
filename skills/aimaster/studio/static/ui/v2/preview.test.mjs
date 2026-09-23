// node --test skills/aimaster/studio/static/ui/v2/preview.test.mjs

import test from "node:test";
import assert from "node:assert/strict";

import { assetUrlOf, previewKind } from "./preview.js";

test("нет своего файла — заглушка, а не битая картинка", () => {
  assert.equal(previewKind(null), "none");
  assert.equal(previewKind({ asset_url: null }), "none");
  assert.equal(previewKind({ asset_url: "" }), "none");
  assert.equal(previewKind({ asset_url: "https://example.com/a.png" }), "none");
  assert.equal(assetUrlOf({ asset_url: "/static/x.png" }), null);
});

test("тип берётся из media_type, mime, расширения, вида референса и места", () => {
  assert.equal(previewKind({ asset_url: "/assets/asset-1", media_type: "video" }), "video");
  assert.equal(previewKind({ asset_url: "/assets/asset-1", mime: "audio/mpeg" }), "audio");
  assert.equal(previewKind({ asset_url: "/assets/clip.MP4" }), "video");
  assert.equal(previewKind({ asset_url: "/assets/voice.m4a?x=1" }), "audio");
  assert.equal(previewKind({ asset_url: "/assets/still.webp" }), "image");
  assert.equal(previewKind({ asset_url: "/assets/asset-1", kind: "video" }), "video");
  assert.equal(previewKind({ asset_url: "/assets/asset-1" }, { fallback: "video" }), "video");
  assert.equal(previewKind({ asset_url: "/assets/asset-1" }), "image");
});

test("видеореференс владельца (VID_01) — видео, картинка персонажа — картинка", () => {
  assert.equal(previewKind({ asset_url: "/assets/asset-66cb", kind: "video", media_type: "video" }), "video");
  assert.equal(previewKind({ asset_url: "/assets/asset-8833", kind: "character", media_type: null }), "image");
});
