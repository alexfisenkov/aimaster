// Опрос монтажа, пока открыт экран «Сборка»: дешёвое состояние раз в 5 с
// (только когда вкладка видна), схема слоёв — когда сменился index_key,
// current_version или revision проекта. Каждый опрос — ещё и знак серверу
// «экран смотрят»: стол, открытый дашбордом, не остановится по простою
// (studio/desk_keeper.py). Ядро `createMontageFeed` — без DOM, таймеры
// только свои (таймаут запроса — ниже), его проверяют тесты; обёртка ниже
// вешает таймер опроса и шлёт `studio:montage-updated`.
//
// Показ проекта (show/hide) заводит новое «поколение» со своим
// `AbortController`: у каждой попытки оно своё, снятое в момент запуска.
// Попытка прежнего поколения, чей ответ пришёл уже после переключения,
// тихо бросается — никогда не пишет в entry и никого не ждёт; её запрос
// ещё и обрывается явно (дашборд по HTTP/1.1, у браузера предел — 6
// соединений на хост, копить забытые незачем).
//
// Статус и схема идут раздельно: статус — раз в POLL_MS, коротко; схему
// сервер может считать до 120 с (studio/montage/status_screen.py), и пока
// она считается, статус всё равно опрашивается по расписанию — модель не
// держит его в заложниках. `busyGeneration` — про статус,
// `modelBusyGeneration` — про схему, это два независимых флага.

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
  let generation = 0;
  let generationController = null; // отменяется в show()/hide() — обрывает всё, что летело для прежнего поколения
  let busyGeneration = null;       // статус для этого поколения летит (модель сюда не входит)
  let modelBusyGeneration = null;  // схема для этого поколения летит — отдельно, статус её не ждёт
  let queued = false;              // refresh() позвали, пока статус уже летит — досдать статус сразу после него
  let queuedWaiters = [];          // resolve() тех refresh(), что ждут именно этот добор

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

  /** Схему показываем как актуальную только пока её index_key совпадает с
   * текущим статусом — B5 вешает на `false` подпись «обновляется…». */
  function modelFresh(statusBody, model) {
    return Boolean(model) && Boolean(statusBody) && model.index_key === statusBody.index_key;
  }

  /** Схему просить сейчас — или ключ новый, или прошлая попытка по этому же
   * ключу провалилась и пауза уже кончилась; схема этого поколения уже не
   * летит (иначе второй параллельный запрос той же схемы). */
  function needsModel(status, myGeneration) {
    if (!applicable(status)) return false;
    if (modelBusyGeneration === myGeneration) return false;
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

  /** Один запрос с таймаутом плюс отмена всего поколения: `genSignal` —
   * сигнал контроллера поколения (оборвётся в show()/hide() целиком);
   * свой контроллер на этот же запрос добавляет таймаут. Оба вместе —
   * через `AbortSignal.any`, когда он есть; без него таймаут всё равно
   * работает, просто отмена по поколению не обрывает сам fetch раньше. */
  async function fetchWithTimeout(id, part, ms, genSignal) {
    const requestController = typeof AbortController === "function" ? new AbortController() : null;
    const signal = requestController && typeof AbortSignal !== "undefined" && typeof AbortSignal.any === "function"
      ? AbortSignal.any(genSignal ? [genSignal, requestController.signal] : [requestController.signal])
      : (genSignal || requestController?.signal);
    let timer;
    const timeout = new Promise((resolve) => {
      timer = setTimeout(() => { requestController?.abort(); resolve({ ok: false, code: "timeout" }); }, ms);
    });
    try {
      return await Promise.race([load(id, part, signal), timeout]);
    } finally {
      clearTimeout(timer);
    }
  }

  /** Схема — отдельная, «отвязанная» от статуса попытка: статус её не
   * ждёт (item 1 фикса раунда 3). Пишет в entry и зовёт notify, только
   * если её поколение всё ещё текущее и модель всё ещё относится к
   * последнему известному статусу (иначе более новый статус уже решил,
   * что показывать в error, — не затираем его). */
  function startModelFetch(id, myGeneration, statusBody, genSignal) {
    const key = keyOf(statusBody);
    if (!sameKey(key, modelKey)) modelError = null; // новый ключ — старая ошибка модели больше не о нём
    modelBusyGeneration = myGeneration;
    fetchWithTimeout(id, "model", modelTimeoutMs, genSignal).then((model) => {
      if (modelBusyGeneration === myGeneration) modelBusyGeneration = null;
      if (generation !== myGeneration) return; // поколение сменилось — эта попытка больше никому не нужна
      modelKey = key;
      const failed = model.ok ? modelFailed(model.body) : true;
      modelError = model.ok ? null : model;
      modelFailStreak = failed ? modelFailStreak + 1 : 0;
      modelWaitTicks = failed ? MODEL_RETRY_TICKS[Math.min(modelFailStreak - 1, MODEL_RETRY_TICKS.length - 1)] : 0;
      const currentStatus = entry?.status;
      const stillCurrent = currentStatus && applicable(currentStatus) && sameKey(keyOf(currentStatus), key);
      const nextModel = model.ok ? model.body : entry?.model || null;
      const modelEntry = {
        ...entry,
        model: nextModel,
        error: stillCurrent ? modelError : entry?.error ?? null,
        modelFresh: modelFresh(currentStatus, nextModel),
      };
      if (JSON.stringify(modelEntry) !== JSON.stringify(entry)) {
        entry = modelEntry;
        notify(id);
      }
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
    if (status.ok && !applicable(body)) modelError = null; // статус стал неприменим — старая ошибка схемы не о нём
    const statusEntry = {
      status: status.ok ? status.body : entry?.status || null,
      model: entry?.model || null,
      error: status.ok ? (applicable(body) && sameKey(keyOf(body), modelKey) ? modelError : null) : status,
      modelFresh: modelFresh(status.ok ? body : entry?.status, entry?.model || null),
    };
    const statusChanged = JSON.stringify(statusEntry) !== JSON.stringify(entry);
    entry = statusEntry;
    if (statusChanged) notify(id);
    onStatus?.();
    if (status.ok && needsModel(body, myGeneration)) startModelFetch(id, myGeneration, body, genSignal);
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

  return {
    show(id) {
      if (id !== projectId) {
        generationController?.abort();
        generationController = typeof AbortController === "function" ? new AbortController() : null;
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
      generationController?.abort();
      generationController = null;
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
