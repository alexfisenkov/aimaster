// node --test skills/aimaster/studio/static/ui/v2/screens.test.mjs
//
// Модели экранов Сценарий / Видео / Звук на живой фикстуре: что именно
// человек увидит по этим данным. Только чистые функции — DOM здесь нет.

import test from "node:test";
import assert from "node:assert/strict";

import { audioTiles, AUDIO_LAYERS } from "./audio-model.js";
import { scriptVersions, storyboardRows, activeBlockText } from "./scenario-model.js";
import { clipStatus, continuationLine } from "./video-model.js";
import { PROJECT, projectWith } from "./snapshot.fixture.mjs";

const sceneBy = (project, id) => project.scenes.find((scene) => scene.scene_id === id);

test("версии сценария идут по цепочке, активная — третья", () => {
  const { versions, activeIndex } = scriptVersions(PROJECT);
  assert.deepEqual(versions.map((item) => item.version_id), ["script-v1", "script-v2", "script-v3"]);
  assert.equal(activeIndex, 2);
});

test("без сценария листать нечего", () => {
  const { versions, activeIndex } = scriptVersions(projectWith({ script: {} }));
  assert.deepEqual(versions, []);
  assert.equal(activeIndex, 0);
});

test("раскадровка — номер, название, время и текст активной версии блока", () => {
  const rows = storyboardRows(PROJECT);
  assert.equal(rows.length, 6);
  assert.equal(rows[0].position, 1);
  assert.equal(rows[0].title, "Столик и идея");
  assert.equal(rows[0].startMs, 0);
  assert.equal(rows[0].endMs, 5000);
  assert.equal(rows[0].text, activeBlockText(sceneBy(PROJECT, "cafe-open")));
  assert.match(rows[0].text, /британском кафе/);
});

test("у сцены с выбранным клипом — «клип выбран», у пустой — «клипов пока нет»", () => {
  assert.equal(clipStatus(PROJECT, sceneBy(PROJECT, "cafe-open")).text, "клип выбран");
  const empty = clipStatus(PROJECT, sceneBy(PROJECT, "free-reveal"));
  assert.equal(empty.total, 0);
  assert.equal(empty.text, "клипов пока нет");
});

test("варианты есть, а выбора нет — «выберите из N»", () => {
  const project = structuredClone(PROJECT);
  const scene = sceneBy(project, "cafe-open");
  delete scene.links.video_result_id;
  project.video_results.push({
    result_id: "result:scene:cafe-open:video",
    version_id: "result:scene:cafe-open:video-v2",
    parent_version_id: "result:scene:cafe-open:video-v1",
    scene_id: "cafe-open",
    status: "ready",
  });
  const status = clipStatus(project, scene);
  assert.equal(status.total, 2);
  assert.equal(status.text, "выберите из 2");
});

test("выбран не первый из нескольких — номер виден", () => {
  const project = structuredClone(PROJECT);
  const scene = sceneBy(project, "cafe-open");
  project.video_results.push({
    result_id: "result:scene:cafe-open:video",
    version_id: "result:scene:cafe-open:video-v2",
    parent_version_id: "result:scene:cafe-open:video-v1",
    scene_id: "cafe-open",
    status: "ready",
  });
  scene.links.video_result_id = "result:scene:cafe-open:video-v2";
  assert.equal(clipStatus(project, scene).text, "клип выбран · 2 из 2");
});

test("видеореференс usage=continue читается как продолжение предыдущей сцены", () => {
  assert.deepEqual(
    continuationLine(PROJECT, sceneBy(PROJECT, "skeptic-online")),
    { text: "Продолжение: с конца сцены 1", warn: false },
  );
  assert.deepEqual(
    continuationLine(PROJECT, sceneBy(PROJECT, "money-question")),
    { text: "Продолжение: с конца сцены 3", warn: false },
  );
});

test("без продолжения подпись берётся из video_mode", () => {
  assert.equal(continuationLine(PROJECT, sceneBy(PROJECT, "cafe-open")).text,
    "Отдельный клип по референсам и промпту");
  const project = structuredClone(PROJECT);
  const scene = sceneBy(project, "cafe-open");
  scene.video_mode = "firstlast";
  assert.equal(continuationLine(project, scene).text, "От первого кадра к последнему");
  scene.video_mode = "first";
  assert.equal(continuationLine(project, scene).text, "Оживляем первый кадр");
  scene.video_mode = undefined;
  assert.equal(continuationLine(project, scene).text, "Способ оживления пока не выбран");
});

test("правленая сцена просит перепроверить связь", () => {
  const project = structuredClone(PROJECT);
  const scene = sceneBy(project, "skeptic-online");
  scene.linkage_status = "review_linkage";
  assert.equal(continuationLine(project, scene).warn, true);
});

test("четыре слоя звука идут по-человечески: голос, музыка, эффекты, атмосфера", () => {
  assert.deepEqual(AUDIO_LAYERS.map((item) => item.layer), ["voice", "music", "fx", "atmos"]);
  const tiles = audioTiles(PROJECT);
  assert.deepEqual(tiles.map((item) => item.name), ["Голос", "Музыка", "Эффекты", "Атмосфера"]);
  assert.deepEqual(tiles.map((item) => item.status), Array(4).fill("слой пока пустой"));
  assert.deepEqual(tiles.map((item) => item.hasPrompt), Array(4).fill(false));
});

test("у слоя с вариантами виден выбор и число вариантов", () => {
  const project = projectWith({
    audio_layers: [{ layer: "music", links: { audio_prompt_version_id: "p1", audio_result_id: "audio:music-v2" } }],
    audio_prompts: [{ prompt_id: "prompt:audio:music", version_id: "p1", parent_version_id: null, text: "джаз" }],
    audio_results: [
      { result_id: "result:audio:music", version_id: "audio:music-v1", parent_version_id: null, status: "ready" },
      { result_id: "result:audio:music", version_id: "audio:music-v2", parent_version_id: "audio:music-v1", status: "ready" },
    ],
  });
  project.positions.push({
    position_id: "pos:audio:music",
    kind: "audio",
    layer: "music",
    stage: "audio",
    status: "ready",
    prompt_group_id: "prompt:audio:music",
    result_group_id: "result:audio:music",
    required: true,
  });
  const music = audioTiles(project).find((item) => item.layer === "music");
  assert.equal(music.total, 2);
  assert.equal(music.index, 2);
  assert.equal(music.status, "выбран 2 из 2");
  assert.equal(music.hasPrompt, true);
});
