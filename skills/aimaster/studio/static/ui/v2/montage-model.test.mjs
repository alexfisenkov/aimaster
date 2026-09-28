// node --test skills/aimaster/studio/static/ui/v2/montage-model.test.mjs
//
// Экран «Сборка» монтажа — что человек увидит по снимку проекта и ответам
// `GET …/montage` и `GET …/montage/model`. Только чистые функции.

import test from "node:test";
import assert from "node:assert/strict";

import {
  downloadHref, durationText, montageApplies, montageScreen, notices, orientation, screenFlags,
  versionLabel, versionRows, whenText,
} from "./montage-model.js";
import { PROJECT, projectWith } from "./snapshot.fixture.mjs";

const AT = new Date(2026, 8, 28, 14, 5).toISOString();
const MONTAGE = {
  current_version: "v002",
  canvas: { width: 1080, height: 1920 },
  versions: [
    { id: "v001", asset_id: "asset-1", asset_url: "/assets/asset-1", created_at: AT, by: "agent",
      based_on: null, summary: "черновой монтаж: 3 клипа, 0:15" },
    { id: "v002", asset_id: "asset-2", asset_url: "/assets/asset-2", created_at: AT, by: "owner",
      based_on: "v001", summary: "" },
  ],
};
const STATUS = Object.freeze({
  project_id: "p", revision: 7, applicable: true,
  engine: { state: "installed", version: "0.8.75", reason: "" },
  exists: true, current_version: "v002", canvas: { width: 1080, height: 1920 },
  index_key: "k1", unrendered_changes: false,
  file: { version: "v002", shown: "рабочая папка/media/p/montage/v002.mp4" },
  desk: { state: "closed" }, reveal: true,
});
const status = (patch = {}) => ({ ...structuredClone(STATUS), ...patch });

test("монтаж — у видео и смешанных проектов; фото собирается картинкой", () => {
  assert.equal(montageApplies(projectWith({ type: "video" })), true);
  assert.equal(montageApplies(projectWith({ type: "mixed" })), true);
  assert.equal(montageApplies(projectWith({ type: "photo" })), false);
});

test("монтажная раскладка: есть монтаж или итога ещё нет; старый итог без монтажа — как раньше", () => {
  assert.equal(montageScreen(projectWith({ type: "video", montage: MONTAGE })), true);
  assert.equal(montageScreen(projectWith({ type: "video" })), true);
  assert.equal(montageScreen(projectWith({ type: "video", assembly: { asset_url: "/assets/old" } })), false);
  assert.equal(montageScreen(projectWith({ type: "photo" })), false);
});

test("версии новыми сверху: кто, когда, что изменилось, какая текущая", () => {
  const rows = versionRows(projectWith({ montage: MONTAGE }));
  assert.deepEqual(rows.map((row) => [row.label, row.who, row.current]), [["v2", "Вы", true], ["v1", "Агент", false]]);
  assert.equal(rows[0].summary, "без описания");
  assert.equal(rows[1].summary, "черновой монтаж: 3 клипа, 0:15");
  assert.equal(rows[1].when, "28.09, 14:05");
  assert.equal(rows[1].assetUrl, "/assets/asset-1");
  assert.deepEqual(versionRows(PROJECT), []);
});

test("номер версии читается коротко, дата — по-русски", () => {
  assert.equal(versionLabel("v010"), "v10");
  assert.equal(versionLabel("v1000"), "v1000");
  assert.equal(whenText("не дата"), "");
});

test("«Скачать» — тот же файл с download=1, и с билетом Mini App тоже", () => {
  assert.equal(downloadHref("/assets/asset-2"), "/assets/asset-2?download=1");
  assert.equal(downloadHref("/assets/asset-2?e=1&t=x"), "/assets/asset-2?e=1&t=x&download=1");
  assert.equal(downloadHref("https://example.test/x"), null);
  assert.equal(downloadHref(undefined), null);
});

test("стол на компьютере: закрыт, открыт со ссылкой, запускается", () => {
  assert.equal(screenFlags({ status: status() }).desk, "closed");
  const open = screenFlags({ status: status({ desk: { state: "open", url: "http://127.0.0.1:9/x", telemetry_off: true } }) });
  assert.deepEqual([open.desk, open.deskUrl], ["open", "http://127.0.0.1:9/x"]);
  assert.equal(screenFlags({ status: status({ desk: { state: "busy" } }) }).desk, "busy");
});

test("на телефоне и в Telegram нет стола и «Показать в папке» — есть подсказка", () => {
  for (const place of [{ phone: true }, { telegram: true }]) {
    const flags = screenFlags({ status: status(), ...place });
    assert.deepEqual([flags.desk, flags.reveal, flags.deskHint, flags.build], ["hidden", false, true, true]);
  }
});

test("нет движка или черновика — стола нет, сборка в чат остаётся", () => {
  const missing = screenFlags({ status: status({ engine: { state: "missing", version: null, reason: "не найден Node.js" } }) });
  assert.deepEqual([missing.engine, missing.desk, missing.build], ["missing", "hidden", true]);
  assert.equal(screenFlags({ status: status({ exists: false }) }).desk, "hidden");
  assert.deepEqual([screenFlags({ status: null }).engine, screenFlags({ status: null }).desk], ["unknown", "hidden"]);
});

test("после принятия ролика — ни стола, ни «Сделать текущей», ни сборки", () => {
  const flags = screenFlags({ status: status(), finished: true });
  assert.deepEqual([flags.desk, flags.restore, flags.build, flags.deskHint], ["hidden", false, false, false]);
});

test("«Показать в папке» — только когда файл на месте и серверу есть чем открыть папку", () => {
  assert.equal(screenFlags({ status: status() }).reveal, true);
  assert.equal(screenFlags({ status: status({ reveal: false }) }).reveal, false);
  assert.equal(screenFlags({ status: status({ file: { version: "v002", shown: null } }) }).reveal, false);
});

test("стол «открыт» без ссылки (адрес не с этого компьютера) — отдельный флаг, не тот же что «закрыт»", () => {
  // studio/montage/service_screen.py:desk_view отдаёт ровно {"state": "open"}
  // без ключа url, когда адрес стола не 127.0.0.1/localhost/[::1] — например,
  // запись .desk.json подменена или устарела. deskUrl тогда null, а флаг
  // deskLinkPending отличает этот случай от «стол закрыт».
  const flags = screenFlags({ status: status({ desk: { state: "open" } }) });
  assert.deepEqual([flags.desk, flags.deskUrl, flags.deskLinkPending], ["open", null, true]);
  assert.equal(screenFlags({ status: status({ desk: { state: "closed" } }) }).deskLinkPending, false);
  assert.equal(screenFlags({
    status: status({ desk: { state: "open", url: "http://127.0.0.1:9/x", telemetry_off: true } }),
  }).deskLinkPending, false);
});

test("плашка несобранных правок — по свежей схеме, иначе по дешёвому состоянию", () => {
  const byStatus = notices({ status: status({ unrendered_changes: true }) });
  assert.deepEqual(byStatus.map((item) => [item.key, item.action]), [["unrendered", "build"]]);
  assert.match(byStatus[0].text, /^Есть несобранные правки/);
  const byModel = notices({ status: status({ unrendered_changes: null }), model: { index_key: "k1", unrendered_changes: true } });
  assert.deepEqual(byModel.map((item) => item.key), ["unrendered"]);
  const oldModel = notices({ status: status({ index_key: "k2" }), model: { index_key: "k1", unrendered_changes: true } });
  assert.deepEqual(oldModel, []);
});

test("без собранной версии плашки нет: собирать ещё нечего сравнивать", () => {
  assert.deepEqual(notices({ status: status({ current_version: null, file: null, unrendered_changes: true }) }), []);
});

test("ошибки монтажа, пропавший файл и устаревшие клипы — текстом", () => {
  const list = notices({
    status: status({ file: { version: "v002", shown: null } }),
    model: { index_key: "k1", unrendered_changes: false, model_error: "HyperFrames «timeline --json» завершился с кодом 1",
             stale_error: null, stale_clips: [{ clip: "v-1" }, { clip: "v-2" }] },
  });
  assert.deepEqual(list.map((item) => [item.key, item.tone]), [["file", "error"], ["model_error", "error"], ["stale", "warn"]]);
  assert.match(list[0].text, /v2 нет на месте/);
  assert.match(list[2].text, /устарело: 2/);
  assert.equal(list[2].action, "refresh");
});

test("записки стола и ошибка опроса видны; фото — только ошибка опроса", () => {
  const list = notices({ status: status({ desk: { state: "closed", note: "монтажный стол не отвечает" } }), feedError: "Нет связи с дашбордом." });
  assert.deepEqual(list.map((item) => item.key), ["feed", "desk-note"]);
  assert.deepEqual(notices({ status: { applicable: false }, feedError: "x" }).map((item) => item.key), ["feed"]);
  const noOpener = notices({ status: status({ desk: { state: "open", url: "http://127.0.0.1:9/", telemetry_off: false } }) });
  assert.deepEqual(noOpener.map((item) => item.key), ["telemetry"]);
});

test("сторона кадра — для превью вертикального ролика", () => {
  assert.equal(orientation({ width: 1080, height: 1920 }), "portrait");
  assert.equal(orientation({ width: 1920, height: 1080 }), "landscape");
  assert.equal(orientation({ width: 1080, height: 1080 }), "square");
  assert.equal(orientation(null), "landscape");
});

test("длина — из схемы без несобранных правок, иначе по концу последней сцены", () => {
  const model = { index_key: "k1", unrendered_changes: false, duration: 14.6 };
  assert.equal(durationText({ status: status(), model, project: PROJECT }), "00:15");
  assert.equal(durationText({ status: status(), model: { ...model, unrendered_changes: true }, project: PROJECT }), "00:35");
  assert.equal(durationText({ status: null, model: null, project: projectWith({ scenes: [] }) }), "");
});
