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

  if (!webApp || !webApp.initData) {
    const notice = document.createElement("div");
    notice.textContent = webApp
      ? "Mini App не получила данные Telegram. Закройте окно и откройте AI Мастерскую из меню бота ещё раз."
      : "Mini App не смогла загрузить Telegram SDK (telegram.org). Проверьте соединение и откройте AI Мастерскую из меню бота ещё раз.";
    notice.style.cssText = "position:fixed;inset:16px auto auto 16px;right:16px;padding:16px;border-radius:12px;background:#fff3cd;color:#5d4500;font:15px -apple-system,BlinkMacSystemFont,sans-serif;z-index:9999";
    document.body.prepend(notice);
    return;
  }
  webApp.ready();
  const originalFetch = globalThis.fetch.bind(globalThis);
  globalThis.fetch = (input, init = {}) => {
    const requestInit = { ...init, headers: new Headers(init.headers || {}) };
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
    return originalFetch(input, requestInit);
  };
})();
