// Telegram Mini App adapter. The ordinary local dashboard remains unchanged;
// inside Telegram this adds the validated initData to same-origin API calls.
(() => {
  const miniMode = location.hash === "#mini-app";
  if (!miniMode) return;
  const webApp = globalThis.Telegram && globalThis.Telegram.WebApp;
  if (!webApp || !webApp.initData) {
    const notice = document.createElement("div");
    notice.textContent = "Mini App не получила данные Telegram. Закройте окно и откройте AI Мастерскую из меню бота ещё раз.";
    notice.style.cssText = "position:fixed;inset:16px auto auto 16px;right:16px;padding:16px;border-radius:12px;background:#fff3cd;color:#5d4500;font:15px -apple-system,BlinkMacSystemFont,sans-serif;z-index:9999";
    document.body.prepend(notice);
    return;
  }
  webApp.ready();
  const originalFetch = globalThis.fetch.bind(globalThis);
  globalThis.fetch = (input, init = {}) => {
    const requestInit = { ...init, headers: new Headers(init.headers || {}) };
    const url = typeof input === "string" ? new URL(input, location.href) : new URL(input.url);
    if (url.origin === location.origin) {
      requestInit.headers.set("Authorization", `tma ${webApp.initData}`);
    }
    return originalFetch(input, requestInit);
  };
})();
