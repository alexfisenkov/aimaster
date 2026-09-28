// node --test skills/aimaster/studio/static/ui/v2/montage-feed.test.mjs
//
// Опрос монтажа: дешёвое состояние каждый раз, схема — только когда сменился
// index_key; ответ для прежнего проекта выбрасывается; отказ сервера — текстом.

import test from "node:test";
import assert from "node:assert/strict";

import { getMontage, montageUrl, postMontage, refusalText } from "./montage-api.js";
import { POLL_MS, createMontageFeed } from "./montage-feed.js";

const ok = (body) => ({ ok: true, body });
const STATUS = (key, patch = {}) => ({ applicable: true, exists: true, engine: { state: "installed" }, index_key: key, ...patch });

function server(answers) {
  const calls = [];
  const load = async (id, part) => {
    calls.push(part ? `${id}:${part}` : id);
    const queue = answers[part || "status"];
    return queue.length > 1 ? queue.shift() : queue[0];
  };
  return { calls, load };
}

function feedFor(answers) {
  const { calls, load } = server(answers);
  const seen = [];
  return { calls, seen, feed: createMontageFeed({ load, notify: (id) => seen.push(id) }) };
}

test("опрос раз в 5 секунд", () => {
  assert.equal(POLL_MS, 5000);
});

test("первый опрос: состояние и схема, одно оповещение", async () => {
  const { calls, seen, feed } = feedFor({ status: [ok(STATUS("k1"))], model: [ok({ index_key: "k1", layers: [] })] });
  feed.show("p");
  await feed.tick();
  assert.deepEqual(calls, ["p", "p:model"]);
  assert.deepEqual(seen, ["p"]);
  assert.equal(feed.current("p").model.index_key, "k1");
});

test("то же состояние — схему не спрашиваем и не перерисовываем", async () => {
  const { calls, seen, feed } = feedFor({ status: [ok(STATUS("k1"))], model: [ok({ index_key: "k1" })] });
  feed.show("p");
  await feed.tick();
  await feed.tick();
  assert.deepEqual(calls, ["p", "p:model", "p"]);
  assert.deepEqual(seen, ["p"]);
});

test("сменился index_key — схема заново", async () => {
  const { calls, seen, feed } = feedFor({
    status: [ok(STATUS("k1")), ok(STATUS("k2"))],
    model: [ok({ index_key: "k1" }), ok({ index_key: "k2" })],
  });
  feed.show("p");
  await feed.tick();
  await feed.tick();
  assert.deepEqual(calls, ["p", "p:model", "p", "p:model"]);
  assert.deepEqual(seen, ["p", "p"]);
});

test("нет движка, черновика или это фото — схему не спрашиваем", async () => {
  for (const status of [STATUS("k1", { engine: { state: "missing" } }), STATUS(null, { exists: false }),
    { applicable: false }]) {
    const { calls, feed } = feedFor({ status: [ok(status)], model: [ok({})] });
    feed.show("p");
    await feed.tick();
    assert.deepEqual(calls, ["p"]);
  }
});

test("скрытый экран не опрашивается", async () => {
  const { calls, feed } = feedFor({ status: [ok(STATUS("k1"))], model: [ok({ index_key: "k1" })] });
  feed.show("p");
  feed.hide();
  await feed.tick();
  assert.deepEqual(calls, []);
  assert.equal(feed.current("p"), null);
});

test("ответ для прежнего проекта выбрасывается", async () => {
  let release;
  const load = (id) => (id === "a"
    ? new Promise((resolve) => { release = () => resolve(ok(STATUS("k1"))); })
    : Promise.resolve(ok(STATUS("k9", { engine: { state: "missing" } }))));
  const seen = [];
  const feed = createMontageFeed({ load, notify: (id) => seen.push(id) });
  feed.show("a");
  const first = feed.tick();
  feed.show("b");
  await feed.tick();
  release();
  await first;
  assert.equal(feed.current("a"), null);
  assert.equal(feed.current("b").status.index_key, "k9");
  assert.deepEqual(seen, ["b"]);
});

test("отказ сервера сохраняется с текстом", async () => {
  const refusal = { ok: false, code: "montage_refused", message: "в папке монтажа есть ссылки на другие места" };
  const { seen, feed } = feedFor({ status: [refusal], model: [ok({})] });
  feed.show("p");
  await feed.tick();
  assert.deepEqual(feed.current("p").error, refusal);
  assert.equal(refusalText(feed.current("p").error), refusal.message);
  assert.deepEqual(seen, ["p"]);
});

test("getMontage: адрес, ответ, отказ с текстом, нет сети", async () => {
  assert.equal(montageUrl("проект 1", "model"), "/api/projects/%D0%BF%D1%80%D0%BE%D0%B5%D0%BA%D1%82%201/montage/model");
  const seen = [];
  const answer = (status, body) => async (url) => {
    seen.push(url);
    return { ok: status < 400, status, json: async () => body };
  };
  assert.deepEqual(await getMontage("p", "", answer(200, { exists: true })), { ok: true, body: { exists: true } });
  assert.deepEqual(await getMontage("p", "model", answer(422, { error: { code: "montage_refused", message: "нет версии v009" } })),
    { ok: false, code: "montage_refused", message: "нет версии v009" });
  assert.deepEqual(await getMontage("p", "", async () => { throw new Error("offline"); }), { ok: false, code: "network_error" });
  assert.deepEqual(seen, ["/api/projects/p/montage", "/api/projects/p/montage/model"]);
});

test("postMontage: CSRF дашборда и текст отказа", async () => {
  const calls = [];
  globalThis.fetch = async (path, init = {}) => {
    calls.push([init.method || "GET", String(path), init.headers?.["X-CSRF-Token"] || null]);
    const json = (body, status = 200) => ({ ok: status < 400, status, json: async () => body });
    if (path === "/api/session") return json({ csrf_token: "t" });
    return json({ error: { code: "montage_refused", message: "ролик ещё не собран — показывать в папке нечего" } }, 422);
  };
  const result = await postMontage("p", "reveal");
  assert.deepEqual(result, { ok: false, code: "montage_refused", message: "ролик ещё не собран — показывать в папке нечего" });
  assert.deepEqual(calls.at(-1), ["POST", "/api/projects/p/montage/reveal", "t"]);
});

test("refusalText: текст сервера, иначе по коду", () => {
  assert.equal(refusalText({ ok: false, code: "revision_conflict" }), "Проект только что изменился — попробуйте ещё раз.");
  assert.equal(refusalText({ ok: false, code: "forbidden" }), "Дашборд не принял запрос — обновите страницу.");
  assert.equal(refusalText({ ok: false, code: "что-то" }), "Не получилось. Попробуйте ещё раз.");
});
