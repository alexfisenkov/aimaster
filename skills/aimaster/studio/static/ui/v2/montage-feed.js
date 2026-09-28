// Опрос монтажа, пока открыт экран «Сборка»: дешёвое состояние раз в 5 с
// (только когда вкладка видна), схема слоёв — когда сменился index_key,
// current_version или revision. Каждый опрос — ещё и знак серверу «экран
// смотрят»: стол, открытый дашбордом, не остановится по простою
// (studio/desk_keeper.py). Ядро `createMontageFeed` — без DOM и таймеров,
// его проверяют тесты; обёртка ниже вешает таймер и шлёт
// `studio:montage-updated`.

import { getMontage } from "./montage-api.js";

export const POLL_MS = 5000;

// Сколько тиков пропустить перед повтором схемы, которая пришла с
// model_error/stale_error (движок временно не смог посчитать таймлайн), —
// по числу неудач подряд с этим же ключом: 0 (следующий же тик — 5 с),
// потом 5 (30 с), потом 11 (60 с) — дальше без увеличения.
const MODEL_RETRY_TICKS = [0, 5, 11];

export function createMontageFeed({ load, notify }) {
  let projectId = null;
  let entry = null;
  let busy = false;   // сейчас идёт один опрос — второй параллельно не пускаем
  let queued = false; // refresh() позвали, пока опрос уже летит — досдать сразу после него

  // Ключ, для которого схему в последний раз пробовали спросить: сменился
  // index_key (правка на столе), current_version (собрали новую версию —
  // index.html при этом не трогают, index_key тот же) или revision проекта
  // (снимок изменился) — старая схема могла устареть, спрашиваем заново.
  let modelKey = null;
  let modelFailStreak = 0;
  let modelWaitTicks = 0;

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

  /** Один опрос: дешёвое состояние и, если нужно, схема. `id` берём заново
   * на каждой проверке — если экран уже смотрит другой проект (или снова
   * тот же после другого), писать в его `entry` нечего: show()/hide() его
   * уже сбросили. */
  async function attempt() {
    const id = projectId;
    const status = await load(id, "");
    if (projectId !== id) return;
    const next = { status: status.ok ? status.body : entry?.status || null,
      model: entry?.model || null, error: status.ok ? null : status };
    if (status.ok && needsModel(status.body)) {
      const key = keyOf(status.body);
      const model = await load(id, "model");
      if (projectId !== id) return;
      modelKey = key;
      const failed = model.ok ? modelFailed(model.body) : true;
      if (model.ok) next.model = model.body; else next.error = model;
      modelFailStreak = failed ? modelFailStreak + 1 : 0;
      modelWaitTicks = failed ? MODEL_RETRY_TICKS[Math.min(modelFailStreak - 1, MODEL_RETRY_TICKS.length - 1)] : 0;
    }
    const changed = JSON.stringify(next) !== JSON.stringify(entry);
    entry = next;
    if (changed) notify(id);
  }

  async function run() {
    busy = true;
    try {
      await attempt();
      while (queued) {
        queued = false;
        await attempt();
      }
    } finally {
      busy = false;
    }
  }

  return {
    show(id) {
      if (id !== projectId) {
        projectId = id;
        entry = null;
        modelKey = null;
        modelFailStreak = 0;
        modelWaitTicks = 0;
      }
    },
    hide() {
      projectId = null;
      entry = null;
      modelKey = null;
      modelFailStreak = 0;
      modelWaitTicks = 0;
    },
    /** Обычный опрос (таймер, показ экрана): пока летит другой — просто
     * пропускаем этот раз, следующий будет через POLL_MS. */
    tick() {
      if (!projectId || busy) return Promise.resolve();
      return run();
    },
    /** Явный запрос (после «Сделать текущей», открытия стола, возврата на
     * вкладку): пока летит обычный опрос — не теряем его, а сразу следом
     * досдаём ровно один ещё раз. */
    refresh() {
      if (!projectId) return Promise.resolve();
      if (busy) {
        queued = true;
        return Promise.resolve();
      }
      return run();
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
  load: (id, part) => getMontage(id, part),
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

/** Спросить сейчас: после «Сделать текущей», открытия стола, возврата на вкладку. */
export function refreshMontage() {
  return feed.refresh();
}
