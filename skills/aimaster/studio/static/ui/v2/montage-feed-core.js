// Ядро опроса «Сборки» без DOM: статус раз в POLL_MS, схема слоёв — отдельно,
// статус её не ждёт (сервер считает её до 120 с). Схема летит одна; новый
// ключ спрашивают, как только она легла (montage-model-tracker.js). Показ
// проекта (show/hide) — новое «поколение» со своим AbortController: всё
// прежнее обрывается, поздний ответ тихо бросается. Обрыв — только по
// таймауту и смене поколения (montage-request.js); entry — montage-entry.js.

import { composeEntry, staleTicksAfter } from "./montage-entry.js";
import { createModelTracker } from "./montage-model-tracker.js";
import { newController, requestWithTimeout } from "./montage-request.js";

export const POLL_MS = 5000;

// Таймаут одного запроса: у схемы он больше, чем у сервера может занять сам
// счёт (до 120 с) — иначе медленный ответ и зависший запрос не отличить.
const STATUS_TIMEOUT_MS = 15000;
const MODEL_TIMEOUT_MS = 130000;

/** Сбой в чужом коде (`notify`) — браузеру как необработанная ошибка (консоль,
 * `window.onerror`; без `reportError` — брошенная из таймера), опрос живёт. */
export function report(error) {
  if (typeof globalThis.reportError === "function") globalThis.reportError(error);
  else setTimeout(() => { throw error; });
}

export function createMontageFeed({
  load, notify, statusTimeoutMs = STATUS_TIMEOUT_MS, modelTimeoutMs = MODEL_TIMEOUT_MS,
}) {
  const tracker = createModelTracker();
  let projectId = null;
  let generation = 0;
  let generationController = null; // обрывает всё, что летело для прежнего поколения
  let busyGeneration = null;       // статус этого поколения летит (схема сюда не входит)
  let queued = false;              // refresh() позвали, пока статус летит — досдать сразу после него
  let queuedWaiters = [];          // resolve() тех refresh(), что ждут именно этот добор
  let entry = null;
  let lastStatus = null;           // последний удачный статус
  let statusError = null;          // отказ последнего статуса
  let shown = null;                // последняя удачная схема: {model, key — для какого ключа спрошена}
  let staleTicks = 0;              // опросов статуса подряд, пока схема на экране не свежая

  /** Пересобрать entry и, если он изменился, оповестить. `tick` — публикует
   * опрос статуса (он двигает счёт отставшей схемы). Сбой в `notify` не
   * роняет опрос и не оставляет `refresh()` без ответа. */
  function publish(id, tick = false) {
    const facts = {
      status: lastStatus, statusError, model: shown?.model, shownKey: shown?.key,
      modelKey: tracker.key, modelError: tracker.error,
    };
    staleTicks = staleTicksAfter(staleTicks, composeEntry(facts), tick);
    const next = composeEntry({ ...facts, staleTicks });
    if (JSON.stringify(next) === JSON.stringify(entry)) return;
    entry = next;
    try {
      notify(id);
    } catch (error) {
      report(error);
    }
  }

  /** Схема (`tracker.flight` — её ключ) легла — показать; статус тем временем
   * ушёл на другой ключ — сразу спросить его. Прежнее поколение — бросить.
   * Следующую схему спрашивают до публикации: `tracker` уже записал её в
   * полёт, и сбой публикации не должен оставить этот флаг навсегда. */
  function startModel(id, myGeneration, genSignal) {
    const key = tracker.flight;
    requestWithTimeout(load, id, "model", { ms: modelTimeoutMs, genSignal })
      .then((result) => {
        if (generation !== myGeneration) return; // tracker уже с чистого листа
        const next = tracker.onResult(key, result); // флаг полёта снят первым делом
        if (result.ok && result.body) shown = { model: result.body, key }; // без тела — провал, не показ
        if (next === "start") startModel(id, myGeneration, genSignal);
        publish(id);
      })
      .catch(report);
  }

  /** Одна попытка статуса: публикуется сразу (`onStatus` отпускает того,
   * кто ждал именно её — `refresh()`), схема — следом и отдельно. */
  async function statusAttempt(id, myGeneration, genSignal, onStatus) {
    const status = await requestWithTimeout(load, id, "", { ms: statusTimeoutMs, genSignal });
    if (generation !== myGeneration) {
      onStatus?.();
      return;
    }
    statusError = status.ok ? null : status;
    if (status.ok) lastStatus = status.body;
    const decision = status.ok ? tracker.onStatus(status.body) : "idle";
    // Схему — раньше публикации: `onStatus` уже записал её в полёт.
    if (decision === "start") startModel(id, myGeneration, genSignal);
    publish(id, true);
    onStatus?.();
  }

  async function runStatus(id, myGeneration, genSignal, onStatus) {
    busyGeneration = myGeneration;
    try {
      await statusAttempt(id, myGeneration, genSignal, onStatus);
      while (queued && generation === myGeneration) {
        queued = false;
        const waiters = queuedWaiters;
        queuedWaiters = [];
        await statusAttempt(id, myGeneration, genSignal, () => waiters.forEach((resolve) => resolve()));
      }
    } finally {
      if (busyGeneration === myGeneration) busyGeneration = null;
    }
  }

  /** Новое поколение: прежнее обрывается, ждущие refresh() отпускаются. */
  function startGeneration(id) {
    generationController?.abort();
    generationController = newController();
    projectId = id;
    generation += 1;
    entry = null;
    lastStatus = null;
    statusError = null;
    shown = null;
    staleTicks = 0;
    tracker.reset();
    queued = false;
    const waiters = queuedWaiters;
    queuedWaiters = [];
    waiters.forEach((resolve) => resolve());
  }

  return {
    show(id) { if (id !== projectId) startGeneration(id); },
    hide() { startGeneration(null); },
    /** Опрос по таймеру: статус этого поколения уже летит — пропускаем. */
    tick() {
      if (!projectId || busyGeneration === generation) return Promise.resolve();
      return runStatus(projectId, generation, generationController?.signal);
    },
    /** Явный запрос (после действия или возврата на вкладку): резолвится по
     * СВОЕМУ статусу, схему не ждёт; статус летит — досдаём один раз следом. */
    refresh() {
      if (!projectId) return Promise.resolve();
      const myGeneration = generation;
      if (busyGeneration === myGeneration) {
        queued = true;
        return new Promise((resolve) => { queuedWaiters.push(resolve); });
      }
      const id = projectId;
      const signal = generationController?.signal;
      return new Promise((resolve) => { runStatus(id, myGeneration, signal, resolve); });
    },
    current(id) {
      return id && id === projectId ? entry : null;
    },
    active() {
      return projectId;
    },
  };
}
