// node --test skills/aimaster/studio/static/ui/v2/viewer-canvas.test.mjs
//
// Плёнка вариантов, переключатель слотов и подпись под холстом. У живой
// фикстуры кадров у сцен нет вовсе (сцены оживают по референсам), поэтому
// слот «первый кадр» здесь досыпан к её копии через `projectWith`.

import test from "node:test";
import assert from "node:assert/strict";

import { canvasCaption, filmstrip, ownFileStrip, promptOfVariant, slotOptions } from "./viewer-canvas.js";
import { variantCounts } from "./counts.js";
import { directActionsFor } from "./decide.js";
import { PROJECT, VIEW_STAGE, projectWith } from "./snapshot.fixture.mjs";

const GROUP = "result:frame:cafe-open:first";
const PROMPT_V2 = "prompt:frame:cafe-open:first-v2";

function frame(number, extra = {}) {
  return {
    result_id: GROUP,
    version_id: `${GROUP}-v${number}`,
    parent_version_id: number === 1 ? null : `${GROUP}-v${number - 1}`,
    asset_url: `/assets/frame-${number}`,
    status: "ready",
    ...extra,
  };
}

const WITH_FRAMES = projectWith({
  scenes: PROJECT.scenes.map((scene) => (scene.scene_id === "cafe-open"
    ? {
      ...scene,
      need_first: true,
      need_last: true,
      links: { ...scene.links, first_frame_result_id: `${GROUP}-v3` },
    }
    : scene)),
  positions: [
    ...PROJECT.positions,
    {
      kind: "first_frame",
      position_id: "pos:frame:cafe-open:first",
      prompt_group_id: "prompt:frame:cafe-open:first",
      result_group_id: GROUP,
      scene_id: "cafe-open",
      stage: "image_results",
      status: "ready",
    },
  ],
  image_results: [
    ...PROJECT.image_results,
    frame(1, { decision: "rejected" }),
    frame(2, { decision: "approved" }),
    frame(3, { links: { prompt_version_ids: [PROMPT_V2] } }),
    frame(4, { hidden: true }),
  ],
});

const counts = variantCounts(WITH_FRAMES, { sceneId: "cafe-open", slot: "first" });

test("плёнка: порядок цепочки, пометки и номер выбранного", () => {
  const strip = filmstrip(counts);
  assert.equal(strip.total, 4);
  assert.equal(strip.selectedIndex, 3);
  assert.deepEqual(strip.items.map((item) => item.mark), ["отклонён", "принят", "выбран", "скрыт"]);
  assert.deepEqual(strip.items.map((item) => item.dim), [true, false, false, true]);
  assert.deepEqual(strip.items.map((item) => item.index), [1, 2, 3, 4]);
});

test("«выбран» — только тот, на который указывает ссылка сцены", () => {
  const approvedElsewhere = filmstrip(counts).items[1];
  assert.equal(approvedElsewhere.version.decision, "approved");
  assert.equal(approvedElsewhere.state, "approved", "одобренный, но не выбранный — не «выбран»");
});

test("плёнка пустого места", () => {
  const strip = filmstrip(variantCounts(WITH_FRAMES, { sceneId: "cafe-open", slot: "last" }));
  assert.deepEqual(strip, { items: [], selectedIndex: 0, total: 0 });
});

test("слоты: только те, что есть или нужны по плану кадров", () => {
  const scene = WITH_FRAMES.scenes.find((item) => item.scene_id === "cafe-open");
  assert.deepEqual(slotOptions(WITH_FRAMES, scene), [
    { slot: "first", total: 4, label: "Первый кадр · 4 варианта" },
    { slot: "last", total: 0, label: "Последний кадр · нет" },
  ]);
  const plain = PROJECT.scenes.find((item) => item.scene_id === "cafe-open");
  assert.deepEqual(slotOptions(PROJECT, plain), [], "сцене без кадров переключать нечего");
});

test("слова «вариант» склоняются", () => {
  const withCount = (total) => slotOptions(
    projectWith({
      scenes: [{ scene_id: "s", order: 1, need_first: true, links: {} }],
      positions: [{ kind: "first_frame", position_id: "pos:frame:s:first", result_group_id: "g", scene_id: "s" }],
      image_results: Array.from({ length: total }, (_, at) => ({
        result_id: "g", version_id: `g-v${at + 1}`, parent_version_id: at ? `g-v${at}` : null,
      })),
    }),
    { scene_id: "s", need_first: true },
  )[0].label;
  assert.equal(withCount(1), "Первый кадр · 1 вариант");
  assert.equal(withCount(3), "Первый кадр · 3 варианта");
  assert.equal(withCount(5), "Первый кадр · 5 вариантов");
  assert.equal(withCount(11), "Первый кадр · 11 вариантов");
});

test("подпись под холстом", () => {
  assert.equal(
    canvasCaption({ index: 3, total: 4, mark: "выбран", promptLabel: "v2" }),
    "Вариант 3 из 4 · выбран · по промпту v2",
  );
  assert.equal(
    canvasCaption({ index: 1, total: 2, mark: "новый" }),
    "Вариант 1 из 2 · новый",
    "без связи промпт→результат хвоста «по промпту» нет",
  );
  assert.equal(canvasCaption({ index: 1, total: 0 }), "Вариантов пока нет");
});

test("связь варианта с версией промпта читается только из данных", () => {
  const versions = [{ version_id: "prompt:frame:cafe-open:first-v1" }, { version_id: PROMPT_V2 }];
  const strip = filmstrip(counts);
  assert.equal(promptOfVariant(strip.items[2].version, versions)?.version_id, PROMPT_V2);
  assert.equal(promptOfVariant(strip.items[0].version, versions), null);
});

test("плёнка референса берётся из image_results, а не из клипов", () => {
  const strip = filmstrip(variantCounts(PROJECT, { referenceId: "IMG_04" }));
  assert.equal(strip.total, 1, "у референса есть свой вариант, и он должен попасть на плёнку");
  assert.equal(strip.items[0].version.result_id, "result:ref:IMG_04");
  assert.equal(strip.items[0].mark, "выбран");
});

test("загруженный референс показывает свой файл, а не пустоту", () => {
  const upload = PROJECT.references.find((item) => item.reference_id === "IMG_01");
  assert.equal(upload.source, "upload");
  assert.equal(filmstrip(variantCounts(PROJECT, { referenceId: "IMG_01" })).total, 0);
  const strip = ownFileStrip(upload.asset_url, upload.label);
  assert.equal(strip.total, 1);
  assert.equal(strip.items[0].mark, "ваш файл");
  assert.equal(strip.items[0].version.asset_url, upload.asset_url);
  assert.equal(strip.items[0].version.version_id, undefined, "версии у своего файла нет");
  assert.equal(ownFileStrip(null), null);
});

test("по плитке «ваш файл» решать нечего", () => {
  const upload = PROJECT.references.find((item) => item.reference_id === "IMG_01");
  const strip = ownFileStrip(upload.asset_url, upload.label);
  assert.deepEqual(
    directActionsFor({
      allowedActions: VIEW_STAGE.allowed_actions,
      currentStage: "image_results",
      collection: "image_results",
      version: strip.items[0].version,
    }),
    [],
  );
});
