// node --test skills/aimaster/studio/static/ui/v2/screen-prompts.test.mjs
//
// Промпты экрана «Сборка» по канону монтажа (references/montage.md): сборка
// бесплатная и локальная — агент собирает сразу, без плана и подтверждения;
// установка — командой из montage status, путей в тексте нет.

import test from "node:test";
import assert from "node:assert/strict";

import {
  ASSEMBLE_LABEL, assembleFinal, assembleLabel, installMontage, updateMontageClips,
} from "./screen-prompts.js";
import { projectWith } from "./snapshot.fixture.mjs";

const VIDEO = projectWith({ type: "video" });
const PHOTO = projectWith({ type: "photo" });
const PATHS = /\/Users\/|[A-Za-z]:\\|\/home\//;

test("«Собрать ролик → чат» — одна надпись; у фото — «Собрать → чат»", () => {
  assert.equal(ASSEMBLE_LABEL, "Собрать ролик → чат");
  assert.equal(assembleLabel(VIDEO), "Собрать ролик → чат");
  assert.equal(assembleLabel(projectWith({ type: "mixed" })), "Собрать ролик → чат");
  assert.equal(assembleLabel(PHOTO), "Собрать → чат");
});

test("сборка видео: diff и пересказ, затем сразу render --by owner, без подтверждения", () => {
  const { title, prompt } = assembleFinal(VIDEO, 62);
  assert.equal(title, "Собрать ролик");
  assert.match(prompt, /project_id «dashboard-dialogue»/);
  assert.match(prompt, /snapshot revision 62/);
  assert.match(prompt, /references\/montage\.md/);
  assert.match(prompt, /montage diff/);
  assert.match(prompt, /montage render --by owner/);
  assert.match(prompt, /бесплатная, подтверждения не нужно/);
  assert.match(prompt, /копию не собирай/);
  assert.doesNotMatch(prompt, /платное действие|дождись моего подтверждения/);
});

test("нет черновика — тот же промпт велит сделать его montage draft", () => {
  assert.match(assembleFinal(VIDEO, 1).prompt, /нет черновика — сделай его \(montage draft\)/);
});

test("фото-проект собирается принятой картинкой, без монтажа", () => {
  const { title, prompt } = assembleFinal(PHOTO, 3);
  assert.equal(title, "Собрать итог");
  assert.match(prompt, /assembly set/);
  assert.doesNotMatch(prompt, /montage/);
});

test("«Установить → чат» — команда из montage status, без путей", () => {
  const { title, prompt } = installMontage(VIDEO, 62);
  assert.equal(title, "Установить монтажный стол");
  assert.match(prompt, /engine\.install_argv/);
  assert.match(prompt, /бесплатный/);
  assert.doesNotMatch(prompt, PATHS);
});

test("«Обновить клипы → чат» — refresh сразу, rebuild только по слову", () => {
  const { title, prompt } = updateMontageClips(VIDEO, 62);
  assert.equal(title, "Обновить клипы в монтаже");
  assert.match(prompt, /stale_clips/);
  assert.match(prompt, /montage draft --refresh/);
  assert.match(prompt, /дождись моего ответа/);
});
