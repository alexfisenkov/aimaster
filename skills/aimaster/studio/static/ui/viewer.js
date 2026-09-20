// Accessible photo lightbox and native video player, opened by any media
// card media.js builds. The overlay is built fresh on every open and fully
// torn down (removed from `document.body`, not merely hidden) on every
// close: this file's zone may only wire `<link>`/`<script>` tags into
// index.html, never add new markup there, so the overlay still has to be
// created from script, but it never lingers as stale, closed-but-present
// markup once the viewer is dismissed (spec §2.1) -- closing it leaves no
// media markup, buttons or captions in the DOM at all, not merely hidden
// ones.
//
// Contract (interfaces.md, ticket 07): `openImageViewer(asset, trigger)`,
// `openVideoViewer(asset, scene, trigger)`, `closeViewer()`. Neither viewer
// ever enqueues an action -- there is no approve/reject/vary control here,
// only viewing. This module never imports media.js -- a card asks it to
// open by dispatching a bubbling `studio:open-viewer` DOM event instead
// (media.js's `dispatchOpenViewer`), which `attachViewerOpenListener` below
// picks up once wired from app.js. Escape, the backdrop and the close
// button all close the same way and return focus to `trigger`, the element
// that opened the viewer -- or, when a snapshot repaint has replaced that
// exact element while the viewer was open, to the freshly-painted card
// carrying the same `data-result-id`/`data-prompt-id`/`data-reference-id`
// and, when the original card had one, the same `data-version-id`.
//
// Real decode is confirmed before the media counts as displayed (spec §8):
// images use `HTMLImageElement.decode()`, which rejects on a corrupt or
// unservable file even when the HTTP request itself succeeded; video relies
// on the element's own `error` event -- there is no video equivalent of
// `decode()`'s reject-on-corrupt-data promise, so this is the one signal
// this module has. Either failure swaps in a safe, diagnosable placeholder
// without touching any other card.
//
// Repair, 2026-09-17 (ticket 06 amendment 6/condition 6). The video player
// now carries its own "Перейти к сцене" toolbar button, shown whenever
// `openVideoViewer`'s `scene` names a real `scene_id` -- previously the
// only way back to the scenario was a card's own `.media-scene-tag-button`
// (ui/media.js's `buildSceneTag`), which stays as the *other* way in but
// left the player itself with no such control. Clicking it closes the
// viewer, selects the scene through the same shared
// `requestSceneSelection` every other trigger uses, and moves focus to
// that scene's block in the scenario -- deliberately *not* wherever
// `closeViewer`'s own focus-return would otherwise land (the card that
// opened the player), since the whole point of the control is to leave
// the player for the scenario, not back to the gallery.

import {
  formatSceneRange,
  hasLoadableAsset,
  markAssetError,
  buildAssetPlaceholder,
} from "./media-asset.js";
import { requestSceneSelection } from "./timeline.js";

let overlayRefs = null;

// Elements a Tab/Shift+Tab cycle should stop on while the dialog is open.
// The native <video controls> element is itself one stop; its internal
// scrubber/play/volume controls are the browser's own focus management, not
// ours to trap.
function focusableInDialog(dialog) {
  return Array.from(
    dialog.querySelectorAll('button, [href], video, audio, [tabindex]:not([tabindex="-1"])'),
  ).filter((el) => !el.hidden && el.tabIndex !== -1);
}

function trapTabKey(event, dialog) {
  if (event.key !== "Tab") {
    return;
  }
  const focusable = focusableInDialog(dialog);
  if (focusable.length === 0) {
    return;
  }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  const active = document.activeElement;
  if (!dialog.contains(active)) {
    // Focus already escaped the dialog -- typically to `<body>`, left there
    // by a real click on a non-focusable element inside it (see
    // `buildOverlay`'s listener comment below). Tab must still stay inside
    // the dialog, not resume the page's own tab order from wherever focus
    // currently sits.
    event.preventDefault();
    (event.shiftKey ? last : first).focus();
    return;
  }
  if (event.shiftKey && active === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && active === last) {
    event.preventDefault();
    first.focus();
  }
}

function buildOverlay() {
  // Captured before anything below moves focus, so it is genuinely "what
  // had focus right before this viewer opened" -- the fallback closeViewer
  // uses when the trigger cannot be re-found (see resolveFocusTarget and
  // closeViewer below).
  const previousActiveElement =
    document.activeElement instanceof HTMLElement ? document.activeElement : null;

  const overlay = document.createElement("div");
  overlay.className = "media-viewer-overlay";
  overlay.dataset.hook = "media-viewer";
  overlay.hidden = true;

  const backdrop = document.createElement("button");
  backdrop.type = "button";
  backdrop.className = "media-viewer-backdrop";
  backdrop.dataset.hook = "media-viewer-backdrop";
  // Decorative click target only -- the dialog below carries the real
  // accessible name and content; a second name here would be redundant.
  backdrop.setAttribute("aria-hidden", "true");
  backdrop.tabIndex = -1;
  backdrop.addEventListener("click", () => closeViewer());

  const dialog = document.createElement("div");
  dialog.className = "media-viewer-dialog";
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");

  const toolbar = document.createElement("div");
  toolbar.className = "media-viewer-toolbar";

  const zoomButton = document.createElement("button");
  zoomButton.type = "button";
  zoomButton.className = "media-viewer-zoom";
  zoomButton.dataset.hook = "media-viewer-zoom";
  zoomButton.hidden = true;
  zoomButton.textContent = "Увеличить";
  zoomButton.addEventListener("click", () => toggleZoom());

  const goToSceneButton = document.createElement("button");
  goToSceneButton.type = "button";
  goToSceneButton.className = "media-viewer-go-to-scene";
  goToSceneButton.dataset.hook = "media-viewer-go-to-scene";
  goToSceneButton.hidden = true;
  goToSceneButton.textContent = "Перейти к сцене";
  goToSceneButton.addEventListener("click", () => goToScene());

  const closeButton = document.createElement("button");
  closeButton.type = "button";
  closeButton.className = "media-viewer-close";
  closeButton.dataset.hook = "media-viewer-close";
  closeButton.textContent = "Закрыть";
  closeButton.addEventListener("click", () => closeViewer());

  toolbar.append(zoomButton, goToSceneButton, closeButton);

  const body = document.createElement("div");
  body.className = "media-viewer-body";
  body.dataset.hook = "media-viewer-body";

  const caption = document.createElement("p");
  caption.className = "media-viewer-caption";
  caption.dataset.hook = "media-viewer-caption";

  dialog.append(toolbar, body, caption);
  overlay.append(backdrop, dialog);
  document.body.append(overlay);

  // Listens on `document`, not `overlay`: a real mouse click on a
  // non-focusable element inside the dialog (the image, the caption, the
  // body background) blurs whatever previously held focus and moves
  // `document.activeElement` to `<body>` -- the browser's default mousedown
  // behavior for a target that isn't itself focusable. A keydown then
  // targets `<body>` and bubbles to `document`, never reaching a listener
  // attached only to `overlay` -- so Escape and Tab would silently stop
  // working after exactly that click. Removed again in `closeViewer`.
  const handleDocumentKeydown = (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      closeViewer();
      return;
    }
    trapTabKey(event, dialog);
  };
  document.addEventListener("keydown", handleDocumentKeydown);

  return {
    overlay,
    dialog,
    toolbar,
    zoomButton,
    goToSceneButton,
    closeButton,
    body,
    caption,
    handleDocumentKeydown,
    previousActiveElement,
  };
}

function ensureOverlay() {
  if (!overlayRefs) {
    overlayRefs = buildOverlay();
  }
  return overlayRefs;
}

/**
 * Whether zooming an image has anywhere real to go, and the pixel size to
 * grow to when it does. `displayedWidth`/`displayedHeight` are the size the
 * browser is currently rendering the image at -- already clamped by
 * `max-width:100%`/`max-height:70vh` -- and `naturalWidth`/`naturalHeight`
 * are its real pixel dimensions. When the image is already shown at (the
 * clamps above only ever shrink it, never enlarge it, so it can never be
 * shown *bigger* than natural) its full native size, growing further would
 * mean upscaling past the source's own resolution -- not real zoom, just
 * blur -- so `canGrow` is `false` and callers hide the "Увеличить" control
 * entirely rather than offer a zoom that visibly does nothing (an already-
 * small e.g. 640x360 image is exactly this case). Otherwise the target is
 * the natural size itself: always bigger than the (necessarily smaller, or
 * `canGrow` would be false) displayed size, so the zoomed image reliably
 * exceeds its container -- `.media-viewer-body`'s own `overflow:auto` makes
 * the excess scrollable -- unlike the previous `width:180%` CSS rule, whose
 * percentage resolved against `.media-viewer-body`'s auto (shrink-to-fit)
 * width and so could not guarantee any growth at all (see
 * styles/media.css). Pure and DOM-free: the caller measures the live image
 * and passes plain numbers in.
 */
export function resolveZoomTarget({ naturalWidth, naturalHeight, displayedWidth, displayedHeight }) {
  const hasNatural =
    Number.isFinite(naturalWidth) && naturalWidth > 0 &&
    Number.isFinite(naturalHeight) && naturalHeight > 0;
  const hasDisplayed =
    Number.isFinite(displayedWidth) && displayedWidth > 0 &&
    Number.isFinite(displayedHeight) && displayedHeight > 0;
  if (!hasNatural || !hasDisplayed) {
    return { canGrow: false };
  }
  const canGrow = naturalWidth > displayedWidth || naturalHeight > displayedHeight;
  if (!canGrow) {
    return { canGrow: false };
  }
  return { canGrow: true, width: naturalWidth, height: naturalHeight };
}

function toggleZoom() {
  if (!overlayRefs) {
    return;
  }
  const img = overlayRefs.body.querySelector("img");
  if (!img) {
    return;
  }
  const zoomed = img.dataset.zoomed === "true";
  if (!zoomed) {
    const width = Number(img.dataset.zoomWidth);
    const height = Number(img.dataset.zoomHeight);
    if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
      // Nothing real to grow to -- the button should already be hidden in
      // this case (see openImageViewer's configureZoom), but a stale/
      // programmatic click must still never fake a zoom.
      return;
    }
    // A fixed pixel target, not the old CSS percentage -- see
    // resolveZoomTarget's doc comment for why a percentage here cannot
    // guarantee growth.
    img.style.width = `${width}px`;
    img.style.height = `${height}px`;
  } else {
    img.style.removeProperty("width");
    img.style.removeProperty("height");
  }
  img.dataset.zoomed = String(!zoomed);
  overlayRefs.zoomButton.textContent = zoomed ? "Увеличить" : "Уменьшить";
  overlayRefs.zoomButton.setAttribute("aria-pressed", String(!zoomed));
}

// The three group-identity attributes a viewer trigger's card can carry,
// checked in this order, plus (separately) `data-version-id` when the card
// has one. Together these let `closeViewer` re-find "the same card" after a
// snapshot repaint has replaced the original trigger element -- and, for a
// card that is one specific version among several sharing the same group id
// (an image/video result, a prompt entry), re-find that exact version, not
// merely the first card that happens to share the group id.
const TRIGGER_GROUP_ID_ATTRS = [
  ["resultId", "data-result-id"],
  ["promptId", "data-prompt-id"],
  ["referenceId", "data-reference-id"],
];

/** Capture, at open time, a stable descriptor for the real snapshot id(s)
 * `trigger`'s card carries -- `null` when it carries none of the three group
 * ids (nothing to re-find later; closeViewer then simply skips refocus).
 * `versionAttr`/`versionValue` are set only when the same card also has
 * `data-version-id` (reference cards never do). */
function describeTrigger(trigger) {
  if (!(trigger instanceof HTMLElement)) {
    return null;
  }
  const position = trigger.closest('[data-hook="position-card"]');
  if (position?.dataset.positionId) {
    return { attrName: "data-position-id", value: position.dataset.positionId,
      versionAttr: null, versionValue: null, controlAction: trigger.dataset.action || "open" };
  }
  const card = trigger.closest("[data-result-id],[data-prompt-id],[data-reference-id]");
  if (!card) {
    return null;
  }
  for (const [datasetKey, attrName] of TRIGGER_GROUP_ID_ATTRS) {
    const value = card.dataset[datasetKey];
    if (value) {
      const versionValue = card.dataset.versionId;
      return {
        attrName,
        value,
        versionAttr: versionValue ? "data-version-id" : null,
        versionValue: versionValue || null,
      };
    }
  }
  return null;
}

/** Whether `.focus()` on `el` would actually move focus there. Naturally
 * focusable elements (button, a[href], input, a `<video controls>`, ...)
 * and anything carrying an explicit non-negative `tabindex` read a
 * `tabIndex` of 0 or more; a plain, non-interactive element -- e.g. the
 * bare `<li>`/`<span>` a card is built from, if something other than the
 * usual `<button>` ever dispatches `studio:open-viewer` as its `target` --
 * reads -1, same as anything already removed from the document. Calling
 * `.focus()` on a -1 element is a silent no-op, which is exactly the bug
 * this guards against: `resolveFocusTarget`'s caller must not report such
 * an element as a valid target, or focus quietly ends up on `<body>`. */
function isFocusable(el) {
  return el instanceof HTMLElement && document.contains(el) && el.tabIndex >= 0;
}

/** The element focus should return to on close: `trigger` itself when it is
 * still attached *and* actually focusable (the common case), or -- when a
 * repaint has replaced it, or it was never focusable to begin with -- the
 * button inside whichever live card now carries the same group id *and*,
 * when the original card had one, the same `data-version-id`. A group id
 * alone is not enough to pick the right card when several versions share
 * it, so the version id (when the descriptor has one) is a second,
 * required match, not an optional refinement. `null` when neither is
 * available, in which case `closeViewer` falls back to whatever held focus
 * right before the viewer opened (`previousActiveElement`) rather than
 * guessing -- never `trigger` itself when it cannot actually take focus. */
function resolveFocusTarget(trigger, descriptor) {
  if (isFocusable(trigger)) {
    return trigger;
  }
  if (!descriptor || typeof CSS === "undefined" || typeof CSS.escape !== "function") {
    return null;
  }
  let selector = `[${descriptor.attrName}="${CSS.escape(descriptor.value)}"]`;
  if (descriptor.versionAttr) {
    selector += `[${descriptor.versionAttr}="${CSS.escape(descriptor.versionValue)}"]`;
  }
  const card = document.querySelector(selector);
  if (!card) {
    return null;
  }
  return descriptor.controlAction
    ? card.querySelector(`[data-hook="card-control"][data-action="${CSS.escape(descriptor.controlAction)}"]`)
    : card.querySelector("button") || card;
}

function openOverlay({ dialogLabel, captionText, trigger, kind }) {
  const refs = ensureOverlay();
  refs.overlay.__triggerEl = trigger instanceof HTMLElement ? trigger : null;
  refs.overlay.__triggerDescriptor = describeTrigger(trigger);
  // Reset on every open, not only for the "video with a scene" case that
  // sets it: an image viewer (or a video with no linked scene) must never
  // keep a *previous* video's scene id lying around in this shared,
  // reused overlay.
  refs.overlay.__sceneId = null;
  refs.dialog.setAttribute("aria-label", dialogLabel);
  refs.dialog.dataset.kind = kind;
  // Hidden until openImageViewer's decode handler confirms (via
  // resolveZoomTarget) there is somewhere real to grow to -- never shown
  // merely because kind is "image".
  refs.zoomButton.hidden = true;
  refs.zoomButton.setAttribute("aria-pressed", "false");
  refs.zoomButton.textContent = "Увеличить";
  // Hidden until openVideoViewer confirms a real scene id below -- never
  // shown for an image, or a video whose result carries no scene link.
  refs.goToSceneButton.hidden = true;
  refs.caption.textContent = captionText || "";
  refs.overlay.hidden = false;
  refs.closeButton.focus();
}

/**
 * Open the accessible photo lightbox for `asset`
 * (`{assetUrl, caption?, assetId?}`). `trigger` is the element that opened
 * the viewer and regains focus on close. Real pixel decode is confirmed
 * with `decode()`; a corrupt/unservable/missing asset swaps in a
 * placeholder without leaving the viewer in a broken state, and reports it.
 */
export function openImageViewer(asset, trigger) {
  const assetUrl = asset && typeof asset.assetUrl === "string" ? asset.assetUrl : "";
  const assetId = asset && typeof asset.assetId === "string" ? asset.assetId : undefined;
  const captionText = asset && typeof asset.caption === "string" ? asset.caption : "";
  openOverlay({
    dialogLabel: captionText || "Просмотр изображения",
    captionText,
    trigger,
    kind: "image",
  });
  const refs = overlayRefs;
  refs.body.textContent = "";

  if (!hasLoadableAsset(assetUrl)) {
    const placeholder = buildAssetPlaceholder("Не удалось загрузить изображение");
    refs.body.append(placeholder);
    refs.zoomButton.hidden = true;
    markAssetError(placeholder, assetId);
    return;
  }

  const showFailure = () => {
    refs.body.textContent = "";
    const placeholder = buildAssetPlaceholder("Не удалось загрузить изображение");
    refs.body.append(placeholder);
    refs.zoomButton.hidden = true;
    markAssetError(placeholder, assetId);
  };

  const img = document.createElement("img");
  img.alt = "";
  img.className = "media-viewer-image";
  // The cursor's zoom-in/zoom-out affordance (styles/media.css) is only
  // ever correct when a click really does zoom -- so the image itself
  // toggles zoom too, not only the toolbar button. This is a plain,
  // non-focusable click target, so a real mouse click here moves
  // `document.activeElement` to `<body>` (the browser's default mousedown
  // behavior for a target that isn't itself focusable) -- `buildOverlay`'s
  // document-level keydown listener and `trapTabKey`'s "focus escaped the
  // dialog" branch both account for that, so clicking anywhere on the image
  // still leaves Escape and Tab working correctly.
  img.addEventListener("click", () => toggleZoom());
  img.addEventListener("error", showFailure);
  img.addEventListener("load", () => {
    const configureZoom = () => {
      // overlayRefs !== refs: the viewer was closed while decode() awaited.
      // body's own <img> !== img: a different asset was opened in the same
      // (reused) overlay before this one finished decoding. Either way this
      // stale resolution must not touch whatever is showing now.
      if (overlayRefs !== refs || refs.body.querySelector("img") !== img) {
        return;
      }
      const plan = resolveZoomTarget({
        naturalWidth: img.naturalWidth,
        naturalHeight: img.naturalHeight,
        displayedWidth: img.clientWidth,
        displayedHeight: img.clientHeight,
      });
      refs.zoomButton.hidden = !plan.canGrow;
      img.dataset.zoomWidth = plan.canGrow ? String(plan.width) : "";
      img.dataset.zoomHeight = plan.canGrow ? String(plan.height) : "";
      // Drives styles/media.css's cursor:zoom-in rule -- the same
      // `plan.canGrow` that decides whether the toolbar's own "Увеличить"
      // control is shown, so the cursor affordance never promises a zoom
      // the image has nowhere left to grow into.
      img.dataset.zoomable = String(plan.canGrow);
    };
    if (typeof img.decode !== "function") {
      configureZoom();
      return;
    }
    img.decode().then(configureZoom).catch(showFailure);
  });
  img.src = assetUrl;
  refs.body.append(img);
}

/**
 * Open the native video player for `asset`
 * (`{assetUrl, caption?, assetId?}`), labelled with `scene`'s range when the
 * scene carries `start_ms`/`end_ms` (a project-timeline position, not an
 * offset into this clip's own, usually shorter, file -- so playback is
 * never seeked to it, only described). `trigger` regains focus on close.
 */
export function openVideoViewer(asset, scene, trigger) {
  const assetUrl = asset && typeof asset.assetUrl === "string" ? asset.assetUrl : "";
  const assetId = asset && typeof asset.assetId === "string" ? asset.assetId : undefined;
  const captionParts = [];
  if (asset && typeof asset.caption === "string" && asset.caption) {
    captionParts.push(asset.caption);
  }
  const rangeLabel =
    scene && Number.isFinite(scene.start_ms) && Number.isFinite(scene.end_ms)
      ? formatSceneRange(scene.start_ms, scene.end_ms)
      : null;
  if (rangeLabel) {
    captionParts.push(rangeLabel);
  }
  const captionText = captionParts.join(" · ");
  openOverlay({
    dialogLabel: captionText || "Просмотр видео",
    captionText,
    trigger,
    kind: "video",
  });
  const refs = overlayRefs;
  const sceneId = scene && typeof scene.scene_id === "string" ? scene.scene_id : null;
  refs.overlay.__sceneId = sceneId;
  refs.goToSceneButton.hidden = !sceneId;
  refs.body.textContent = "";

  if (!hasLoadableAsset(assetUrl)) {
    const placeholder = buildAssetPlaceholder("Не удалось загрузить видео");
    refs.body.append(placeholder);
    markAssetError(placeholder, assetId);
    return;
  }

  const video = document.createElement("video");
  video.className = "media-viewer-video";
  video.controls = true;
  video.preload = "metadata";
  video.addEventListener("error", () => {
    refs.body.textContent = "";
    const placeholder = buildAssetPlaceholder("Не удалось загрузить видео");
    refs.body.append(placeholder);
    markAssetError(placeholder, assetId);
  });
  video.src = assetUrl;
  refs.body.append(video);
}

/** Open an audio result in the same modal/focus boundary as image/video. */
export function openAudioViewer(asset, trigger) {
  const assetUrl = asset && typeof asset.assetUrl === "string" ? asset.assetUrl : "";
  const assetId = asset && typeof asset.assetId === "string" ? asset.assetId : undefined;
  const captionText = asset && typeof asset.caption === "string" ? asset.caption : "";
  openOverlay({
    dialogLabel: captionText || "Просмотр аудио",
    captionText,
    trigger,
    kind: "audio",
  });
  const refs = overlayRefs;
  refs.body.textContent = "";
  if (!hasLoadableAsset(assetUrl)) {
    const placeholder = buildAssetPlaceholder("Аудио недоступно");
    refs.body.append(placeholder);
    markAssetError(placeholder, assetId);
    return;
  }
  const audio = document.createElement("audio");
  audio.className = "media-viewer-audio";
  audio.controls = true;
  audio.preload = "metadata";
  audio.addEventListener("error", () => {
    refs.body.textContent = "";
    const placeholder = buildAssetPlaceholder("Аудио недоступно");
    refs.body.append(placeholder);
    markAssetError(placeholder, assetId);
  });
  audio.src = assetUrl;
  refs.body.append(audio);
}

/**
 * Close whichever viewer is open (a no-op if none is): fully removes the
 * overlay from the document -- no leftover markup, buttons or captions once
 * closed, not merely a hidden node -- releases the document-level keydown
 * listener `buildOverlay` registered, and returns focus to whichever
 * element `resolveFocusTarget` finds. When that finds nothing -- the open
 * event did not come from a recognizable card element, so there is no
 * trigger and no group id to re-find by -- focus instead returns to
 * whatever held it right before the viewer opened (`buildOverlay`'s
 * `previousActiveElement`), so the removed close button never leaves focus
 * stranded on `<body>` for no reason a keyboard user could see. The next
 * `openImageViewer`/`openVideoViewer` call rebuilds a fresh overlay via
 * `ensureOverlay`.
 */
export function closeViewer() {
  if (!overlayRefs || overlayRefs.overlay.hidden) {
    return;
  }
  const refs = overlayRefs;
  document.removeEventListener("keydown", refs.handleDocumentKeydown);
  const trigger = refs.overlay.__triggerEl;
  const descriptor = refs.overlay.__triggerDescriptor;
  const previousActiveElement = refs.previousActiveElement;
  const media = refs.body.querySelector("video") || refs.body.querySelector("audio");
  if (media) {
    media.pause();
    media.removeAttribute("src");
    media.load();
  }
  refs.overlay.remove();
  overlayRefs = null;
  let target = resolveFocusTarget(trigger, descriptor);
  if (!target && previousActiveElement && document.contains(previousActiveElement)) {
    target = previousActiveElement;
  }
  if (target && typeof target.focus === "function") {
    target.focus();
  }
}

/**
 * The toolbar's "Перейти к сцене" handler (ticket 06 condition 6): closes
 * the player, asks the app to select the scene the open video is linked
 * to, and moves focus to that scene's block in the scenario -- never left
 * on `<body>`, and never left on the trigger card `closeViewer`'s own
 * focus-return would otherwise pick (the whole point of this control is to
 * leave the player *for the scenario*, not back to the gallery it was
 * opened from). Reads `__sceneId` before calling `closeViewer` -- which
 * sets `overlayRefs` back to `null` -- then dispatches through the same
 * shared `requestSceneSelection` every other scene trigger uses;
 * `document.dispatchEvent`/the store's own `commit` are both synchronous
 * (`ui/state.js`'s `createStore`), so the scenario surface has already
 * repainted with this scene visible by the time the `.focus()` call below
 * runs.
 */
function goToScene() {
  const sceneId = overlayRefs?.overlay.__sceneId || null;
  closeViewer();
  if (!sceneId) {
    return;
  }
  requestSceneSelection(sceneId, "media");
  const target = document.querySelector(
    `[data-hook="scenario-block-select"][data-scene-id="${CSS.escape(sceneId)}"]`,
  );
  if (target && typeof target.focus === "function") {
    target.focus();
  }
}

let openListenerAttached = false;

/**
 * Wire the listener that opens this viewer when a media card dispatches
 * `studio:open-viewer` (media.js's `dispatchOpenViewer`). Call once, from
 * the browser entry point (app.js) -- never at this module's own top level,
 * so importing viewer.js (e.g. to reach a pure function, in a test) never
 * touches `document` merely by being imported. A second call is a no-op:
 * app.js only calls this once, but nothing else guarantees that.
 *
 * `detail.kind` is a strict allowlist (`image`/`video`/`audio`); anything
 * else -- a future card type, a typo, a malformed or direct dispatch --
 * opens nothing, rather than silently falling back to the image viewer.
 */
export function attachViewerOpenListener() {
  if (openListenerAttached) {
    return;
  }
  openListenerAttached = true;
  document.addEventListener("studio:open-viewer", (event) => {
    const detail = event && event.detail;
    if (!detail) {
      return;
    }
    if (!["image", "video", "audio"].includes(detail.kind)) {
      return;
    }
    const trigger = event.target instanceof HTMLElement ? event.target : null;
    if (detail.kind === "video") {
      openVideoViewer(detail.asset, detail.scene, trigger);
    } else if (detail.kind === "audio") {
      openAudioViewer(detail.asset, trigger);
    } else {
      openImageViewer(detail.asset, trigger);
    }
  });
}
