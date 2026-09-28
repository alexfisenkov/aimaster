// Ядро опроса экрана «Сборка» — без DOM, его проверяют тесты: статус раз в
// POLL_MS, схема слоёв — отдельной попыткой, которую статус не ждёт (сервер
// считает её до 120 с, studio/montage/status_screen.py). Показ проекта
// (show/hide) — новое «поколение» со своим AbortController: всё, что летело
// для прежнего, обрывается, а его поздний ответ тихо бросается. Когда
// спрашивать схему — montage-model-tracker.js; что показать — montage-entry.js.

import { composeEntry } from "./montage-entry.js";
import { createModelTracker } from "./montage-model-tracker.js";
import { newController, requestWithTimeout } from "./montage-request.js";

export const POLL_MS = 5000;

// Таймаут одного запроса: у схемы он больше, чем у сервера может занять сам
// счёт (до 120 с) — иначе медленный ответ и зависший запрос не отличить.
const STATUS_TIMEOUT_MS = 15000;
const MODEL_TIMEOUT_MS = 130000;

/** Сбой в чужом коде (`notify` и обработчики за ним) браузер показывает как
 * необработанную ошибку — в консоли и `window.onerror`, — а опрос живёт. */
export function report(error) {
  globalThis.reportError?.(error);
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
  let shownModel = null;           // последняя удачная схема
  let modelRequest = null;         // летящий запрос схемы: {controller}

  function announce(id) {
    try {
      notify(id);
    } catch (error) {
      report(error);
    }
  }

  function publish(id) {
    const next = composeEntry({
      status: lastStatus, statusError, model: shownModel, modelKey: tracker.key, modelError: tracker.error,
    });
    if (JSON.stringify(next) === JSON.stringify(entry)) return;
    entry = next;
    announce(id);
  }

  /** Схема — отдельная, не дожидаемая статусом попытка. Пишет, только если
   * её не вытеснили (новый ключ, новое поколение). */
  function startModel(id, myGeneration, genSignal) {
    const key = tracker.flight;
    const request = { controller: newController() };
    modelRequest = request;
    requestWithTimeout(load, id, "model", { ms: modelTimeoutMs, genSignal, controller: request.controller })
      .then((result) => {
        if (modelRequest !== request) return; // вытеснена — ответ никому не нужен
        modelRequest = null;
        if (generation !== myGeneration) return;
        tracker.onResult(key, result);
        if (result.ok) shownModel = result.body;
        publish(id);
      })
      .catch(report)
      .finally(() => {
        if (modelRequest === request) modelRequest = null;
      });
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
    publish(id);
    onStatus?.();
    if (decision === "restart" || decision === "drop") {
      modelRequest?.controller?.abort();
      modelRequest = null;
    }
    if (decision === "start" || decision === "restart") startModel(id, myGeneration, genSignal);
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

  /** Новое поколение: прежнее обрывается, состояние — с чистого листа;
   * прежний refresh() своего ответа уже не дождётся. */
  function startGeneration(id) {
    generationController?.abort();
    generationController = newController();
    projectId = id;
    generation += 1;
    entry = null;
    lastStatus = null;
    statusError = null;
    shownModel = null;
    modelRequest = null;
    tracker.reset();
    queued = false;
    const waiters = queuedWaiters;
    queuedWaiters = [];
    waiters.forEach((resolve) => resolve());
  }

  return {
    show(id) {
      if (id !== projectId) startGeneration(id);
    },
    hide() {
      startGeneration(null);
    },
    /** Опрос по таймеру: статус этого поколения уже летит — пропускаем. */
    tick() {
      if (!projectId || busyGeneration === generation) return Promise.resolve();
      return runStatus(projectId, generation, generationController?.signal);
    },
    /** Явный запрос (после «Сделать текущей», открытия стола, возврата на
     * вкладку): резолвится по СВОЕМУ статусу, схему не ждёт. Пока статус
     * летит — досдаём ровно один ещё раз сразу следом. */
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
