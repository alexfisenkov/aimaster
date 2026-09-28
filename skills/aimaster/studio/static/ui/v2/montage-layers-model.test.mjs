// node --test skills/aimaster/studio/static/ui/v2/montage-layers-model.test.mjs
//
// Схема монтажа: шесть дорожек, блоки по времени, подпись по нажатию —
// чей клип, где он в ролике и какой кусок исходника взят.

import test from "node:test";
import assert from "node:assert/strict";

import {
  clipDetail, fmtLen, fmtTime, layerRows, sceneNames, volumeText,
} from "./montage-layers-model.js";
import { projectWith } from "./snapshot.fixture.mjs";

const PROJECT = projectWith({
  scenes: [
    { scene_id: "s2", order: 2, title: "Клубок" },
    { scene_id: "s1", order: 1, title: "Сад" },
  ],
});
const clip = (patch) => ({ id: "x", kind: "video", start: 0, duration: 1, media_start: 0, volume: null,
  scene_id: null, asset_id: null, text: null, ...patch });
const MODEL = {
  duration: 10,
  layers: [
    { layer: "video", label: "Видео", clips: [clip({ id: "v-1", start: 0, duration: 2.5, media_start: 0.5, volume: 0.3, scene_id: "s1" }),
                                              clip({ id: "v-2", start: 2.5, duration: 5, scene_id: "s2" })] },
    { layer: "titles", label: "Титры", clips: [clip({ id: "t-1", kind: "div", start: 0.2, duration: 1.6, text: "Барсик" })] },
    { layer: "voice", label: "Голос", clips: [clip({ id: "a-voice", kind: "audio", start: 0, duration: 5 })] },
    { layer: "music", label: "Музыка", clips: [] },
    { layer: "fx", label: "Шумы", clips: [clip({ id: "a-fx", kind: "audio", start: 9.99, duration: 0.01, volume: 0.8 })] },
    { layer: "atmos", label: "Атмосфера", clips: [clip({ id: "a-atmos", kind: "audio", start: 12, duration: 2 })] },
  ],
};

test("время и длина — как в строках montage diff", () => {
  assert.equal(fmtTime(3.25), "0:03.3");
  assert.equal(fmtTime(65), "1:05.0");
  assert.equal(fmtTime(0), "0:00.0");
  assert.equal(fmtLen(2.5), "2,5 с");
  assert.equal(volumeText(0.3), "30 %");
  assert.equal(volumeText(null), "100 %");
});

test("сцены называются по порядку, а не по месту в списке", () => {
  assert.deepEqual(sceneNames(PROJECT), {
    s1: { number: 1, text: "сцена 1 «Сад»" },
    s2: { number: 2, text: "сцена 2 «Клубок»" },
  });
});

test("шесть дорожек в постоянном порядке, блоки — доли длины ролика", () => {
  const rows = layerRows(MODEL, PROJECT);
  assert.deepEqual(rows.map((row) => row.label), ["Видео", "Титры", "Голос", "Музыка", "Шумы", "Атмосфера"]);
  assert.deepEqual(rows[0].blocks.map((block) => [block.id, block.at, block.len, block.text]),
    [["v-1", 0, 25, "1"], ["v-2", 25, 50, "2"]]);
  assert.deepEqual(rows[1].blocks.map((block) => block.text), ["Барсик"]);
  assert.deepEqual(rows[3].blocks, []);
});

test("короткий клип всё равно можно нажать, а вылезший за конец — виден у края", () => {
  const rows = layerRows(MODEL, PROJECT);
  assert.deepEqual([rows[4].blocks[0].at, rows[4].blocks[0].len], [98.8, 1.2]);
  assert.deepEqual([rows[5].blocks[0].at, rows[5].blocks[0].len], [98.8, 1.2]);
});

test("подпись по нажатию: клип сцены, кусок исходника, громкость", () => {
  const names = sceneNames(PROJECT);
  assert.equal(clipDetail(MODEL.layers[0].clips[0], "video", "Видео", names),
    "Клип: сцена 1 «Сад» · 0:00.0–0:02.5 ролика · из исходника с 0:00.5, 2,5 с · громкость 30 %");
  assert.equal(clipDetail(MODEL.layers[0].clips[1], "video", "Видео", names),
    "Клип: сцена 2 «Клубок» · 0:02.5–0:07.5 ролика · из исходника с 0:00.0, 5,0 с");
  assert.equal(clipDetail(MODEL.layers[1].clips[0], "titles", "Титры", names), "Титр «Барсик» · 0:00.2–0:01.8 ролика");
  assert.equal(clipDetail(MODEL.layers[2].clips[0], "voice", "Голос", names),
    "Голос · 0:00.0–0:05.0 ролика · из исходника с 0:00.0, 5,0 с · громкость 100 %");
});

test("без схемы дорожек нет; без длины ролика — она по концу последнего клипа", () => {
  assert.deepEqual(layerRows(null, PROJECT), []);
  const rows = layerRows({ duration: 0, layers: [{ layer: "video", label: "Видео", clips: [clip({ id: "v-1", start: 0, duration: 4 })] }] }, PROJECT);
  assert.deepEqual([rows[0].blocks[0].at, rows[0].blocks[0].len], [0, 100]);
});
