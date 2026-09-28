// Один запрос экрана «Сборка» (для montage-feed-core.js): свой контроллер,
// таймаут и отмена вместе со всем поколением показа. Сигнал поколения
// пересылается в контроллер запроса вручную — `AbortSignal.any` нет в
// Safari/iOS < 17.4, Chrome и Android WebView < 116, Firefox < 124, а это и
// Mini App в Telegram на iPhone постарше. Обрывать надо всерьёз: дашборд по
// HTTP/1.1, у браузера предел — 6 соединений на хост.

export function newController() {
  return typeof AbortController === "function" ? new AbortController() : null;
}

/** `load(id, part, signal)` с таймаутом `ms` и отменой по `genSignal`
 * (поколение показа). Отмена сама заканчивает запрос — не ждёт, пока `load`
 * заметит обрыв: таймер снят, подписка на поколение снята (поколение
 * переживает много опросов), сигнал `load` оборван. Ответ всегда
 * `{ok, …}`, промис никогда не отказывает:
 * - ответ `load`; его сбой или отказ — `network_error`, как у `getMontage`;
 * - `timeout` — `ms` прошло; `aborted` — поколение сменилось (такой ответ
 *   ядро выбрасывает, не показывая). */
export function requestWithTimeout(load, id, part, { ms, genSignal = null } = {}) {
  return new Promise((resolve) => {
    if (genSignal?.aborted) {
      resolve({ ok: false, code: "aborted" });
      return;
    }
    const controller = newController();
    let open = true;
    let timer = null;
    const finish = (result) => {
      if (!open) return;
      open = false;
      clearTimeout(timer);
      genSignal?.removeEventListener("abort", onGenerationAbort);
      resolve(result);
    };
    // Сначала ответ, потом обрыв: обрыв может синхронно закончить `load`
    // своим network_error — побеждает причина отмены.
    const cancel = (result) => {
      finish(result);
      controller?.abort();
    };
    function onGenerationAbort() {
      cancel({ ok: false, code: "aborted" });
    }
    genSignal?.addEventListener("abort", onGenerationAbort, { once: true });
    timer = setTimeout(() => cancel({ ok: false, code: "timeout" }), ms);
    const failed = () => finish({ ok: false, code: "network_error" });
    try {
      Promise.resolve(load(id, part, controller?.signal)).then(finish, failed);
    } catch {
      failed();
    }
  });
}
