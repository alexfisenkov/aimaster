// node --test skills/aimaster/studio/static/ui/v2/viewer-zones.test.mjs
//
// «Где используется» у референса и «Из чего собран» у сборки: только то,
// что есть в snapshot, и тем же правилом включённости, что строка сцены.

import test from "node:test";
import assert from "node:assert/strict";

import { assemblyParts, whereUsed } from "./viewer-zones.js";
import { PROJECT, projectWith } from "./snapshot.fixture.mjs";

test("общий референс — во всех сценах, где он в `reference_ids`", () => {
  const used = whereUsed(PROJECT, "IMG_01").map((item) => item.sceneId);
  const expected = [...PROJECT.scenes]
    .sort((left, right) => (left.order || 0) - (right.order || 0))
    .filter((scene) => (scene.links?.reference_ids || []).includes("IMG_01"))
    .map((scene) => scene.scene_id);
  assert.ok(expected.length > 0);
  assert.deepEqual(used, expected);
  assert.match(whereUsed(PROJECT, "IMG_01")[0].label, /^Сцена 1 · /);
});

test("«только здесь» и видеореференс — в своей сцене, даже без `reference_ids`", () => {
  const local = PROJECT.references.find((item) => item.local === true && item.kind !== "video");
  assert.ok(local, "в фикстуре есть референс «только здесь»");
  assert.deepEqual(whereUsed(PROJECT, local.reference_id).map((item) => item.sceneId), [local.scene_id]);
  const video = PROJECT.references.find((item) => item.kind === "video");
  assert.deepEqual(whereUsed(PROJECT, video.reference_id).map((item) => item.sceneId), [video.scene_id]);
});

test("выключенный из всех сцен и неизвестный референс — пусто", () => {
  const off = projectWith({
    scenes: PROJECT.scenes.map((scene) => ({
      ...scene,
      links: { ...scene.links, reference_ids: (scene.links?.reference_ids || []).filter((id) => id !== "IMG_03") },
    })),
  });
  assert.deepEqual(whereUsed(off, "IMG_03"), []);
  assert.deepEqual(whereUsed(PROJECT, "IMG_99"), []);
  assert.deepEqual(whereUsed(null, "IMG_01"), []);
});

test("из чего собран — только сцены с выбранным клипом, по порядку", () => {
  const parts = assemblyParts(PROJECT);
  const withClip = [...PROJECT.scenes]
    .sort((left, right) => (left.order || 0) - (right.order || 0))
    .filter((scene) => typeof scene.links?.video_result_id === "string")
    .map((scene) => scene.scene_id);
  assert.deepEqual(parts.map((item) => item.target.id), withClip);
  assert.ok(parts.every((item) => item.tab === "video" && item.label.startsWith("Клип · Сцена ")));
});

test("без выбранных клипов и звука перечислять нечего", () => {
  const bare = projectWith({
    scenes: PROJECT.scenes.map((scene) => ({ ...scene, links: { ...scene.links, video_result_id: undefined } })),
  });
  assert.deepEqual(assemblyParts(bare), []);
  assert.deepEqual(assemblyParts(null), []);
});
