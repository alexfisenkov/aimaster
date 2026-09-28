// Когда спрашивать схему слоёв (`…/montage/model`) — чистые правила без
// сети и таймеров (для montage-feed-core.js). Ключ схемы — index_key
// (правка на столе), current_version (собрали новую версию — index.html при
// этом не трогают) и revision проекта (снимок изменился): сменился любой —
// старая схема могла устареть. Отказ и счёт неудач всегда про последний
// ключ, по которому схема ответила (`key`).

// Сколько тиков пропустить перед повтором схемы, которая пришла с ошибкой
// (сетевой отказ, таймаут или model_error/stale_error в теле — движок
// временно не смог посчитать таймлайн), — по числу неудач подряд с этим же
// ключом: 0 (следующий же тик — 5 с), потом 5 (30 с), потом 11 (60 с) —
// дальше без увеличения.
export const MODEL_RETRY_TICKS = [0, 5, 11];

export function keyOf(body) {
  return { index_key: body.index_key, current_version: body.current_version, revision: body.revision };
}

export function sameKey(a, b) {
  return Boolean(a) && Boolean(b) && a.index_key === b.index_key
    && a.current_version === b.current_version && a.revision === b.revision;
}

/** Схема вообще нужна: видео или смешанный проект, черновик есть, движок стоит. */
export function applicable(body) {
  return Boolean(body) && body.applicable !== false && body.exists === true
    && body.engine?.state === "installed";
}

export function modelFailed(body) {
  return !body || Boolean(body.model_error) || Boolean(body.stale_error);
}

export function createModelTracker() {
  let key = null;      // последний ключ, по которому схема ответила
  let failStreak = 0;
  let waitTicks = 0;
  let error = null;    // отказ запроса схемы для `key` — держим между попытками, не мигаем им
  let flight = null;   // ключ схемы, что летит сейчас

  /** Ключ новый — или прошлая попытка по нему провалилась и пауза кончилась. */
  function due(next) {
    if (!sameKey(next, key)) return true;
    if (failStreak === 0) return false;
    if (waitTicks > 0) {
      waitTicks -= 1;
      return false;
    }
    return true;
  }

  return {
    get key() { return key; },
    get error() { return error; },
    get flight() { return flight; },
    /** Удачный статус текущего поколения → что делать со схемой:
     * `start` — спросить (`flight` уже её ключ), `keep` — одна уже летит,
     * `idle` — не нужна; `restart`/`drop` — летящая схема прежнего ключа
     * вытеснена (оборвать её), и новую спросить / не спрашивать. */
    onStatus(body) {
      if (!applicable(body)) {
        error = null; // статус стал неприменим — старая ошибка схемы не о нём
        return flight ? "keep" : "idle";
      }
      const next = keyOf(body);
      const dropped = Boolean(flight) && !sameKey(flight, next);
      if (dropped) flight = null;
      if (flight) return "keep";
      if (!due(next)) return dropped ? "drop" : "idle";
      flight = next;
      return dropped ? "restart" : "start";
    },
    /** Схема для `resultKey` ответила (`{ok, body}` или отказ). */
    onResult(resultKey, result) {
      flight = null;
      const failed = result.ok ? modelFailed(result.body) : true;
      const streak = sameKey(resultKey, key) ? failStreak : 0; // новый ключ — прошлых неудач для него ещё не было
      key = resultKey;
      error = result.ok ? null : result;
      failStreak = failed ? streak + 1 : 0;
      waitTicks = failed ? MODEL_RETRY_TICKS[Math.min(failStreak - 1, MODEL_RETRY_TICKS.length - 1)] : 0;
      return "idle";
    },
    reset() {
      key = null;
      failStreak = 0;
      waitTicks = 0;
      error = null;
      flight = null;
    },
  };
}
