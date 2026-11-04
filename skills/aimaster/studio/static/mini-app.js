// Telegram Mini App adapter. The ordinary local dashboard remains unchanged;
// inside Telegram this adds the validated initData to same-origin API calls.
//
// Repair, 2026-09-21: the mode used to be detected with a strict
// `location.hash === "#mini-app"`, which never matches a real Telegram
// launch. Telegram clients append their own launch parameters to the
// fragment of the `web_app` URL, and telegram.org's own SDK documents the
// rule in `urlAppendHashParams`: a URL that already ends in `#mini-app`
// comes back as `#mini-app?tgWebAppData=...`, and a fragment that already
// contains `=` gets `&tgWebAppData=...`. A bare `#mini-app` therefore only
// ever exists in a hand-typed URL. With the strict comparison the adapter
// stayed off inside Telegram: no Authorization header was attached, every
// `/api/*` call answered 403, and the dashboard sat on "Не удалось
// загрузить проект" with nothing pointing at Telegram. The fragment is now
// parsed the way the SDK parses it -- everything before `?` is the "path"
// (our own `mini-app` marker), the rest are parameters (`tgWebApp*`).
(() => {
  const rawHash = String(location.hash || "").replace(/^#/, "");
  const separator = rawHash.indexOf("?");
  // Same rule as the SDK: a fragment without `?` but with `=` is all
  // parameters (`#tgWebAppData=...` when the menu URL had no fragment).
  const paramsOnly = separator < 0 && rawHash.includes("=");
  const hashPath = separator < 0 ? (paramsOnly ? "" : rawHash) : rawHash.slice(0, separator);
  const hashParams = new URLSearchParams(
    separator < 0 ? (paramsOnly ? rawHash : "") : rawHash.slice(separator + 1)
  );
  const webApp = globalThis.Telegram && globalThis.Telegram.WebApp;
  // Three independent signals, because a client may keep our marker, drop
  // it, or (after an in-WebView reload) hand the SDK its launch parameters
  // back out of sessionStorage with no fragment left at all. Outside
  // Telegram `initData` is always an empty string, so the ordinary
  // `http://127.0.0.1:<port>/` dashboard still takes none of these.
  const miniMode =
    hashPath.split("&").includes("mini-app") ||
    hashParams.has("tgWebAppData") ||
    Boolean(webApp && webApp.initData);
  if (!miniMode) return;

  let notice;
  const showError = (message) => {
    const first = !notice;
    if (!notice) {
      notice = document.createElement("div");
      notice.style.cssText = "position:fixed;inset:16px auto auto 16px;right:16px;padding:16px;border-radius:12px;background:#fff3cd;color:#5d4500;font:15px -apple-system,BlinkMacSystemFont,sans-serif;z-index:9999";
      notice.setAttribute?.("role", "alert");
    }
    notice.textContent = message;
    if (first) document.body.prepend(notice);
    if (notice.appendChild) {
      const retry = document.createElement("button");
      retry.type = "button";
      retry.textContent = "Повторить / Retry";
      retry.style.minHeight = "44px";
      retry.addEventListener("click", () => location.reload());
      notice.appendChild(retry);
    }
  };

  if (!webApp || !webApp.initData) {
    showError(webApp
      ? "Mini App не получила данные Telegram. Закройте окно и откройте AI Мастерскую из меню бота ещё раз."
      : "Mini App не смогла загрузить Telegram SDK (telegram.org). Проверьте соединение и откройте AI Мастерскую из меню бота ещё раз.");
    return;
  }
  webApp.ready();
  const originalFetch = globalThis.fetch.bind(globalThis);
  globalThis.fetch = async (input, init = {}) => {
    const requestInit = { ...init, headers: new Headers(init.headers || input?.headers || {}) };
    // `input` is a string everywhere in this dashboard, but a URL object or
    // a Request must not throw here either -- an exception in this wrapper
    // would take down every fetch on the page, which is the one failure
    // mode that really does leave a blank screen.
    let url = null;
    try {
      const raw = typeof input === "string" || input instanceof URL ? input : input.url;
      url = new URL(raw, location.href);
    } catch {
      url = null;
    }
    if (url && url.origin === location.origin) {
      requestInit.headers.set("Authorization", `tma ${webApp.initData}`);
    }
    try {
      const response = await originalFetch(input, requestInit);
      if (url && url.origin === location.origin && response.status === 403) {
        showError("Telegram-вход недействителен или устарел. Откройте приложение из меню своего бота снова. / Telegram authentication expired; reopen from your bot.");
      }
      return response;
    } catch (error) {
      if (url && url.origin === location.origin) {
        showError("Нет связи с компьютером. Проверьте подключение и повторите. Можно продолжить текстом в боте. / Computer unavailable; retry or use bot text.");
      }
      throw error;
    }
  };
})();
