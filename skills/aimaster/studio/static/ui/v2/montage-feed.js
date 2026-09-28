// Опрос монтажа, пока открыт экран «Сборка»: дешёвое состояние раз в 5 с
// (только когда вкладка видна), схема слоёв — когда сменился index_key,
// current_version или revision проекта. Каждый опрос — ещё и знак серверу
// «экран смотрят»: стол, открытый дашбордом, не остановится по простою
// (studio/desk_keeper.py). Ядро `createMontageFeed` — без DOM, таймеры
// только свои (таймаут запроса — ниже), его проверяют тесты; обёртка ниже
// вешает таймер опроса и шлёт `studio:montage-updated`.
//
// Показ проекта (show/hide) заводит новое «поколение» со своим
// `AbortController`. У каждого запроса — ещё и свой контроллер: его
// обрывают таймаут запроса, отмена поколения (сигнал поколения пересылается
// в него вручную — `AbortSignal.any` нет в Safari/iOS < 17.4, Chrome и
// Android WebView < 116, Firefox < 124, а это и Mini App в Telegram на
// iPhone постарше) и, у схемы, новый ключ (схема прежнего ключа больше не
// нужна). Попытка прежнего поколения, чей ответ пришёл уже после
// переключения, тихо бросается — никогда не пишет в entry и никого не ждёт.
// Обрывать запросы надо всерьёз: дашборд по HTTP/1.1, у браузера предел —
// 6 соединений на хост, зависшие сокеты заперли бы весь дашборд.
//
// Статус и схема идут раздельно: статус — раз в POLL_MS, коротко; схему
// сервер может считать до 120 с (studio/montage/status_screen.py), и пока
// она считается, статус всё равно опрашивается по расписанию — модель не
// держит его в заложниках. `busyGeneration` — про статус, `modelFlight` —
// про схему, это два независимых флага.

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

function newController() {
  return typeof AbortController === "function" ? new AbortController() : null;
}

/** Сбой в чужом коде (`notify` и обработчики за ним) браузер показывает как
 * необработанную ошибку — в консоли и `window.onerror`, — а опрос живёт
 * дальше: его флаги сняты, `refresh()` дождётся ответа. */
function report(error) {
  globalThis.reportError?.(error);
}

export function createMontageFeed({
  load, notify, statusTimeoutMs = STATUS_TIMEOUT_MS, modelTimeoutMs = MODEL_TIMEOUT_MS,
}) {
  let projectId = null;
  let entry = null;
  let generation = 0;
  let generationController = null; // отменяется в show()/hide() — обрывает всё, что летело для прежнего поколения
  let busyGeneration = null;       // статус для этого поколения летит (модель сюда не входит)
  let modelFlight = null;          // схема, что летит сейчас: {key, controller} — статус её не ждёт
  let queued = false;              // refresh() позвали, пока статус уже летит — досдать статус сразу после него
  let queuedWaiters = [];          // resolve() тех refresh(), что ждут именно этот добор
  let statusError = null;          // отказ последнего статуса — поздняя схема его не затирает

  // Ключ, для которого схему в последний раз спросили и получили ответ:
  // сменился index_key (правка на столе), current_version (собрали новую
  // версию — index.html при этом не трогают, index_key тот же) или revision
  // проекта (снимок изменился) — старая схема могла устареть, спрашиваем
  // заново. `modelError` и счёт неудач всегда про этот же ключ.
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

  /** Схему показываем как актуальную только пока её index_key совпадает с
   * текущим статусом — B5 вешает на `false` подпись «обновляется…». */
  function modelFresh(statusBody, model) {
    return Boolean(model) && Boolean(statusBody) && model.index_key === statusBody.index_key;
  }

  /** Схема летит для прежнего ключа, а статус уже на новом: ответ про старый
   * ключ никому не нужен — обрываем запрос сейчас, чтобы новый ключ спросить
   * этим же тиком, а не когда старый досчитается (до 130 с). */
  function dropSupersededModel(status) {
    if (!modelFlight || !applicable(status) || sameKey(modelFlight.key, keyOf(status))) return;
    modelFlight.controller?.abort();
    modelFlight = null;
  }

  /** Схему просить сейчас — или ключ новый, или прошлая попытка по этому же
   * ключу провалилась и пауза уже кончилась; схема сейчас не летит (иначе
   * второй параллельный запрос той же схемы). */
  function needsModel(status) {
    if (!applicable(status) || modelFlight) return false;
    if (!sameKey(keyOf(status), modelKey)) return true; // новый ключ — схему для него ещё не спрашивали
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

  function announce(id) {
    try {
      notify(id);
    } catch (error) {
      report(error);
    }
  }

  /** Один запрос со своим контроллером (схема передаёт свой — чтобы новый
   * ключ мог оборвать её снаружи). Его обрывают таймаут и отмена поколения:
   * сигнал поколения пересылается в контроллер запроса вручную, без
   * `AbortSignal.any`, и подписка снимается, как только запрос кончился —
   * поколение переживает много опросов. Никогда не бросает: сбой самого
   * `load` — это `network_error`, как у `getMontage` при обрыве fetch. */
  async function fetchWithTimeout(id, part, ms, genSignal, controller = newController()) {
    const cancel = () => controller?.abort();
    if (genSignal?.aborted) cancel();
    else genSignal?.addEventListener("abort", cancel, { once: true });
    let timer;
    const timeout = new Promise((resolve) => {
      // Сначала ответ «таймаут», потом обрыв: обрыв может синхронно
      // закончить `load` своим network_error — гонку выигрывает таймаут.
      timer = setTimeout(() => { resolve({ ok: false, code: "timeout" }); cancel(); }, ms);
    });
    try {
      return await Promise.race([load(id, part, controller?.signal), timeout]);
    } catch {
      return { ok: false, code: "network_error" };
    } finally {
      clearTimeout(timer);
      genSignal?.removeEventListener("abort", cancel);
    }
  }

  /** Ответ схемы для `key` — в счёт неудач, в entry и в notify. Отказ
   * самого статуса (`statusError`) сильнее: схема его не затирает. */
  function publishModel(id, key, model) {
    const failed = model.ok ? modelFailed(model.body) : true;
    const streak = sameKey(key, modelKey) ? modelFailStreak : 0; // новый ключ — прошлых неудач для него ещё не было
    modelKey = key;
    modelError = model.ok ? null : model;
    modelFailStreak = failed ? streak + 1 : 0;
    modelWaitTicks = failed ? MODEL_RETRY_TICKS[Math.min(modelFailStreak - 1, MODEL_RETRY_TICKS.length - 1)] : 0;
    const currentStatus = entry?.status;
    const stillCurrent = applicable(currentStatus) && sameKey(keyOf(currentStatus), key);
    const nextModel = model.ok ? model.body : entry?.model || null;
    const modelEntry = {
      ...entry,
      model: nextModel,
      error: statusError || (stillCurrent ? modelError : null),
      modelFresh: modelFresh(currentStatus, nextModel),
    };
    if (JSON.stringify(modelEntry) !== JSON.stringify(entry)) {
      entry = modelEntry;
      announce(id);
    }
  }

  /** Схема — отдельная, «отвязанная» от статуса попытка: статус её не ждёт.
   * Пишет, только если её не вытеснили (новый ключ, новое поколение); флаг
   * полёта снимается при любом исходе, сбой не уходит в пустоту. */
  function startModelFetch(id, myGeneration, statusBody, genSignal) {
    const flight = { key: keyOf(statusBody), controller: newController() };
    modelFlight = flight;
    fetchWithTimeout(id, "model", modelTimeoutMs, genSignal, flight.controller)
      .then((model) => {
        if (modelFlight !== flight) return; // вытеснена — ответ про прежний ключ или проект никому не нужен
        modelFlight = null;
        if (generation === myGeneration) publishModel(id, flight.key, model);
      })
      .catch(report)
      .finally(() => {
        if (modelFlight === flight) modelFlight = null;
      });
  }

  /** Одна попытка статуса: публикуется сразу (`onStatus` отпускает того,
   * кто ждал именно эту публикацию — `refresh()`); если нужна схема,
   * запускает её отдельной, не дожидаемой попыткой (`startModelFetch`) —
   * статус её не ждёт ни на этот, ни на следующий тик. */
  async function statusAttempt(id, myGeneration, genSignal, onStatus) {
    const status = await fetchWithTimeout(id, "", statusTimeoutMs, genSignal);
    if (generation !== myGeneration) {
      onStatus?.();
      return;
    }
    const body = status.ok ? status.body : null;
    statusError = status.ok ? null : status;
    if (status.ok && !applicable(body)) modelError = null; // статус стал неприменим — старая ошибка схемы не о нём
    const statusEntry = {
      status: status.ok ? body : entry?.status || null,
      model: entry?.model || null,
      error: statusError || (applicable(body) && sameKey(keyOf(body), modelKey) ? modelError : null),
      modelFresh: modelFresh(status.ok ? body : entry?.status, entry?.model || null),
    };
    const statusChanged = JSON.stringify(statusEntry) !== JSON.stringify(entry);
    entry = statusEntry;
    if (statusChanged) announce(id);
    onStatus?.();
    if (!status.ok) return;
    dropSupersededModel(body);
    if (needsModel(body)) startModelFetch(id, myGeneration, body, genSignal);
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

  /** Новое поколение: всё, что летело для прежнего, обрывается, состояние
   * — с чистого листа; прежний refresh() своего ответа уже не дождётся. */
  function startGeneration(id) {
    generationController?.abort();
    generationController = newController();
    projectId = id;
    generation += 1;
    entry = null;
    statusError = null;
    modelFlight = null;
    modelKey = null;
    modelFailStreak = 0;
    modelWaitTicks = 0;
    modelError = null;
    queued = false;
    releaseWaiters();
  }

  return {
    show(id) {
      if (id !== projectId) startGeneration(id);
    },
    hide() {
      startGeneration(null);
    },
    /** Обычный опрос статуса (таймер, показ экрана): текущее поколение уже
     * опрашивается — просто пропускаем этот раз, следующий будет через
     * POLL_MS. Схему (если она летит) не ждёт и не трогает. */
    tick() {
      if (!projectId) return Promise.resolve();
      if (busyGeneration === generation) return Promise.resolve();
      return runStatus(projectId, generation, generationController?.signal);
    },
    /** Явный запрос (после «Сделать текущей», открытия стола, возврата на
     * вкладку): резолвится, как только придёт СВОЙ ответ статуса — не
     * ждёт схему. Пока летит обычный опрос статуса — не теряем запрос, а
     * сразу следом досдаём ровно один ещё раз и резолвим по его статусу. */
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

/** Что известно о монтаже проекта: `{status, model, error, modelFresh}` или
 * `null`. `modelFresh: false` — показанная схема отстала от статуса (другой
 * index_key), B5 помечает её «обновляется…». */
export function montageState(projectId) {
  return feed.current(projectId);
}

/** Спросить сейчас: после «Сделать текущей», открытия стола, возврата на
 * вкладку. Резолвится по своему статусу — вызывающий код не ждёт схему;
 * экран также слушает `studio:montage-updated` отдельно. */
export function refreshMontage() {
  return feed.refresh();
}
