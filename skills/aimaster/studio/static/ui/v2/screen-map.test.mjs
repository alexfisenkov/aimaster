// node --test skills/aimaster/studio/static/ui/v2/screen-map.test.mjs

import test from "node:test";
import assert from "node:assert/strict";

import {
  SCREENS,
  pathState,
  primaryAction,
  projectFinished,
  projectStatus,
  screenForStage,
  screenHeading,
  screensFor,
  stagesForScreen,
} from "./screen-map.js";
import { unresolvedEntries, unresolvedItems } from "./unresolved.js";
import { PROJECT, projectWith } from "./snapshot.fixture.mjs";

test("пять экранов в порядке спецификации", () => {
  assert.deepEqual([...SCREENS], ["scenario", "frames", "video", "audio", "assembly"]);
});

test("обе стадии изображений живут на экране «Кадры»", () => {
  assert.equal(screenForStage("image_plan"), "frames");
  assert.equal(screenForStage("image_results"), "frames");
  assert.deepEqual(stagesForScreen("frames"), ["image_plan", "image_results"]);
});

test("остальные стадии — один в один", () => {
  assert.equal(screenForStage("scenario"), "scenario");
  assert.equal(screenForStage("motion"), "video");
  assert.equal(screenForStage("audio"), "audio");
  assert.equal(screenForStage("assembly"), "assembly");
  assert.equal(screenForStage("нет-такой"), null);
});

test("у фотопроекта нет ни видео, ни звука", () => {
  assert.deepEqual(screensFor("photo"), ["scenario", "frames", "assembly"]);
  assert.deepEqual(screensFor("video"), [...SCREENS]);
  assert.deepEqual(screensFor(undefined), [...SCREENS]);
});

test("путь живого проекта: сценарий и кадры пройдены, мы на видео", () => {
  assert.deepEqual(pathState(PROJECT), [
    { id: "scenario", label: "Сценарий", hint: "одобрен", state: "done" },
    { id: "frames", label: "Кадры", hint: "одобрен", state: "done" },
    { id: "video", label: "Видео", hint: "вы здесь", state: "current" },
    { id: "audio", label: "Звук", hint: "дальше", state: "next" },
    { id: "assembly", label: "Сборка", hint: "", state: "next" },
  ]);
});

test("путь на первом шаге: всё остальное впереди", () => {
  const states = pathState(projectWith({ stage: "scenario" })).map((step) => step.state);
  assert.deepEqual(states, ["current", "next", "next", "next", "next"]);
});

test("путь фотопроекта короче на два шага", () => {
  const path = pathState(projectWith({ type: "photo", stage: "image_results" }));
  assert.deepEqual(path.map((step) => step.id), ["scenario", "frames", "assembly"]);
  assert.equal(path[1].state, "current");
});

test("главная кнопка живого проекта: видео → звук, и она недоступна", () => {
  const action = primaryAction(PROJECT);
  assert.equal(action.label, "Одобрить видео → Звук");
  assert.equal(action.stage, "motion");
  assert.equal(action.enabled, false);
  assert.ok(action.remaining.length > 0, "две сцены без клипа должны быть названы");
});

test("«Осталось решить» называет обе сцены без клипа", () => {
  const remaining = unresolvedItems(PROJECT, "motion");
  assert.deepEqual(remaining, [
    "Сцена 5 «Бесплатно»: клип",
    "Сцена 6 «Финальная пауза»: клип",
  ]);
});

test("кнопка включается, когда решать нечего и сервер разрешает", () => {
  const project = projectWith({
    stage: "assembly",
    stage_readiness: { stage: "assembly", can_approve: true, reason: null },
  });
  const action = primaryAction(project);
  assert.equal(action.label, "Принять ролик");
  assert.equal(action.enabled, true);
  assert.deepEqual(action.remaining, []);
});

test("серверная причина попадает в строку, когда своих находок нет", () => {
  const project = projectWith({
    stage: "assembly",
    stage_readiness: { stage: "assembly", can_approve: false, reason: "missing_final_material" },
  });
  assert.deepEqual(primaryAction(project).remaining, ["нет финального материала"]);
});

test("неизвестная причина не превращается в служебный код", () => {
  const project = projectWith({
    stage: "assembly",
    stage_readiness: { stage: "assembly", can_approve: false, reason: "что_то_новое" },
  });
  assert.deepEqual(primaryAction(project).remaining, ["проверьте материалы этого шага"]);
});

test("на «Кадрах» нерешённое — референс без выбранного варианта", () => {
  const project = projectWith({
    stage: "image_results",
    image_results: [],
    stage_readiness: { stage: "image_results", can_approve: false, reason: "unaccepted_positions" },
  });
  const action = primaryAction(project);
  assert.equal(action.label, "Одобрить кадры → Видео");
  assert.deepEqual(action.remaining, [
    "референс «Британское кафе — криминальная комедия»",
    "референс «Ручка AI Мастерская»",
  ]);
});

test("устаревший легаси-промпт загруженного референса решать не просят", () => {
  const stale = PROJECT.image_prompts.filter((prompt) => prompt.stale === true);
  assert.ok(stale.length > 0, "в фикстуре есть помеченный stale промпт");
  assert.deepEqual(stale.map((prompt) => prompt.prompt_id), ["prompt:ref:IMG_02"]);
  const positions = PROJECT.positions.map((item) => item.prompt_group_id);
  assert.ok(!positions.includes("prompt:ref:IMG_02"), "позиции у него нет");
  const remaining = unresolvedItems(projectWith({ stage: "image_results", image_results: [] }), "image_results");
  assert.ok(!remaining.some((item) => item.includes("устарел")), remaining.join(" | "));
});

test("устаревший промпт действующей позиции назван по владельцу", () => {
  const image_prompts = structuredClone(PROJECT.image_prompts).map((prompt) =>
    prompt.version_id === "prompt:ref:IMG_03-v2" ? { ...prompt, stale: true } : prompt,
  );
  const remaining = unresolvedItems(projectWith({ stage: "image_plan", image_prompts }), "image_plan");
  assert.ok(remaining.includes("промпт референса «Британское кафе — криминальная комедия» устарел"), remaining.join(" | "));
});

test("у фотопроекта кадры ведут сразу в сборку", () => {
  const project = projectWith({ type: "photo", stage: "image_results" });
  assert.equal(primaryAction(project).label, "Одобрить кадры → Сборка");
});

test("отмеченные слоты кадров без выбора попадают в список", () => {
  const scenes = structuredClone(PROJECT.scenes);
  scenes[0].need_first = true;
  scenes[0].need_last = true;
  const project = projectWith({ stage: "image_results", scenes, image_results: [] });
  const remaining = unresolvedItems(project, "image_results");
  assert.ok(remaining.includes("Сцена 1 «Столик и идея»: первый кадр"));
  assert.ok(remaining.includes("Сцена 1 «Столик и идея»: последний кадр"));
});

test("«одним заходом» спрашивает один клип на весь ролик", () => {
  const project = projectWith({ gen_mode: "one_shot", stage: "motion" });
  assert.deepEqual(unresolvedItems(project, "motion"), ["клип всего ролика"]);
});

test("пустой проект не роняет ни путь, ни кнопку", () => {
  assert.deepEqual(pathState(null).map((step) => step.state), ["next", "next", "next", "next", "next"]);
  const action = primaryAction(null);
  assert.equal(action.enabled, false);
  assert.equal(action.stage, null);
  assert.deepEqual(unresolvedItems(null), []);
});

test("пункт «осталось решить» ведёт в просмотрщик на клип сцены", () => {
  const [first] = unresolvedEntries(PROJECT, "motion");
  assert.equal(first.label, "Сцена 5 «Бесплатно»: клип");
  assert.equal(first.target.kind, "scene");
  assert.equal(typeof first.target.id, "string");
  assert.equal(first.tab, "video");
  assert.equal(first.slot, "video");
  assert.deepEqual(primaryAction(PROJECT).items.map((item) => item.label), primaryAction(PROJECT).remaining);
});

test("причина от сервера — пункт без адреса", () => {
  const project = projectWith({ stage: "assembly", stage_readiness: { can_approve: false, reason: "missing_final_material" } });
  const [item] = primaryAction(project).items;
  assert.equal(item.label, "нет финального материала");
  assert.equal(item.target, null);
});

test("статус-пилюля: янтарная с числом, зелёная когда можно и когда всё принято", () => {
  assert.deepEqual(projectStatus({ active_project: PROJECT }), { text: "Видео · осталось 2", tone: "warn", count: 2 });
  const ready = projectWith({ stage: "scenario", stage_readiness: { can_approve: true } });
  assert.equal(projectStatus({ active_project: ready }).text, "Сценарий · можно одобрять");
  const done = { active_project: projectWith({ stage: "assembly" }), view_stage: { gate_status: "approved" } };
  assert.equal(projectFinished(done), true);
  assert.deepEqual(projectStatus(done), { text: "Проект завершён", tone: "ok", count: 0 });
  assert.equal(projectStatus({}), null);
});

test("заголовок экрана: номер шага и отметка об одобрении", () => {
  assert.deepEqual(screenHeading(PROJECT, "frames"), {
    kicker: "Шаг 2 из 5 · одобрен",
    title: "Кадры",
    hint: "Кто и что в кадре: референсы, промпты и картинки сцен.",
  });
  assert.equal(screenHeading(PROJECT, "video").kicker, "Шаг 3 из 5");
  assert.equal(screenHeading(projectWith({ type: "photo", stage: "image_results" }), "assembly").kicker, "Шаг 3 из 3");
});
