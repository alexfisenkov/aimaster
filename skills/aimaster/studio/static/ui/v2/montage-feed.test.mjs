// node --test skills/aimaster/studio/static/ui/v2/montage-feed.test.mjs
//
// Опрос монтажа: дешёвое состояние каждый раз, схема — только когда сменился
// index_key; ответ для прежнего проекта выбрасывается; отказ сервера — текстом.

import test from "node:test";
import assert from "node:assert/strict";

import { _resetCsrfTokenForTests } from "../actions.js";
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

test("сменился current_version при том же index_key — схема заново (сборка не трогает index.html)", async () => {
  // b4-review/stale-after-render.mjs: montage render меняет current_version
  // и unrendered_changes, но не пишет в index.html — index_key прежний.
  // Отставшую схему («несобранные правки») экран показывал бы вечно, не
  // спрашивая новую, если бы ключ обновления был завязан только на него.
  const { calls, seen, feed } = feedFor({
    status: [ok(STATUS("k1", { current_version: null, unrendered_changes: true })),
             ok(STATUS("k1", { current_version: "v001", unrendered_changes: false }))],
    model: [ok({ index_key: "k1", unrendered_changes: true }), ok({ index_key: "k1", unrendered_changes: false })],
  });
  feed.show("p");
  await feed.tick();
  await feed.tick();
  assert.deepEqual(calls, ["p", "p:model", "p", "p:model"]);
  assert.deepEqual(seen, ["p", "p"]);
  assert.equal(feed.current("p").model.unrendered_changes, false);
});

test("сменилась revision проекта при том же ключе — схема заново", async () => {
  const { calls, feed } = feedFor({
    status: [ok(STATUS("k1", { revision: 7 })), ok(STATUS("k1", { revision: 8 }))],
    model: [ok({ index_key: "k1" }), ok({ index_key: "k1" })],
  });
  feed.show("p");
  await feed.tick();
  await feed.tick();
  assert.deepEqual(calls, ["p", "p:model", "p", "p:model"]);
});

test("схема с model_error переспрашивается не каждый тик, а с растущей паузой", async () => {
  // MODEL_RETRY_TICKS = [0, 5, 11] тиков паузы (5 с, 30 с, 60 с гэпом между
  // попытками): тот же ключ, движок временно не смог посчитать таймлайн —
  // не долбим его раз в 5 с без остановки.
  const failing = { index_key: "k1", model_error: "HyperFrames «timeline --json» завершился с кодом 1" };
  const { calls, feed } = feedFor({ status: [ok(STATUS("k1"))], model: [ok(failing)] });
  feed.show("p");
  await feed.tick(); // попытка 1 — провал, пауза 0 тиков
  assert.deepEqual(calls, ["p", "p:model"]);
  await feed.tick(); // пауза 0 — сразу попытка 2 (гэп 5 с), тоже провал, пауза уже 5 тиков
  assert.deepEqual(calls, ["p", "p:model", "p", "p:model"]);
  await feed.tick(); // пауза только началась — схему не спрашиваем
  assert.deepEqual(calls, ["p", "p:model", "p", "p:model", "p"]);
  for (let i = 0; i < 4; i += 1) await feed.tick(); // ещё 4 из 5 тиков паузы
  assert.deepEqual(calls, ["p", "p:model", "p", "p:model", "p", "p", "p", "p", "p"]);
  await feed.tick(); // 6-й тик — пауза кончилась (гэп 30 с) — попытка 3
  assert.deepEqual(calls.at(-1), "p:model");
});

test("схема после провала оживает, как только приходит без ошибки", async () => {
  const failing = { index_key: "k1", model_error: "код 1" };
  const ready = { index_key: "k1", unrendered_changes: false };
  const { calls, feed } = feedFor({ status: [ok(STATUS("k1"))], model: [ok(failing), ok(ready)] });
  feed.show("p");
  await feed.tick(); // попытка 1 — провал, пауза 0
  await feed.tick(); // пауза 0 — сразу попытка 2 — успех
  assert.deepEqual(calls, ["p", "p:model", "p", "p:model"]);
  assert.equal(feed.current("p").model.unrendered_changes, false);
  await feed.tick(); // тот же ключ, прошлая попытка удачна — схему больше не спрашиваем
  assert.deepEqual(calls, ["p", "p:model", "p", "p:model", "p"]);
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

test("ответ для прежнего проекта выбрасывается, а не второй параллельный запрос", async () => {
  // Один опрос летит за раз (busy): переключение на «b», пока «a» ещё не
  // ответил, не запускает второй запрос тут же — иначе a→b→a копит
  // параллельные запросы (обзор B4, репродукция overlap.mjs). Как только
  // ответ для «a» пришёл, он отбрасывается (projectId уже не тот), а «b»
  // спрашивается следующим тиком.
  let release;
  const load = (id) => (id === "a"
    ? new Promise((resolve) => { release = () => resolve(ok(STATUS("k1"))); })
    : Promise.resolve(ok(STATUS("k9", { engine: { state: "missing" } }))));
  const seen = [];
  const feed = createMontageFeed({ load, notify: (id) => seen.push(id) });
  feed.show("a");
  const first = feed.tick();
  feed.show("b");
  await feed.tick(); // «a» ещё летит — этот тик пустой, «b» пока не спрошен
  assert.equal(feed.current("b"), null);
  release();
  await first; // ответ для «a» пришёл, но экран уже не на нём — отброшен
  assert.equal(feed.current("a"), null);
  assert.equal(feed.current("b"), null);
  await feed.tick(); // свободно — спрашиваем «b»
  assert.equal(feed.current("b").status.index_key, "k9");
  assert.deepEqual(seen, ["b"]);
});

test("refresh() во время обычного опроса не теряется — досдаётся один раз сразу за ним", async () => {
  // refreshMontage() зовут после «Сделать текущей», открытия стола,
  // возврата на вкладку: если промолчать, пока летит обычный опрос через
  // POLL_MS, человек до 5 с смотрел бы на старые данные без причины.
  let releaseFirst;
  const answers = [STATUS("k1", { engine: { state: "missing" } }), STATUS("k2", { engine: { state: "missing" } })];
  const calls = [];
  let count = 0;
  const load = async (id, part) => {
    calls.push(part || "status");
    count += 1;
    if (count === 1) return new Promise((resolve) => { releaseFirst = () => resolve(ok(answers.shift())); });
    return ok(answers.shift()); // добор после queued — сразу, отдельно управлять не нужно
  };
  const feed = createMontageFeed({ load, notify: () => {} });
  feed.show("p");
  const polled = feed.tick(); // 1-й запрос — «летит»
  const refreshed = feed.refresh(); // позвали, пока первый ещё не ответил
  assert.deepEqual(calls, ["status"]); // второй запрос не стартовал сам по себе — refresh() не полез вперёд
  assert.equal(await refreshed, undefined); // сам по себе не ждёт довеска — тот привязан к polled
  releaseFirst();
  await polled; // первый сел, следом сам собой ушёл и сел добор (queued)
  assert.deepEqual(calls, ["status", "status"]);
  assert.equal(feed.current("p").status.index_key, "k2");
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
  const savedFetch = globalThis.fetch;
  _resetCsrfTokenForTests();
  try {
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
  } finally {
    globalThis.fetch = savedFetch;
    _resetCsrfTokenForTests();
  }
});

test("refusalText: текст сервера, иначе по коду", () => {
  assert.equal(refusalText({ ok: false, code: "revision_conflict" }), "Проект только что изменился — попробуйте ещё раз.");
  assert.equal(refusalText({ ok: false, code: "forbidden" }), "Дашборд не принял запрос — обновите страницу.");
  assert.equal(refusalText({ ok: false, code: "что-то" }), "Не получилось. Попробуйте ещё раз.");
});
