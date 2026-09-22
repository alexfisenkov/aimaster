// node --test skills/aimaster/studio/static/ui/v2/variants.test.mjs
//
// Фикстура — живой snapshot владельца (snapshot.fixture.mjs), поэтому
// проверки ниже сверяются с тем же, что показывает дашборд v1.

import test from "node:test";
import assert from "node:assert/strict";

import {
  orderByParent,
  promptGroups,
  resultGroups,
  selectedResultVersion,
  variantState,
  versionsMadeBy,
} from "./variants.js";
import { PROJECT, projectWith } from "./snapshot.fixture.mjs";

const ids = (records) => records.map((item) => item.version_id);

test("фикстура — тот самый проект: шесть сцен и восемь референсов", () => {
  assert.equal(PROJECT.id, "dashboard-dialogue");
  assert.equal(PROJECT.scenes.length, 6);
  assert.equal(PROJECT.references.length, 8);
  assert.equal(PROJECT.gen_mode, "per_scene");
  assert.equal(PROJECT.stage, "motion");
});

test("orderByParent: корень первый, за ним цепочка", () => {
  const chain = [
    { version_id: "c", parent_version_id: "b" },
    { version_id: "a", parent_version_id: null },
    { version_id: "b", parent_version_id: "a" },
  ];
  assert.deepEqual(ids(orderByParent(chain)), ["a", "b", "c"]);
});

test("orderByParent: сироты уходят в конец в порядке появления", () => {
  const records = [
    { version_id: "orphan-1", parent_version_id: "missing" },
    { version_id: "a", parent_version_id: null },
    { version_id: "orphan-2", parent_version_id: "also-missing" },
    { version_id: "b", parent_version_id: "a" },
  ];
  assert.deepEqual(ids(orderByParent(records)), ["a", "b", "orphan-1", "orphan-2"]);
});

test("orderByParent: цикл не вешает обход", () => {
  const records = [
    { version_id: "x", parent_version_id: "y" },
    { version_id: "y", parent_version_id: "x" },
  ];
  assert.deepEqual(ids(orderByParent(records)), ["x", "y"]);
});

test("orderByParent: пустой и мусорный ввод — пустой список", () => {
  assert.deepEqual(orderByParent(null), []);
  assert.deepEqual(orderByParent([null, 7, "нет"]), []);
});

test("promptGroups: у промпта движения сцены «Кафе» три версии подряд", () => {
  const groups = promptGroups(PROJECT.motion_prompts);
  const cafe = groups.get("prompt:scene:alex-convenience:video");
  assert.deepEqual(ids(cafe), [
    "prompt:scene:alex-convenience:video-v1",
    "prompt:scene:alex-convenience:video-v2",
    "prompt:scene:alex-convenience:video-v3",
  ]);
});

test("promptGroups: у локации «Британское кафе» две версии промпта", () => {
  const groups = promptGroups(PROJECT.image_prompts);
  assert.deepEqual(ids(groups.get("prompt:ref:IMG_03")), [
    "prompt:ref:IMG_03-v1",
    "prompt:ref:IMG_03-v2",
  ]);
});

test("resultGroups: каждая группа результатов — отдельная запись", () => {
  const groups = resultGroups(PROJECT.video_results);
  assert.equal(groups.size, 4);
  assert.deepEqual(ids(groups.get("result:scene:cafe-open:video")), [
    "result:scene:cafe-open:video-v1",
  ]);
});

test("selectedResultVersion: клип сцены 1 — тот, на который указывает ссылка сцены", () => {
  const selected = selectedResultVersion(PROJECT, { sceneId: "cafe-open", slot: "video" });
  assert.equal(selected.version_id, "result:scene:cafe-open:video-v1");
  assert.equal(selected.version_id, PROJECT.scenes[0].links.video_result_id);
});

test("selectedResultVersion: у сцены без клипа выбора нет", () => {
  assert.equal(selectedResultVersion(PROJECT, { sceneId: "free-reveal", slot: "video" }), null);
});

test("selectedResultVersion: референс «Британское кафе» — по своей ссылке", () => {
  const selected = selectedResultVersion(PROJECT, { referenceId: "IMG_03" });
  assert.equal(selected.version_id, "result:ref:IMG_03-v1");
  assert.equal(selected.decision, "approved");
});

test("selectedResultVersion: у загруженного персонажа результата нет", () => {
  assert.equal(selectedResultVersion(PROJECT, { referenceId: "IMG_01" }), null);
});

test("selectedResultVersion: слоты кадров этого проекта пусты", () => {
  for (const slot of ["first", "last"]) {
    assert.equal(selectedResultVersion(PROJECT, { sceneId: "cafe-open", slot }), null);
  }
});

test("selectedResultVersion: «одним заходом» читает ссылку oneshot", () => {
  const project = projectWith({
    oneshot: { links: { video_result_id: "result:scene:cafe-open:video-v1" } },
  });
  const selected = selectedResultVersion(project, { sceneId: "oneshot" });
  assert.equal(selected.version_id, "result:scene:cafe-open:video-v1");
});

test("selectedResultVersion: чужой проект и пустой ввод не роняют", () => {
  assert.equal(selectedResultVersion(null, { sceneId: "cafe-open", slot: "video" }), null);
  assert.equal(selectedResultVersion(PROJECT, { sceneId: "нет-такой", slot: "video" }), null);
});

test("variantState: решение и флаги в правильном порядке", () => {
  assert.equal(variantState({ decision: "approved" }), "selected");
  assert.equal(variantState({ decision: "rejected" }), "rejected");
  assert.equal(variantState({}), "new");
  assert.equal(variantState({ decision: "approved", hidden: true }), "hidden");
  assert.equal(variantState({ decision: "approved", hidden: true, retired: true }), "retired");
  assert.equal(variantState(null), "new");
});

test("variantState: принятые референсы проекта помечены как выбранные", () => {
  for (const result of PROJECT.image_results) {
    assert.equal(variantState(result), "selected");
  }
});

test("versionsMadeBy: в живом snapshot связи промпт→результат нет", () => {
  assert.deepEqual(versionsMadeBy("prompt:scene:cafe-open:video-v2", PROJECT.video_results), []);
});

test("versionsMadeBy: явная ссылка на версию промпта находится", () => {
  const results = [
    { version_id: "r1", links: { image_prompt_version_id: "p-v2" } },
    { version_id: "r2", prompt_version_ids: ["p-v1", "p-v2"] },
    { version_id: "r3", parent_version_id: "p-v2" },
  ];
  assert.deepEqual(versionsMadeBy("p-v2", results).map((item) => item.version_id), ["r1", "r2"]);
  assert.deepEqual(versionsMadeBy("", results), []);
});
