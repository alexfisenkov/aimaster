// Когда спрашивать схему слоёв (`…/montage/model`) — чистые правила без
// сети и таймеров (для montage-feed-core.js). Ключ схемы — index_key
// (правка на столе), current_version (собрали новую версию — index.html при
// этом не трогают) и revision проекта (снимок изменился): сменился любой —
// старая схема могла устареть. Отказ и счёт неудач всегда про последний
// ключ, по которому схема ответила (`key`).
//
// Схема летит одна: сервер считает их по очереди (одна на проект за раз) и
// брошенный клиентом запрос не отменяет — оборвать схему ради нового ключа
// значит поставить в очередь сервера ещё один счёт и не показать ни одной
// схемы, пока человек правит. Поэтому новый ключ ждёт, пока летящая схема
// ляжет, — её показывают (пусть и не свежей), и тут же спрашивают следующую.

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
  let latest = null;   // ключ последнего применимого статуса (null — статус неприменим)

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
    get latest() { return latest; },
    /** Удачный статус текущего поколения → что делать со схемой: `start` —
     * спросить (`flight` уже её ключ), `keep` — одна уже летит (новый ключ
     * спросят, когда она ляжет), `idle` — не нужна. */
    onStatus(body) {
      if (!applicable(body)) {
        latest = null;
        error = null; // статус стал неприменим — старая ошибка схемы не о нём
        return flight ? "keep" : "idle";
      }
      latest = keyOf(body);
      if (flight) return "keep";
      if (!due(latest)) return "idle";
      flight = latest;
      return "start";
    },
    /** Схема для `resultKey` ответила (`{ok, body}` или отказ): `start` —
     * статус уже ушёл на другой ключ, спросить его сразу (`flight` — он),
     * иначе `idle`. Флаг полёта снимается первым делом, при любом исходе. */
    onResult(resultKey, result) {
      flight = null;
      const failed = result.ok ? modelFailed(result.body) : true;
      const streak = sameKey(resultKey, key) ? failStreak : 0; // новый ключ — прошлых неудач для него ещё не было
      key = resultKey;
      error = result.ok ? null : result;
      failStreak = failed ? streak + 1 : 0;
      waitTicks = failed ? MODEL_RETRY_TICKS[Math.min(failStreak - 1, MODEL_RETRY_TICKS.length - 1)] : 0;
      if (!latest || sameKey(latest, resultKey)) return "idle";
      flight = latest;
      return "start";
    },
    reset() {
      key = null;
      failStreak = 0;
      waitTicks = 0;
      error = null;
      flight = null;
      latest = null;
    },
  };
}
