// Shared, DOM-light helpers for asset URLs, time labels and the one broken/
// missing/not-ready placeholder every media surface uses. This is its own
// module -- imported by both ui/media.js (card and reference thumbnails)
// and ui/viewer.js (the lightbox/player) -- specifically so neither of
// those two ever imports the other: media.js asks viewer.js to open by
// dispatching a `studio:open-viewer` DOM event (see media.js's
// `dispatchOpenViewer`) instead of calling it directly, so importing either
// module to reach a pure function never loads the other's DOM-only code as
// a side effect.

/** `65000` -> "01:05". Negative/non-finite input clamps to "00:00". */
export function formatDuration(ms) {
  const totalSeconds = Number.isFinite(ms) && ms > 0 ? Math.floor(ms / 1000) : 0;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  const pad = (value) => String(value).padStart(2, "0");
  return `${pad(minutes)}:${pad(seconds)}`;
}

/** `(0, 7000)` -> "00:00–00:07" (en dash). Content, not a technical field --
 * spec §2 names exact timecodes like this as displayable. */
export function formatSceneRange(startMs, endMs) {
  return `${formatDuration(startMs)}–${formatDuration(endMs)}`;
}

/**
 * Whether `assetUrl` is worth attempting to load at all. A missing/blank
 * url is substituted with a placeholder immediately instead of setting
 * `src=""` and hoping the element's `error` event fires for it -- browsers
 * do not treat an empty `src` consistently. Anything that isn't one of this
 * server's own `/assets/{id}` paths (spec §8: the server never hands out a
 * filesystem path or an external URL) is treated the same way.
 */
export function hasLoadableAsset(assetUrl) {
  return typeof assetUrl === "string" && assetUrl.startsWith("/assets/");
}

function disposeMediaElement(element) {
  if (!element) return;
  if (typeof element.pause === "function") element.pause();
  element.removeAttribute("src");
  if (typeof element.load === "function") element.load();
}

/** Keep native media elements alive across a synchronous full-step repaint. */
export function createPersistentMediaPool(createElement) {
  const slots = new Map();
  let observing = false;
  const pauseDisconnected = () => {
    for (const entry of slots.values()) {
      if (!entry.element.isConnected && typeof entry.element.pause === "function") {
        entry.element.pause();
      }
    }
  };
  return {
    acquire(slot, descriptor) {
      const existing = slots.get(slot);
      if (existing?.descriptor === descriptor) return existing.element;
      if (existing) disposeMediaElement(existing.element);
      const element = createElement();
      slots.set(slot, { descriptor, element });
      return element;
    },
    observe(root = document?.body) {
      if (observing || typeof MutationObserver !== "function" || !root) return;
      observing = true;
      new MutationObserver(pauseDisconnected).observe(root, { childList: true, subtree: true });
    },
    pauseDisconnected,
    values() {
      return [...slots.values()].map((entry) => entry.element);
    },
  };
}

/**
 * Mark `node` (a placeholder just substituted for a broken/missing asset)
 * with a diagnosable signal and notify listeners with the asset's id --
 * without logging anything to the console (an expected, handled failure is
 * not console noise). The dispatch is deferred one microtask so a
 * placeholder built before its card is attached to the live document (the
 * "no loadable URL at all" path, decided synchronously) still bubbles to a
 * document-level listener the same way the asynchronous load/decode-failure
 * paths already do by the time *they* fire.
 */
export function markAssetError(node, assetId) {
  const id = typeof assetId === "string" && assetId ? assetId : "unknown";
  node.dataset.assetError = id;
  queueMicrotask(() => {
    node.dispatchEvent(
      new CustomEvent("studio:asset-error", {
        bubbles: true,
        detail: { assetId: id === "unknown" ? undefined : id },
      }),
    );
  });
}

/**
 * The one placeholder node every broken/missing/not-ready-yet thumbnail
 * uses -- media.js's cards and viewer.js's lightbox/player both render this
 * same shape via this one builder, instead of each keeping its own
 * near-identical copy.
 */
export function buildAssetPlaceholder(message) {
  const placeholder = document.createElement("div");
  placeholder.className = "media-placeholder";
  placeholder.setAttribute("role", "img");
  placeholder.setAttribute("aria-label", message);
  const text = document.createElement("p");
  text.textContent = message;
  placeholder.append(text);
  return placeholder;
}
