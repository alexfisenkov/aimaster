// Telegram Mini App adapter. The ordinary local dashboard remains unchanged;
// inside Telegram this adds the validated initData to same-origin API calls.
(() => {
  const webApp = globalThis.Telegram && globalThis.Telegram.WebApp;
  if (!webApp || !webApp.initData) return;
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
