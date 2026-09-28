// node --test skills/aimaster/studio/static/ui/v2/montage-request.test.mjs
//
// Один запрос «Сборки»: свой контроллер, таймаут, отмена поколением — без
// AbortSignal.any. Отмена сама заканчивает запрос, даже если load обрыв не
// слышит: таймер снят, подписка на поколение снята. Промис не отказывает.

import test from "node:test";
import assert from "node:assert/strict";
import { getEventListeners } from "node:events";

import { requestWithTimeout } from "./montage-request.js";

const silent = () => new Promise(() => {}); // молчит и обрыв не слышит
const timers = () => process.getActiveResourcesInfo().filter((kind) => kind === "Timeout").length;
const listeners = (signal) => getEventListeners(signal, "abort").length;

/** Как Safari/iOS < 17.4, Chrome и Android WebView < 116, Firefox < 124. */
async function withoutAny(run) {
  const saved = Object.getOwnPropertyDescriptor(AbortSignal, "any");
  delete AbortSignal.any;
  try {
    assert.equal(typeof AbortSignal.any, "undefined");
    return await run();
  } finally {
    if (saved) Object.defineProperty(AbortSignal, "any", saved);
  }
}

test("ответ load — как есть; подписка на поколение и таймер сняты", async () => {
  const generation = new AbortController();
  const before = timers();
  const seen = [];
  const load = (id, part, signal) => {
    seen.push([id, part, signal.aborted]);
    return Promise.resolve({ ok: true, body: { index_key: "k1" } });
  };
  const answer = await requestWithTimeout(load, "p", "model", { ms: 60000, genSignal: generation.signal });
  assert.deepEqual(answer, { ok: true, body: { index_key: "k1" } });
  assert.deepEqual(seen, [["p", "model", false]]);
  assert.equal(listeners(generation.signal), 0);
  assert.equal(timers(), before);
});

test("таймаут, load обрыв не слышит: timeout, сигнал load оборван, подписок на поколение не остаётся", () => withoutAny(async () => {
  const generation = new AbortController();
  const before = timers();
  const signals = [];
  const load = (id, part, signal) => {
    signals.push(signal);
    return silent();
  };
  for (let i = 0; i < 5; i += 1) { // пять опросов одного поколения подряд
    assert.deepEqual(await requestWithTimeout(load, "p", "", { ms: 10, genSignal: generation.signal }),
      { ok: false, code: "timeout" });
  }
  assert.deepEqual(signals.map((signal) => signal.aborted), [true, true, true, true, true]);
  assert.equal(listeners(generation.signal), 0);
  assert.equal(generation.signal.aborted, false);
  assert.equal(timers(), before);
}));

test("смена поколения, load обрыв не слышит: запросы кончаются сразу, таймеры и подписки сняты", () => withoutAny(async () => {
  const generation = new AbortController();
  const before = timers();
  const signals = [];
  const load = (id, part, signal) => {
    signals.push(signal);
    return silent();
  };
  const requests = [1, 2, 3].map(() => requestWithTimeout(load, "p", "model", { ms: 60000, genSignal: generation.signal }));
  assert.equal(listeners(generation.signal), 3);
  generation.abort(); // человек ушёл к другому проекту
  assert.deepEqual(await Promise.all(requests), Array(3).fill({ ok: false, code: "aborted" }));
  assert.deepEqual(signals.map((signal) => signal.aborted), [true, true, true]);
  assert.equal(listeners(generation.signal), 0);
  assert.equal(timers(), before); // три таймера по 60 с сняты — тест их не ждёт
}));

test("поколение уже сменилось — load даже не зовётся", async () => {
  const generation = new AbortController();
  generation.abort();
  let called = false;
  const answer = await requestWithTimeout(() => { called = true; return silent(); }, "p", "", { ms: 60000, genSignal: generation.signal });
  assert.deepEqual(answer, { ok: false, code: "aborted" });
  assert.equal(called, false);
});

test("load бросает или отказывает — network_error, промис не отказывает, следов не остаётся", async () => {
  const generation = new AbortController();
  const before = timers();
  const broken = [() => { throw new Error("load упал"); }, () => Promise.reject(new Error("load отказал"))];
  for (const load of broken) {
    assert.deepEqual(await requestWithTimeout(load, "p", "model", { ms: 60000, genSignal: generation.signal }),
      { ok: false, code: "network_error" });
  }
  assert.equal(listeners(generation.signal), 0);
  assert.equal(timers(), before);
});

test("load, что на обрыв сразу отвечает network_error, не перебивает причину: timeout или aborted", async () => {
  const hearing = (id, part, signal) => new Promise((resolve) => {
    signal.addEventListener("abort", () => resolve({ ok: false, code: "network_error" }), { once: true });
  });
  assert.deepEqual(await requestWithTimeout(hearing, "p", "", { ms: 10 }), { ok: false, code: "timeout" });
  const generation = new AbortController();
  const request = requestWithTimeout(hearing, "p", "", { ms: 60000, genSignal: generation.signal });
  generation.abort();
  assert.deepEqual(await request, { ok: false, code: "aborted" });
});
