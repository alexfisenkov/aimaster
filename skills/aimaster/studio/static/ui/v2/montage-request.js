// Один запрос экрана «Сборка» (для montage-feed-core.js): свой контроллер,
// таймаут и отмена вместе со всем поколением показа. Сигнал поколения
// пересылается в контроллер запроса вручную — `AbortSignal.any` нет в
// Safari/iOS < 17.4, Chrome и Android WebView < 116, Firefox < 124, а это и
// Mini App в Telegram на iPhone постарше. Обрывать надо всерьёз: дашборд по
// HTTP/1.1, у браузера предел — 6 соединений на хост.

export function newController() {
  return typeof AbortController === "function" ? new AbortController() : null;
}

/** `load(id, part, signal)` с таймаутом `ms`. Запрос обрывают таймаут и
 * отмена поколения (`genSignal`); подписка на поколение снимается, как
 * только запрос кончился — поколение переживает много опросов. `controller`
 * можно передать свой, чтобы оборвать запрос снаружи. Никогда не бросает:
 * сбой самого `load` — это `network_error`, как у `getMontage` при обрыве. */
export async function requestWithTimeout(load, id, part, { ms, genSignal = null, controller = newController() } = {}) {
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
