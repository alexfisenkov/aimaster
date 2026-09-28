// node --test skills/aimaster/studio/static/ui/v2/montage-dom.test.mjs
//
// DOM-модули экрана монтажа: грузятся без браузера (ничего не трогают при
// импорте), стили — только на токенах, блоки схемы — CSS-переменные через
// CSSOM, а не атрибут style (CSP страницы его запрещает). Вид проверяет
// задача 20 в браузере.

import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

import { PROJECT } from "./snapshot.fixture.mjs";

const MODULES = Object.freeze({
  "./montage-notices.js": ["renderNotices"],
  "./montage-file.js": ["renderFileCard"],
  "./montage-desk.js": ["renderMainActions"],
  "./montage-versions.js": ["renderVersions"],
  "./montage-layers.js": ["renderLayers"],
});

test("модули экрана монтажа загружаются в node и отдают свои функции", async () => {
  for (const [path, names] of Object.entries(MODULES)) {
    const module = await import(path);
    for (const name of names) assert.equal(typeof module[name], "function", `${path}: ${name}`);
  }
});

test("стили монтажа не заводят цветов мимо токенов", () => {
  const css = fs.readFileSync(new URL("../../styles/v2/montage.css", import.meta.url), "utf8");
  const literals = (css.match(/#[0-9a-fA-F]{3,8}\b/g) || []).filter((color) => color.toLowerCase() !== "#fff");
  assert.deepEqual(literals, []);
  assert.doesNotMatch(css, /rgba?\(|hsla?\(/);
  assert.match(css, /@media \(max-width: 759px\)/);
});

test("блоки схемы ставятся переменными через CSSOM, атрибута style нет нигде", () => {
  const layers = fs.readFileSync(new URL("./montage-layers.js", import.meta.url), "utf8");
  assert.match(layers, /style\.setProperty\("--am-at"/);
  for (const path of Object.keys(MODULES)) {
    const source = fs.readFileSync(new URL(path, import.meta.url), "utf8");
    assert.doesNotMatch(source, /setAttribute\("style"|\.style\.cssText|innerHTML/, path);
  }
});

test("на экране нет абсолютных путей: путь к файлу — только готовый `file.shown` сервера", () => {
  for (const path of Object.keys(MODULES)) {
    const source = fs.readFileSync(new URL(path, import.meta.url), "utf8");
    assert.doesNotMatch(source, /\/Users\/|[A-Z]:\\\\|\/home\//, path);
  }
  const file = fs.readFileSync(new URL("./montage-file.js", import.meta.url), "utf8");
  assert.match(file, /file\?\.shown/);
});

test("экран «Сборка» и его части загружаются; строки «Финальный ролик» — прежние", async () => {
  const screen = await import("./screen-assembly.js");
  assert.equal(typeof screen.renderAssemblyScreen, "function");
  const parts = await import("./assembly-parts.js");
  for (const name of ["sceneDuration", "doneBanner", "finalPreview", "summaryCard", "historyBlock"]) {
    assert.equal(typeof parts[name], "function", name);
  }
  const lines = parts.assemblyLines(PROJECT, { ready: false, finished: false });
  assert.deepEqual(lines.map((line) => [line.key, line.value]),
    [["Сцены", "6 · 00:35"], ["Режим", "кадр за кадром"], ["Звук", "без звука"], ["Статус", "ещё не собран"]]);
  assert.equal(parts.sceneDuration(PROJECT), "00:35");
});

test("оболочка останавливает опрос монтажа вне «Сборки», boot подключает стили и перерисовку", () => {
  const shell = fs.readFileSync(new URL("./shell.js", import.meta.url), "utf8");
  assert.match(shell, /if \(screen !== "assembly"\) hideMontage\(\);/);
  const boot = fs.readFileSync(new URL("./boot.js", import.meta.url), "utf8");
  assert.match(boot, /ensureStylesheet\("\/static\/styles\/v2\/montage\.css"\)/);
  assert.match(boot, /addEventListener\("studio:montage-updated"/);
});
