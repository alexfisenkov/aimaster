// Опрос монтажа, пока открыт экран «Сборка»: дешёвое состояние раз в 5 с
// (только когда вкладка видна), схема слоёв — когда сменился index_key,
// current_version или revision проекта. Каждый опрос — ещё и знак серверу
// «экран смотрят»: стол, открытый дашбордом, не остановится по простою
// (studio/desk_keeper.py). Ядро `createMontageFeed` — без DOM, таймеры
// только свои (таймаут запроса — ниже), его проверяют тесты; обёртка ниже
// вешает таймер опроса и шлёт `studio:montage-updated`.
//
// Показ проекта (show/hide) заводит новое «поколение»: у каждой попытки
// (attempt) оно своё, снятое в момент запуска. Попытка прежнего поколения,
// чей ответ пришёл уже после переключения, тихо бросается — никогда не
// пишет в entry и никого не ждёт: переключение на другой проект не ждёт
// медленный ответ прежнего (схема сервер может считать до 120 с).

import { getMontage } from "./montage-api.js";

export const POLL_MS = 5000;

// Таймаут одного запроса: у схемы он больше, чем у сервера может занять сам
// счёт (до 120 с, studio/montage/status_screen.py) — иначе легитимный
// медленный ответ и сетевой зависший запрос было бы не отличить.
const STATUS_TIMEOUT_MS = 15000;
const MODEL_TIMEOUT_MS = 130000;

// Сколько тиков пропустить перед повтором схемы, которая пришла с ошибкой
// (сетевой отказ, таймаут или model_error/stale_error в теле — движок
// временно не смог посчитать таймлайн), — по числу неудач подряд с этим же
// ключом: 0 (следующий же тик — 5 с), потом 5 (30 с), потом 11 (60 с) —
// дальше без увеличения.
const MODEL_RETRY_TICKS = [0, 5, 11];

export function createMontageFeed({
  load, notify, statusTimeoutMs = STATUS_TIMEOUT_MS, modelTimeoutMs = MODEL_TIMEOUT_MS,
}) {
  let projectId = null;
  let entry = null;
  let generation = 0;        // растёт на каждый show()/hide() с новым id
  let busyGeneration = null; // какое поколение сейчас опрашивается (null — свободно)
  let queued = false;        // refresh() позвали, пока опрос уже летит — досдать сразу после него
  let queuedWaiters = [];    // resolve() тех refresh(), что ждут именно этот добор

  // Ключ, для которого схему в последний раз пробовали спросить: сменился
  // index_key (правка на столе), current_version (собрали новую версию —
  // index.html при этом не трогают, index_key тот же) или revision проекта
  // (снимок изменился) — старая схема могла устареть, спрашиваем заново.
  let modelKey = null;
  let modelFailStreak = 0;
  let modelWaitTicks = 0;
  let modelError = null; // последний отказ запроса схемы для modelKey — держим между попытками, не мигаем им

  function keyOf(body) {
    return { index_key: body.index_key, current_version: body.current_version, revision: body.revision };
  }

  function sameKey(a, b) {
    return Boolean(a) && Boolean(b) && a.index_key === b.index_key
      && a.current_version === b.current_version && a.revision === b.revision;
  }

  function applicable(body) {
    return Boolean(body) && body.applicable !== false && body.exists === true
      && body.engine?.state === "installed";
  }

  function modelFailed(body) {
    return !body || Boolean(body.model_error) || Boolean(body.stale_error);
  }

  /** Схему просить сейчас — или ключ новый, или прошлая попытка по этому же
   * ключу провалилась и пауза уже кончилась. */
  function needsModel(status) {
    if (!applicable(status)) return false;
    const key = keyOf(status);
    if (!sameKey(key, modelKey)) {
      modelFailStreak = 0; // новый ключ — прошлых неудач для него ещё не было
      return true;
    }
    if (modelFailStreak === 0) return false;
    if (modelWaitTicks > 0) {
      modelWaitTicks -= 1;
      return false;
    }
    return true;
  }

  function releaseWaiters() {
    if (!queuedWaiters.length) return;
    const waiters = queuedWaiters;
    queuedWaiters = [];
    waiters.forEach((resolve) => resolve());
  }

  /** Один запрос с таймаутом: дольше `ms` не ждём, а дальше живём так, будто
   * сервер отказал. `AbortController` не обязателен (тесты без него — тоже
   * обычный JS), но когда он есть, зависший `fetch` реально отменяется. */
  async function fetchWithTimeout(id, part, ms) {
    const controller = typeof AbortController === "function" ? new AbortController() : null;
    let timer;
    const timeout = new Promise((resolve) => {
      timer = setTimeout(() => resolve({ ok: false, code: "timeout" }), ms);
    });
    try {
      const result = await Promise.race([load(id, part, controller?.signal), timeout]);
      if (result.code === "timeout") controller?.abort();
      return result;
    } finally {
      clearTimeout(timer);
    }
  }

  /** Одна попытка: дешёвое состояние публикуется сразу (`onStatus` отпускает
   * того, кто ждал именно эту публикацию — `refresh()`), схема — отдельным,
   * вторым шагом, если нужна. Устаревшее поколение проверяется на каждом
   * шаге: писать в общий `entry` и звать чужой `notify` попытке чужого
   * поколения нельзя — своего проекта на экране уже нет. */
  async function attempt(id, myGeneration, onStatus) {
    const status = await fetchWithTimeout(id, "", statusTimeoutMs);
    if (generation !== myGeneration) {
      onStatus?.();
      return;
    }
    const statusEntry = {
      status: status.ok ? status.body : entry?.status || null,
      model: entry?.model || null,
      error: status.ok ? modelError : status,
    };
    const statusChanged = JSON.stringify(statusEntry) !== JSON.stringify(entry);
    entry = statusEntry;
    if (statusChanged) notify(id);
    onStatus?.();
    if (!status.ok || !needsModel(status.body)) return;
    const key = keyOf(status.body);
    if (!sameKey(key, modelKey)) modelError = null;
    const model = await fetchWithTimeout(id, "model", modelTimeoutMs);
    if (generation !== myGeneration) return;
    modelKey = key;
    const failed = model.ok ? modelFailed(model.body) : true;
    modelError = model.ok ? null : model;
    modelFailStreak = failed ? modelFailStreak + 1 : 0;
    modelWaitTicks = failed ? MODEL_RETRY_TICKS[Math.min(modelFailStreak - 1, MODEL_RETRY_TICKS.length - 1)] : 0;
    const modelEntry = { ...entry, model: model.ok ? model.body : entry.model, error: modelError };
    if (JSON.stringify(modelEntry) !== JSON.stringify(entry)) {
      entry = modelEntry;
      notify(id);
    }
  }

  async function run(id, myGeneration, onStatus) {
    busyGeneration = myGeneration;
    try {
      await attempt(id, myGeneration, onStatus);
      while (queued && generation === myGeneration) {
        queued = false;
        const waiters = queuedWaiters;
        queuedWaiters = [];
        await attempt(id, myGeneration, () => waiters.forEach((resolve) => resolve()));
      }
    } finally {
      if (busyGeneration === myGeneration) busyGeneration = null;
    }
  }

  return {
    show(id) {
      if (id !== projectId) {
        projectId = id;
        generation += 1;
        entry = null;
        modelKey = null;
        modelFailStreak = 0;
        modelWaitTicks = 0;
        modelError = null;
        queued = false;
        releaseWaiters(); // прежний refresh() своего ответа для старого проекта уже не дождётся
      }
    },
    hide() {
      projectId = null;
      generation += 1;
      entry = null;
      modelKey = null;
      modelFailStreak = 0;
      modelWaitTicks = 0;
      modelError = null;
      queued = false;
      releaseWaiters();
    },
    /** Обычный опрос (таймер, показ экрана): текущее поколение уже
     * опрашивается — просто пропускаем этот раз, следующий будет через
     * POLL_MS. Поколение прежнего проекта не в счёт — новое стартует сразу. */
    tick() {
      if (!projectId) return Promise.resolve();
      if (busyGeneration === generation) return Promise.resolve();
      return run(projectId, generation);
    },
    /** Явный запрос (после «Сделать текущей», открытия стола, возврата на
     * вкладку): резолвится, как только придёт СВОЙ ответ дешёвого опроса —
     * не ждёт схему. Пока летит обычный опрос — не теряем запрос, а сразу
     * следом досдаём ровно один ещё раз и резолвим по его статусу. */
    refresh() {
      if (!projectId) return Promise.resolve();
      const myGeneration = generation;
      if (busyGeneration === myGeneration) {
        queued = true;
        return new Promise((resolve) => { queuedWaiters.push(resolve); });
      }
      const id = projectId;
      return new Promise((resolve) => { run(id, myGeneration, resolve); });
    },
    current(id) {
      return id && id === projectId ? entry : null;
    },
    active() {
      return projectId;
    },
  };
}

// --- Обёртка страницы -------------------------------------------------

const feed = createMontageFeed({
  load: (id, part, signal) => getMontage(id, part, undefined, signal),
  notify: (id) => document.dispatchEvent(new CustomEvent("studio:montage-updated", {
    bubbles: true, detail: { projectId: id },
  })),
});
let timer = null;

function visible() {
  return typeof document === "undefined" || document.visibilityState === "visible";
}

/** Экран «Сборка» проекта на экране: начать (или продолжить) опрос. */
export function showMontage(projectId) {
  const fresh = feed.active() !== projectId;
  feed.show(projectId);
  if (!timer) timer = setInterval(() => { if (visible()) feed.tick(); }, POLL_MS);
  if (fresh) feed.tick();
}

/** Другой экран или фото-проект — опрос не нужен. */
export function hideMontage() {
  feed.hide();
  if (timer) {
    clearInterval(timer);
    timer = null;
  }
}

/** Что известно о монтаже проекта: `{status, model, error}` или `null`. */
export function montageState(projectId) {
  return feed.current(projectId);
}

/** Спросить сейчас: после «Сделать текущей», открытия стола, возврата на
 * вкладку. Резолвится по своему дешёвому ответу — вызывающий код не ждёт
 * схему; экран также слушает `studio:montage-updated` отдельно. */
export function refreshMontage() {
  return feed.refresh();
}
