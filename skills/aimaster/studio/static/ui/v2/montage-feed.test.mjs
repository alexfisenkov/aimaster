// node --test skills/aimaster/studio/static/ui/v2/montage-feed.test.mjs
//
// Опрос монтажа: дешёвое состояние каждый раз, схема — когда сменился
// index_key, current_version или revision, отдельной, не дожидаемой tick()
// попыткой (статус её не ждёт); у каждого show()/hide() своё поколение со
// своим AbortController — попытка прежнего поколения не пишет в состояние,
// не ждётся и обрывается явно; отказ схемы держится между попытками, не
// мигает, и не показывается для чужого ключа; отказ сервера — текстом.

import test from "node:test";
import assert from "node:assert/strict";

import { _resetCsrfTokenForTests } from "../actions.js";
import { getMontage, montageUrl, postMontage, refusalText } from "./montage-api.js";
import { POLL_MS, createMontageFeed } from "./montage-feed.js";

const ok = (body) => ({ ok: true, body });
const STATUS = (key, patch = {}) => ({ applicable: true, exists: true, engine: { state: "installed" }, index_key: key, ...patch });

/** Схема — отдельная, не дожидаемая tick()/refresh() попытка (раунд 3): один
 * оборот таймера-макрозадачи гарантированно даёт её микрозадачам (load →
 * race → then-обработчик) осесть, раз сама схема отвечает синхронно-быстро
 * (Promise.resolve, не настоящая сеть). */
const settleModel = () => new Promise((resolve) => setTimeout(resolve, 0));

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

test("первый опрос: состояние публикуется сразу, схема — вторым шагом", async () => {
  // Требование «статус раньше схемы»: даже когда схема приходит быстро
  // следом (без задержки, как здесь), это два отдельных шага публикации —
  // оба меняют entry, оба зовут notify. Так «Сборка» видит свежий статус
  // (десk, current_version), не дожидаясь медленной схемы (до 130 с).
  const { calls, seen, feed } = feedFor({ status: [ok(STATUS("k1"))], model: [ok({ index_key: "k1", layers: [] })] });
  feed.show("p");
  await feed.tick();
  await settleModel(); // схема — отдельная попытка, tick() её не ждёт
  assert.deepEqual(calls, ["p", "p:model"]);
  assert.deepEqual(seen, ["p", "p"]);
  assert.equal(feed.current("p").model.index_key, "k1");
});

test("то же состояние — схему не спрашиваем и не перерисовываем повторно", async () => {
  const { calls, seen, feed } = feedFor({ status: [ok(STATUS("k1"))], model: [ok({ index_key: "k1" })] });
  feed.show("p");
  await feed.tick(); // статус + схема — два оповещения
  await settleModel();
  await feed.tick(); // тот же ключ, схема уже удачна — ни статус, ни схема не меняются, оповещений нет
  assert.deepEqual(calls, ["p", "p:model", "p"]);
  assert.deepEqual(seen, ["p", "p"]);
});

test("медленная схема не задерживает публикацию статуса", async () => {
  // Требование «статус раньше схемы», буквально: пока схема ещё летит,
  // entry уже несёт свежий статус (desk, current_version, …) — DOM не
  // застревает на старых данных на те секунды, что считает движок.
  let releaseModel;
  const load = async (id, part) => {
    if (!part) return { ok: true, body: STATUS("k1") };
    return new Promise((resolve) => { releaseModel = () => resolve({ ok: true, body: { index_key: "k1" } }); });
  };
  const seen = [];
  const feed = createMontageFeed({ load, notify: (id) => seen.push(id) });
  feed.show("p");
  await feed.tick(); // резолвится по статусу — схему не ждёт вовсе (раунд 3)
  assert.deepEqual(seen, ["p"]);
  assert.equal(feed.current("p").status.index_key, "k1");
  assert.equal(feed.current("p").model, null);
  releaseModel();
  await settleModel();
  assert.deepEqual(seen, ["p", "p"]);
  assert.equal(feed.current("p").model.index_key, "k1");
});

test("сменился index_key — схема заново", async () => {
  const { calls, seen, feed } = feedFor({
    status: [ok(STATUS("k1")), ok(STATUS("k2"))],
    model: [ok({ index_key: "k1" }), ok({ index_key: "k2" })],
  });
  feed.show("p");
  await feed.tick(); // статус + схема
  await settleModel();
  await feed.tick(); // ключ сменился — статус + схема снова
  await settleModel();
  assert.deepEqual(calls, ["p", "p:model", "p", "p:model"]);
  assert.deepEqual(seen, ["p", "p", "p", "p"]);
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
  await settleModel();
  await feed.tick();
  await settleModel();
  assert.deepEqual(calls, ["p", "p:model", "p", "p:model"]);
  assert.deepEqual(seen, ["p", "p", "p", "p"]);
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
  await settleModel();
  await feed.tick(); // пауза 0 — сразу попытка 2 — успех
  await settleModel();
  assert.deepEqual(calls, ["p", "p:model", "p", "p:model"]);
  assert.equal(feed.current("p").model.unrendered_changes, false);
  await feed.tick(); // тот же ключ, прошлая попытка удачна — схему больше не спрашиваем
  assert.deepEqual(calls, ["p", "p:model", "p", "p:model", "p"]);
});

test("схема, зависшая дольше таймаута, считается провалом и уходит в паузу", async () => {
  // Без своего таймаута зависший (не сетевой-отказавший, а именно молчащий)
  // запрос схемы держал бы опрос занятым бесконечно — сервер сам считает
  // модель до 120 с, отличить «ещё считает» от «завис навсегда» без предела
  // нечем. modelTimeoutMs здесь мал специально — тест не ждёт реальные 130 с.
  const calls = [];
  const load = async (id, part) => {
    calls.push(part || "status");
    if (part === "model") return new Promise(() => {}); // никогда не ответит
    return ok(STATUS("k1"));
  };
  const feed = createMontageFeed({ load, notify: () => {}, modelTimeoutMs: 20 });
  feed.show("p");
  await feed.tick(); // попытка 1 — схема запущена отдельно (детач), таймаут наступит через реальные 20 мс
  await new Promise((resolve) => setTimeout(resolve, 30));
  assert.deepEqual(calls, ["status", "model"]);
  assert.equal(feed.current("p").error?.code, "timeout");
  await feed.tick(); // пауза 0 — сразу попытка 2 (тоже таймаут), пауза уже 5 тиков
  await new Promise((resolve) => setTimeout(resolve, 30));
  assert.deepEqual(calls, ["status", "model", "status", "model"]);
  await feed.tick(); // пауза только началась — схему не спрашиваем
  assert.deepEqual(calls, ["status", "model", "status", "model", "status"]);
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
  // Брифовый тест задачи 16 (восстановлен в раунде 2 правок B4): «b»
  // спрашивается сразу, не дожидаясь медленного ответа «a» — своё
  // поколение не ждёт чужое. Когда ответ «a» всё же приходит, поколение
  // уже другое — отброшен молча, ни entry, ни notify его не видят.
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

test("переключение на другой проект не ждёт медленный ответ прежнего (repro r1-switch-latency.mjs)", async () => {
  // Раунд 1: «busy»-флаг на весь опрос заставлял «b» ждать до 120 с схемы
  // «a». Раунд 2: у каждого show() своё поколение — «b» получает свои
  // данные сразу же следующим тиком, «a» продолжает копить неудачи в фоне
  // и никогда не пишет в состояние «b».
  let releaseModelA;
  const calls = [];
  const load = (id, part) => {
    calls.push(part ? `${id}:${part}` : `${id}:status`);
    if (id === "a" && part === "model") {
      return new Promise((resolve) => { releaseModelA = () => resolve(ok({ index_key: "k-a" })); });
    }
    return Promise.resolve(ok(part ? { index_key: `k-${id}` } : STATUS(`k-${id}`)));
  };
  const feed = createMontageFeed({ load, notify: () => {} });
  feed.show("a");
  await feed.tick(); // статус «a» готов; схема «a» запущена отдельно (детач) и «висит»
  feed.show("b");
  await feed.tick(); // «b» получает свои данные, не дожидаясь схемы «a»
  await settleModel();
  assert.equal(feed.current("b").status.index_key, "k-b");
  assert.equal(feed.current("b").model.index_key, "k-b");
  assert.equal(feed.current("a"), null);
  releaseModelA();
  await settleModel(); // «a» наконец сел — но его данные уже некуда писать
  assert.equal(feed.current("b").status.index_key, "k-b"); // не затёрто ответом «a»
  assert.equal(feed.current("a"), null);
});

test("статус меняется на сервере, пока схема ещё летит — тик и refresh() видят перемену (repro r2-model-freezes-status.mjs)", async () => {
  // Раунд 2 всё ещё держал весь опрос «занятым» на время схемы (до 120 с) —
  // «Открыть монтажный стол» → POST успел, а десk на экране оставался
  // «закрыт» до тех пор, пока не пришла схема. Раунд 3: статус и схема —
  // независимые попытки; ни обычный тик, ни refresh() схему не ждут.
  let desk = "closed";
  let releaseModel;
  const load = (id, part) => {
    if (part === "model") {
      return new Promise((resolve) => { releaseModel = () => resolve(ok({ index_key: "k1" })); });
    }
    return Promise.resolve(ok({ applicable: true, exists: true, engine: { state: "installed" }, index_key: "k1",
      current_version: "v001", revision: 1, desk: { state: desk } }));
  };
  const feed = createMontageFeed({ load, notify: () => {} });
  feed.show("p");
  await feed.tick(); // статус: закрыт; схема запущена отдельно (детач) и «висит»
  assert.equal(feed.current("p").status.desk.state, "closed");
  desk = "open"; // человек нажал «Открыть монтажный стол», POST на сервере уже прошёл
  await feed.tick(); // обычный тик по таймеру — видит перемену, схема всё ещё летит и не мешает
  assert.equal(feed.current("p").status.desk.state, "open");
  const refreshed = await feed.refresh().then(() => true); // резолвится по статусу, схему тоже не ждёт
  assert.equal(refreshed, true);
  releaseModel();
  await settleModel();
});

test("отказ схемы не показывается для чужого ключа и гаснет, когда статус стал неприменим (repro r2-model-error-lifetime.mjs)", async () => {
  const refusal = { ok: false, code: "montage_refused", message: "в папке монтажа есть ссылки на другие места" };
  let status = STATUS("k1", { current_version: "v001", revision: 1 });
  let modelAnswer = () => Promise.resolve(refusal);
  const feed = createMontageFeed({
    load: (id, part) => (part ? modelAnswer() : Promise.resolve(ok(status))), notify: () => {},
  });
  feed.show("p");
  await feed.tick();
  await settleModel();
  assert.equal(feed.current("p").error?.code, "montage_refused");

  // (a) ключ сменился на k2 — старая ошибка (про k1) не должна виснуть на новом статусе,
  // пока схема k2 ещё летит; после её успешного прихода отказа тоже нет.
  let release;
  modelAnswer = () => new Promise((resolve) => { release = () => resolve(ok({ index_key: "k2" })); });
  status = STATUS("k2", { current_version: "v001", revision: 1 });
  await feed.tick();
  assert.equal(feed.current("p").status.index_key, "k2");
  assert.equal(feed.current("p").error, null);
  release();
  await settleModel();
  assert.equal(feed.current("p").error, null);

  // (b) статус стал неприменим (движок пропал) — держать отказ незачем, он снят.
  status = STATUS("k2", { engine: { state: "missing" } });
  await feed.tick();
  assert.equal(feed.current("p").error, null);
});

test("переключение поколения обрывает запрос схемы прежнего проекта (repro r2-abandoned-live.mjs)", async () => {
  // HTTP/1.1: у браузера предел в 6 соединений на хост — забытые запросы
  // прежних поколений не должны копиться незамеченными.
  const signals = [];
  const releases = [];
  function load(id, part, signal) {
    if (!part) return Promise.resolve(ok(STATUS(`k-${id}`)));
    signals.push(signal);
    return new Promise((resolve) => releases.push(() => resolve(ok({ index_key: `k-${id}` }))));
  }
  const feed = createMontageFeed({ load, notify: () => {} });
  for (const id of ["p1", "p2", "p3"]) {
    feed.show(id);
    feed.tick();
    await settleModel(); // статус успел ответить, схема запущена и «висит»
  }
  assert.equal(signals.length, 3);
  assert.deepEqual(signals.slice(0, 2).map((s) => s?.aborted), [true, true]); // прежние поколения оборваны явно
  assert.equal(signals[2]?.aborted, false); // текущее поколение — нет
  releases.forEach((release) => release()); // не оставляем висящих запросов после теста
  await settleModel();
});

test("modelFresh — false, пока показанная схема отстала от статуса, снова true после её обновления", async () => {
  const { feed } = feedFor({
    status: [ok(STATUS("k1")), ok(STATUS("k2"))],
    model: [ok({ index_key: "k1" }), ok({ index_key: "k2" })],
  });
  feed.show("p");
  await feed.tick();
  await settleModel();
  assert.equal(feed.current("p").modelFresh, true);
  await feed.tick(); // ключ сменился на k2 — показанная схема ещё k1
  assert.equal(feed.current("p").modelFresh, false);
  await settleModel(); // схема k2 подъехала
  assert.equal(feed.current("p").modelFresh, true);
});

test("refresh() во время обычного опроса не теряется — резолвится по своему статусу", async () => {
  // refreshMontage() зовут после «Сделать текущей», открытия стола,
  // возврата на вкладку: если промолчать, пока летит обычный опрос через
  // POLL_MS, человек до 5 с смотрел бы на старые данные без причины.
  // Раунд 2: refresh() резолвится не по всему циклу («статус + возможно
  // схема» текущего опроса), а именно по СВОЕЙ, отдельно досланной попытке
  // — как только придёт её собственный статус, не дожидаясь схемы.
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
  const refreshed = feed.refresh(); // позвали, пока первый ещё не ответил — встал в очередь, второго запроса нет
  assert.deepEqual(calls, ["status"]); // второй запрос не стартовал сам по себе — refresh() не полез вперёд
  releaseFirst(); // первый ответ пришёл — сразу следом уходит добор
  await polled;
  await refreshed; // резолвится по статусу добора
  assert.deepEqual(calls, ["status", "status"]);
  assert.equal(feed.current("p").status.index_key, "k2");
});

test("refresh(), пока идёт опрос, а потом hide() — добор не срывается с id=null (repro r1-queued-after-hide.mjs)", async () => {
  let release;
  const calls = [];
  const notified = [];
  const load = (id, part) => {
    calls.push([id, part]);
    if (calls.length === 1) return new Promise((resolve) => { release = () => resolve(ok(STATUS("k1"))); });
    return Promise.resolve({ ok: false, code: "not_found" }); // добор не должен случиться вовсе
  };
  const feed = createMontageFeed({ load, notify: (id) => notified.push(id) });
  feed.show("p");
  const t = feed.tick();
  feed.refresh(); // например, возврат на вкладку, пока обычный опрос летит
  feed.hide(); // человек ушёл с экрана «Сборка» раньше, чем опрос ответил
  release();
  await t;
  assert.deepEqual(calls, [["p", ""]]); // ни второго вызова, ни тем более с id=null
  assert.deepEqual(notified, []); // экран уже не на «p» — писать некуда, notify не зовётся
});

test("отказ схемы держится между попытками, не мигает (repro r1-model-refusal-flicker.mjs)", async () => {
  const refusal = { ok: false, code: "montage_refused", message: "в папке монтажа есть ссылки на другие места" };
  const load = async (id, part) => (part ? refusal : { ok: true, body: STATUS("k1", { current_version: "v001" }) });
  const feed = createMontageFeed({ load, notify: () => {} });
  feed.show("p");
  for (let i = 0; i < 9; i += 1) {
    await feed.tick();
    await settleModel();
    assert.equal(feed.current("p").error?.code, "montage_refused", `tick ${i + 1}: отказ не должен пропадать`);
  }
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
