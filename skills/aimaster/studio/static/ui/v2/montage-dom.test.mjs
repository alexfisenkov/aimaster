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

// Текст на своём фоне — не меньше 4,5:1 (WCAG AA). Цвета — из токенов
// tokens-v2.css; правило — по селектору, как он записан в montage.css.
const CONTRAST_PAIRS = Object.freeze([
  [".am-lane-empty", '.am-lane[data-empty="true"]'],
  [".am-layers-mark", ".am-layers-mark"],
  ['.am-layers-mark[data-tone="error"]', '.am-layers-mark[data-tone="error"]'],
  [".am-note", "--v2-bg"],
  [".am-desk-nolink, .am-desk-left", "--v2-bg"],
  [".am-version-meta", "--v2-surface"],
  [".am-versions-hint", "--v2-surface"],
  [".am-track-label", "--v2-surface"],
  [".am-file-path-text", ".am-file-path-text"],
  ['.am-notice[data-tone="warn"]', '.am-notice[data-tone="warn"]'],
  ['.am-notice[data-tone="error"]', '.am-notice[data-tone="error"]'],
  ['.am-notice[data-tone="info"]', '.am-notice[data-tone="info"]'],
]);

function tokenColors() {
  const css = fs.readFileSync(new URL("../../styles/v2/tokens-v2.css", import.meta.url), "utf8");
  return Object.fromEntries([...css.matchAll(/(--v2-[\w-]+):\s*(#[0-9a-fA-F]{3,6})\s*;/g)].map(([, name, hex]) => [name, hex]));
}

function ruleOf(css, selector) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const found = new RegExp(`(?:^|\\n)${escaped}\\s*\\{([^}]*)\\}`).exec(css);
  assert.ok(found, `нет правила ${selector}`);
  return found[1];
}

function luminance(hex) {
  const full = hex.length === 4 ? `#${[...hex.slice(1)].map((c) => c + c).join("")}` : hex;
  const [r, g, b] = [1, 3, 5].map((at) => parseInt(full.slice(at, at + 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

test("текст экрана монтажа — не меньше 4,5:1 к своему фону", () => {
  const css = fs.readFileSync(new URL("../../styles/v2/montage.css", import.meta.url), "utf8");
  const tokens = tokenColors();
  const colorOf = (rule, property) => {
    const found = new RegExp(`(?:^|[;{\\s])${property}:\\s*var\\((--v2-[\\w-]+)\\)`).exec(rule);
    assert.ok(found && tokens[found[1]], `${property} в «${rule.trim()}»`);
    return tokens[found[1]];
  };
  for (const [textSelector, background] of CONTRAST_PAIRS) {
    const ink = colorOf(ruleOf(css, textSelector), "color");
    const paper = background.startsWith("--") ? tokens[background] : colorOf(ruleOf(css, background), "background");
    const [light, dark] = [luminance(ink), luminance(paper)].sort((a, b) => b - a);
    const ratio = (light + 0.05) / (dark + 0.05);
    assert.ok(ratio >= 4.5, `${textSelector}: ${ink} на ${paper} — ${ratio.toFixed(2)}:1`);
  }
});
