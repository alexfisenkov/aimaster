// node --test skills/aimaster/studio/static/ui/v2/viewer-prompt.test.mjs
//
// Где просмотрщик берёт промпт места, какая версия считается открытой,
// как разбирается текст на теги и что пишется в мете.

import test from "node:test";
import assert from "node:assert/strict";

import { promptMeta, promptPlace, promptVersions, splitTags } from "./viewer-prompt.js";
import { PROJECT, projectWith } from "./snapshot.fixture.mjs";

test("сцена, вкладка «Видео» — промпт движения этой сцены", () => {
  const place = promptPlace(PROJECT, { kind: "scene", id: "alex-convenience" }, { tab: "video" });
  assert.deepEqual(place, {
    collection: "motion_prompts",
    groupId: "prompt:scene:alex-convenience:video",
    activeId: "prompt:scene:alex-convenience:video-v3",
  });
  const state = promptVersions(PROJECT, place);
  assert.equal(state.total, 3);
  assert.equal(state.index, 3);
  assert.equal(state.active.version_id, "prompt:scene:alex-convenience:video-v3");
});

test("референс — свой промпт из image_prompts", () => {
  const place = promptPlace(PROJECT, { kind: "reference", id: "IMG_04" });
  assert.equal(place.collection, "image_prompts");
  assert.equal(place.groupId, "prompt:ref:IMG_04");
  const state = promptVersions(PROJECT, place);
  assert.equal(state.total, 2);
  assert.equal(state.index, 2, "без ссылки открыта последняя версия цепочки");
  assert.equal(state.active.version_id, "prompt:ref:IMG_04-v2");
});

test("ссылка владельца сильнее порядка цепочки", () => {
  const linked = projectWith({
    references: PROJECT.references.map((item) => (item.reference_id === "IMG_04"
      ? { ...item, links: { image_prompt_version_id: "prompt:ref:IMG_04-v1" } }
      : item)),
  });
  const state = promptVersions(linked, promptPlace(linked, { kind: "reference", id: "IMG_04" }));
  assert.equal(state.index, 1);
  assert.equal(state.active.version_id, "prompt:ref:IMG_04-v1");
});

test("сцена, вкладка «Кадры» — промпт слота, а не движения", () => {
  const place = promptPlace(PROJECT, { kind: "scene", id: "cafe-open" }, { tab: "frames", slot: "first" });
  assert.equal(place.collection, "image_prompts");
  assert.equal(place.groupId, null, "у этой сцены кадрового места нет");
  assert.deepEqual(promptVersions(PROJECT, place), { versions: [], index: 0, active: null, total: 0 });
});

test("сборка одним заходом — общий промпт проекта", () => {
  const oneshot = projectWith({
    gen_mode: "one_shot",
    oneshot: { links: { motion_prompt_version_id: "prompt:scene:cafe-open:video-v1" } },
    positions: [
      ...PROJECT.positions,
      { kind: "oneshot", position_id: "pos:oneshot", prompt_group_id: "prompt:scene:cafe-open:video" },
    ],
  });
  const place = promptPlace(oneshot, { kind: "assembly", id: "oneshot" });
  assert.equal(place.collection, "motion_prompts");
  assert.equal(promptVersions(oneshot, place).index, 1);
});

test("теги разбираются, а не исполняются", () => {
  assert.deepEqual(splitTags("кадр: @IMG_01 и @VID_02 рядом"), [
    { text: "кадр: ", tag: false },
    { text: "@IMG_01", tag: true },
    { text: " и ", tag: false },
    { text: "@VID_02", tag: true },
    { text: " рядом", tag: false },
  ]);
  assert.deepEqual(splitTags("@VOICE_10"), [{ text: "@VOICE_10", tag: true }]);
  assert.deepEqual(splitTags("<b>не разметка</b>"), [{ text: "<b>не разметка</b>", tag: false }]);
  assert.deepEqual(splitTags(""), []);
  assert.deepEqual(splitTags(undefined), []);
});

test("мета версии: номер, статус, устарел", () => {
  assert.equal(promptMeta({ status: "approved" }, 2), "v2 · одобрен");
  assert.equal(promptMeta({ status: "pending", stale: true }, 3), "v3 · черновик · устарел");
  assert.equal(promptMeta({ status: "что-то своё" }, 1), "v1", "неизвестный статус не показывается сырым");
  assert.equal(promptMeta(null, 0), "промпта пока нет");
});
