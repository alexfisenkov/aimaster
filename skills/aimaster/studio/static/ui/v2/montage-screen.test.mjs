// node --test skills/aimaster/studio/static/ui/v2/montage-screen.test.mjs
//
// Блоки экрана «Сборка» на маленьком DOM (montage-fake-dom.mjs): что
// переживает перерисовку по опросу (фокус, прокрутка версий, «летит» и
// отказ кнопок), что видно после «Принять ролик», одна кнопка сборки,
// подпись схемы при ошибке, адрес стола только свой, чья перерисовка.

import test from "node:test";
import assert from "node:assert/strict";

import { _resetCsrfTokenForTests } from "../actions.js";
import { finalPreview, summaryCard } from "./assembly-parts.js";
import { byAction, installFakeDom } from "./montage-fake-dom.mjs";
import { renderMainActions } from "./montage-desk.js";
import { renderFileCard } from "./montage-file.js";
import { renderLayers } from "./montage-layers.js";
import { durationText, notices, screenFlags } from "./montage-model.js";
import { renderNotices } from "./montage-notices.js";
import { renderVersions } from "./montage-versions.js";
import { metaLine, montageRepaintWanted, setViewedScreen } from "./shell.js";
import { projectWith } from "./snapshot.fixture.mjs";

const AT = new Date(2026, 8, 28, 14, 5).toISOString();
const version = (id, by) => ({ id, asset_id: `a-${id}`, asset_url: `/assets/a-${id}`, created_at: AT, by,
  based_on: null, summary: `версия ${id}` });
const PROJECT = projectWith({
  id: "p", type: "video",
  montage: { current_version: "v002", canvas: { width: 1080, height: 1920 },
    versions: [version("v001", "agent"), version("v002", "owner"), version("v003", "agent")] },
});
const STATUS = (patch = {}) => ({
  project_id: "p", revision: 7, applicable: true, engine: { state: "installed", version: "0.8.75", reason: "" },
  exists: true, current_version: "v002", canvas: { width: 1080, height: 1920 }, index_key: "k1",
  unrendered_changes: false, file: { version: "v002", shown: "рабочая папка/media/p/montage/v002.mp4" },
  desk: { state: "closed" }, reveal: true, ...patch,
});
const MODEL = { index_key: "k1", duration: 3.5, unrendered_changes: false, layers: [
  { layer: "video", label: "Видео", clips: [{ id: "v-1", start: 0, duration: 2, media_start: 0, scene_id: null },
    { id: "v-2", start: 2, duration: 1.5, media_start: 0, scene_id: null }] },
  { layer: "titles", label: "Титры", clips: [] },
] };

function withDom(run) {
  return async () => {
    const { doc, restore } = installFakeDom();
    try {
      await run(doc);
    } finally {
      restore();
    }
  };
}

/** Показать узел «на странице» (перерисовка — это снять старый и показать новый). */
function show(doc, node) {
  doc.body.textContent = "";
  doc.body.append(node);
  return node;
}

/** Сервер дашборда на время теста: `/api/session` и ответы POST по порядку. */
function stubServer(answers) {
  const saved = globalThis.fetch;
  const posts = [];
  _resetCsrfTokenForTests();
  globalThis.fetch = async (path, init = {}) => {
    const json = (body, status = 200) => ({ ok: status < 400, status, json: async () => body });
    if (path === "/api/session") return json({ csrf_token: "t" });
    posts.push(String(path));
    const [body, status] = await answers.shift()();
    return json(body, status);
  };
  return { posts, restore: () => { globalThis.fetch = saved; _resetCsrfTokenForTests(); } };
}

test("у каждой кнопки и ссылки блоков — метка фокуса, у каждой своя: перерисовка по опросу не уводит фокус", withDom((doc) => {
  const status = STATUS({ desk: { state: "open", url: "http://127.0.0.1:9/x", telemetry_off: true },
    unrendered_changes: true });
  const flags = screenFlags({ status });
  const staleModel = { ...MODEL, stale_clips: [{ reason: null }] };
  const root = doc.createElement("div");
  root.append(
    renderNotices(notices({ status, model: staleModel }), { project: PROJECT, revision: 7, actions: true }),
    renderFileCard({ project: PROJECT, status, flags }),
    renderMainActions({ project: PROJECT, revision: 7, status, flags }),
    renderVersions({ project: PROJECT, revision: 7, flags, onChanged: () => {} }),
    renderLayers({ project: PROJECT, model: MODEL, engine: "installed", exists: true }),
    finalPreview(PROJECT, { ready: true, statusText: "текущая v2" }),
    summaryCard(PROJECT, 7, { ready: true, finished: false }),
  );
  const controls = root.descendants().filter((node) => node.tagName === "BUTTON" || node.tagName === "A");
  assert.ok(controls.length >= 12);
  const keys = controls.map((node) => {
    assert.equal(node.dataset.hook, "card-control", node.textContent);
    return `${node.dataset.targetId}|${node.dataset.action}`;
  });
  assert.equal(new Set(keys).size, keys.length, keys.join(", "));
  for (const action of ["download", "reveal", "desk-go", "desk-close", "build", "block:v-1", "preview",
    "restore", "refresh:stale", "copy-path"]) {
    assert.ok(keys.some((key) => key.endsWith(`|${action}`)), action);
  }
}));

test("«Есть несобранные правки» — только факт: кнопка «Собрать ролик → чат» на экране одна", withDom((doc) => {
  const status = STATUS({ unrendered_changes: true, file: { version: "v002", shown: null } });
  const flags = screenFlags({ status });
  const root = doc.createElement("div");
  root.append(renderNotices(notices({ status }), { project: PROJECT, revision: 7 }),
    renderMainActions({ project: PROJECT, revision: 7, status, flags }));
  assert.deepEqual(root.querySelectorAll(".am-notice").map((row) => row.dataset.key), ["unrendered", "file"]);
  assert.equal(root.querySelectorAll(".am-notice")[0].descendants().filter((n) => n.tagName === "BUTTON").length, 0);
  assert.deepEqual(byAction(root, "build").map((node) => node.textContent), ["Собрать ролик → чат"]);
  const stale = renderNotices(notices({ status: STATUS(), model: { ...MODEL, stale_clips: [{ reason: null }] } }),
    { project: PROJECT, revision: 7, actions: false });
  assert.equal(stale.descendants().filter((n) => n.tagName === "BUTTON").length, 0); // после принятия — без кнопок
}));

test("после «Принять ролик» оставленный открытым стол можно закрыть — и только", withDom((doc) => {
  const status = STATUS({ desk: { state: "open", url: "http://127.0.0.1:9/x", telemetry_off: true } });
  const box = renderMainActions({ project: PROJECT, revision: 7, status, flags: screenFlags({ status, finished: true }) });
  assert.deepEqual(box.descendants().filter((n) => n.dataset.action).map((n) => n.dataset.action), ["desk-close"]);
  assert.match(box.textContent, /Ролик принят, а монтажный стол ещё открыт/);
  const closed = renderMainActions({ project: PROJECT, revision: 7, status: STATUS(),
    flags: screenFlags({ status: STATUS(), finished: true }) });
  assert.equal(closed.childElementCount, 0);
}));

test("листалка версий остаётся там, куда её пролистали, — у каждого проекта своя", withDom(async (doc) => {
  const flags = screenFlags({ status: STATUS() });
  const render = (project) => show(doc, renderVersions({ project, revision: 7, flags, onChanged: () => {} }));
  const first = render(PROJECT).querySelector(".am-version-list");
  first.scrollLeft = 180;
  await first.fire("scroll");
  const again = render(PROJECT).querySelector(".am-version-list");
  await Promise.resolve();
  assert.equal(again.scrollLeft, 180);
  const other = render({ ...PROJECT, id: "q" }).querySelector(".am-version-list");
  await Promise.resolve();
  assert.equal(other.scrollLeft, 0);
}));

test("первая схема не прочиталась — «не удалось прочитать», а не «Читаем монтаж…»", withDom(() => {
  const base = { project: PROJECT, model: null, engine: "installed", exists: true };
  assert.match(renderLayers(base).textContent, /Читаем монтаж…/);
  const failed = renderLayers({ ...base, error: { ok: false, code: "timeout" } }).textContent;
  assert.match(failed, /Схему прочитать не удалось — причина выше\./);
  assert.doesNotMatch(failed, /Читаем/);
  const lanes = renderLayers({ ...base, model: MODEL }).querySelectorAll(".am-lane");
  assert.deepEqual(lanes.map((lane) => lane.dataset.empty), ["false", "true"]);
}));

test("«Показать в папке»: «летит» и отказ переживают перерисовку; экран перерисуют, если кнопку сняли", withDom(async (doc) => {
  let answer;
  const server = stubServer([() => new Promise((resolve) => { answer = resolve; }),
    async () => [{ project_id: "p", shown: "x" }, 200]]);
  try {
    const status = STATUS();
    const render = () => show(doc, renderFileCard({ project: PROJECT, status, flags: screenFlags({ status }) }));
    const click = byAction(render(), "reveal")[0].fire("click");
    await new Promise((resolve) => setTimeout(resolve, 0));
    const during = byAction(render(), "reveal")[0]; // опрос перерисовал экран, пока ждём ответа
    assert.equal(during.disabled, true);
    assert.match(during.parentNode.textContent, /Открываю папку…/);
    answer([{ error: { code: "montage_refused", message: "на этом компьютере нечем открыть папку" } }, 422]);
    await click;
    assert.ok(doc.events.some((event) => event.type === "studio:montage-updated" && event.detail.projectId === "p"));
    const after = byAction(render(), "reveal")[0];
    assert.equal(after.disabled, false);
    assert.match(after.parentNode.textContent, /нечем открыть папку/);
    await after.fire("click"); // новое нажатие — отказ забыт
    assert.doesNotMatch(byAction(render(), "reveal")[0].parentNode.textContent, /нечем/);
    assert.deepEqual(server.posts, ["/api/projects/p/montage/reveal", "/api/projects/p/montage/reveal"]);
  } finally {
    server.restore();
  }
}));

test("стол ответил чужим адресом — вкладка закрывается, по нему не переходим", withDom(async (doc) => {
  const tab = { closed: false, went: null, document: { body: {} },
    location: { replace: (url) => { tab.went = url; } }, close: () => { tab.closed = true; } };
  globalThis.window = { open: () => tab };
  const server = stubServer([async () => [{ project_id: "p", state: "open", url: "http://evil.example:9/x" }, 200]]);
  try {
    const status = STATUS();
    const box = show(doc, renderMainActions({ project: PROJECT, revision: 7, status, flags: screenFlags({ status }) }));
    await byAction(box, "desk-open")[0].fire("click");
    assert.deepEqual([tab.went, tab.closed], [null, true]);
  } finally {
    server.restore();
    delete globalThis.window;
  }
}));

test("перерисовка по опросу — только открытая «Сборка» того же проекта", () => {
  const state = (stage) => ({ snapshot: { active_project: { id: "p", type: "video", stage } } });
  assert.equal(montageRepaintWanted(state("assembly"), "p"), true);
  assert.equal(montageRepaintWanted(state("assembly"), "q"), false);
  assert.equal(montageRepaintWanted(state("motion"), "p"), false);
  assert.equal(montageRepaintWanted({ snapshot: null }, "p"), false);
  setViewedScreen("audio");
  try {
    assert.equal(montageRepaintWanted(state("assembly"), "p"), false);
  } finally {
    setViewedScreen(null);
  }
});

test("шапка и пилюля превью говорят одну длину: 3,5 с — «3,5 с» и «00:03,5»", () => {
  const status = STATUS();
  assert.equal(durationText({ status, model: MODEL, project: PROJECT }), "00:03,5");
  assert.match(metaLine(PROJECT, { seconds: 3.5 }), /· 3,5 с ·/);
});
