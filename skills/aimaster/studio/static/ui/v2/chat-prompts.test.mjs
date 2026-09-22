// node --test skills/aimaster/studio/static/ui/v2/chat-prompts.test.mjs
//
// Главное требование спецификации §6: агент должен понять по одному
// тексту, что именно открывать и с чем работать — проект, сцена, версия
// промпта и выбранный вариант названы точными идентификаторами.

import test from "node:test";
import assert from "node:assert/strict";

import {
  addReference,
  editPrompt,
  moreVariants,
  projectRef,
  sceneRef,
  toggleSceneReference,
  uploadFrame,
} from "./chat-prompts.js";
import { PROJECT, REVISION } from "./snapshot.fixture.mjs";

const ALL = [
  addReference("character", PROJECT, REVISION),
  addReference("other", PROJECT, REVISION),
  addReference("video", PROJECT, REVISION),
  moreVariants({
    project: PROJECT,
    revision: REVISION,
    sceneId: "cafe-open",
    slot: "video",
    promptVersion: PROJECT.motion_prompts.find((item) => item.version_id === "prompt:scene:cafe-open:video-v2"),
    selectedVariant: PROJECT.video_results[0],
  }),
  uploadFrame({ project: PROJECT, revision: REVISION, sceneId: "skeptic-online", slot: "first" }),
  editPrompt({ project: PROJECT, revision: REVISION, sceneId: "cafe-open", promptVersion: PROJECT.motion_prompts[0] }),
  toggleSceneReference({
    project: PROJECT,
    revision: REVISION,
    sceneId: "cafe-open",
    reference: PROJECT.references[0],
    include: false,
  }),
];

test("любой промпт начинается с «Открой проект …» и называет id", () => {
  for (const item of ALL) {
    assert.match(item.prompt, /^Открой проект «Дашборд для генераций — диалог»/, item.title);
    assert.match(item.prompt, /project_id «dashboard-dialogue»/);
    assert.match(item.prompt, /snapshot revision 62/);
    assert.ok(item.title && item.title.length < 60, item.title);
  }
});

test("никакого служебного жаргона в текстах для человека", () => {
  for (const item of ALL) {
    assert.doesNotMatch(item.title, /позиц|linkage|stage|snapshot/i, item.title);
  }
});

test("projectRef и sceneRef дают именно то, что видит человек", () => {
  assert.equal(
    projectRef(PROJECT, REVISION),
    "проект «Дашборд для генераций — диалог» (project_id «dashboard-dialogue», snapshot revision 62)",
  );
  assert.equal(sceneRef(PROJECT, "skeptic-online"), "сцена 2 «Скептик» (scene_id «skeptic-online»)");
  assert.equal(sceneRef(PROJECT, "нет-такой"), "");
  assert.equal(projectRef(PROJECT), "проект «Дашборд для генераций — диалог» (project_id «dashboard-dialogue»)");
});

test("добавление референса: вид назван, генерация не разрешена заранее", () => {
  const other = addReference("other", PROJECT, REVISION);
  assert.match(other.title, /без категории/);
  assert.match(other.prompt, /kind «other»/);
  assert.match(other.prompt, /провайдера не вызывай/);
  assert.match(other.attachmentHint, /прикрепите изображение/);
});

test("видеореференс — только из файла, со спросом назначения", () => {
  const video = addReference("video", PROJECT, REVISION);
  assert.match(video.prompt, /только из файла/);
  assert.match(video.prompt, /reference, motion, continue или edit/);
  assert.match(video.attachmentHint, /Прикрепите видео/);
});

test("референс «только этой сцены» называет сцену", () => {
  const local = addReference("other", PROJECT, REVISION, { sceneId: "cafe-open" });
  assert.match(local.prompt, /сцена 1 «Столик и идея»/);
  assert.match(local.prompt, /референсы только этой сцены/);
});

test("неизвестный вид не превращается в пустое место", () => {
  assert.match(addReference("нет-такого", PROJECT).title, /Добавить референс/);
});

test("«ещё вариант» несёт версию промпта, выбранный вариант и запрет на самоволку", () => {
  const item = moreVariants({
    project: PROJECT,
    revision: REVISION,
    sceneId: "cafe-open",
    slot: "video",
    promptVersion: PROJECT.motion_prompts.find((p) => p.version_id === "prompt:scene:cafe-open:video-v2"),
    selectedVariant: PROJECT.video_results[0],
  });
  assert.match(item.prompt, /сцена 1 «Столик и идея»/);
  assert.match(item.prompt, /version_id «prompt:scene:cafe-open:video-v2»/);
  assert.match(item.prompt, /result_id «result:scene:cafe-open:video»/);
  assert.match(item.prompt, /version_id «result:scene:cafe-open:video-v1»/);
  assert.match(item.prompt, /дождись моего подтверждения — это платное действие/);
});

test("«ещё вариант» честно говорит, когда выбранного варианта нет", () => {
  const item = moreVariants({ project: PROJECT, referenceId: "IMG_03" });
  assert.match(item.prompt, /Выбранного варианта пока нет/);
  assert.match(item.prompt, /версии промпта нет/);
});

test("загрузка файла запрещает генерацию и просит вложение", () => {
  const item = uploadFrame({ project: PROJECT, revision: REVISION, sceneId: "cafe-open", slot: "last" });
  assert.match(item.title, /последний кадр/);
  assert.match(item.prompt, /Ничего не генерируй/);
  assert.match(item.attachmentHint, /Прикрепите файл/);
});

test("правка промпта сначала показывает текст, потом пишет", () => {
  const item = editPrompt({
    project: PROJECT,
    revision: REVISION,
    referenceId: "IMG_03",
    promptVersion: PROJECT.image_prompts.find((p) => p.version_id === "prompt:ref:IMG_03-v2"),
  });
  assert.match(item.prompt, /референса «IMG_03»/);
  assert.match(item.prompt, /version_id «prompt:ref:IMG_03-v2»/);
  assert.match(item.prompt, /Генерацию не запускай/);
});

test("галочка референса в сцене — ровно одна галочка", () => {
  const off = toggleSceneReference({
    project: PROJECT,
    revision: REVISION,
    sceneId: "cafe-open",
    reference: PROJECT.references[0],
    include: false,
  });
  assert.match(off.title, /^Убрать «Александр/);
  assert.match(off.prompt, /Выключи референс «Александр — основной персонаж»/);
  assert.match(off.prompt, /reference_id «IMG_01»/);
  assert.match(off.prompt, /других сцен и промптов не трогай/);

  const on = toggleSceneReference({ project: PROJECT, sceneId: "cafe-open", reference: PROJECT.references[1] });
  assert.match(on.title, /^Добавить «Артём/);
  assert.match(on.prompt, /Включи референс/);
});

test("пустой ввод не роняет и не подсовывает undefined", () => {
  for (const item of [moreVariants(), uploadFrame(), editPrompt(), toggleSceneReference(), addReference()]) {
    assert.ok(typeof item.prompt === "string" && item.prompt.length > 20);
    assert.doesNotMatch(item.prompt, /undefined|null/);
  }
});
