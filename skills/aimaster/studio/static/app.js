// Composition root for the AI Мастерская shell. Fetches the project index
// and the active project's snapshot from the real loopback API, feeds them
// into the pure store, and re-paints the rail/shell on every change. Owns
// every cross-module DOM event other modules dispatch (`studio:project-
// selected`, `studio:retry-snapshot`, `studio:refresh-snapshot`, `studio:
// scene-selected`, `studio:filter-changed`, `studio:query-changed`) and the
// mobile rail's open/close chrome, which is purely local UI state unrelated
// to server data.
//
// Task 14 repair 1, condition 3: this file cannot be imported under
// `node --test` at all (it queries the real `document` for its DOM roots
// and, at the bottom, starts fetching as a side effect of module load), so
// none of its own wiring was ever actually pinned by a test -- a review
// finding confirmed live, in Chrome, with three concrete mutations that
// every existing test suite left green. Every piece of that wiring --
// which functions the store subscriber calls, whether the liveness poll/
// focus-return actually look at `document.visibilityState`, and whether a
// background tick refreshes in place or reopens the project from scratch --
// now lives in ./ui/app-controller.js's `createAppController`, built from
// injected dependencies alone. This file's own job is just to gather the
// real DOM roots/fetch/document/window and wire them into it once; see that
// module's own banner and tests/ui/app-controller.test.mjs for the
// mutation-tested contract itself.

import { createStore } from "./ui/state.js";
import { renderShell } from "./ui/shell.js";
import { renderProjectRail } from "./ui/rail.js";
import { deriveRailChrome } from "./ui/shell-runtime.js";
import { createAppController } from "./ui/app-controller.js";
import { attachViewerOpenListener } from "./ui/viewer.js";
import { fetchCsrfToken, setActiveProject } from "./ui/actions.js";
import { applyHistoryBackgroundInert, trapHistoryPanelTab } from "./ui/history-panel.js";

// Wires ui/media.js's cards to ui/viewer.js's lightbox/player via the
// `studio:open-viewer` DOM event -- the two modules never import each
// other (see viewer.js's file banner), so this one call is what actually
// connects them at runtime.
attachViewerOpenListener();

class StudioFetchError extends Error {
  constructor(code) {
    super(code);
    this.name = "StudioFetchError";
    this.code = code;
  }
}

const shellRoot = document.querySelector(".app-shell");
const railRoot = document.querySelector('[data-hook="project-rail"]');
const railToggle = document.querySelector('[data-hook="rail-toggle"]');
const railToggleLabel = railToggle?.querySelector(".visually-hidden") ?? null;
const railBackdrop = document.querySelector('[data-hook="rail-backdrop"]');
const main = document.querySelector("#main");
const historyPanel = document.querySelector('[data-hook="history-panel"]');

const store = createStore();

async function fetchJson(path, options) {
  let response;
  try {
    response = await fetch(path, {
      ...options,
      headers: { Accept: "application/json", ...(options?.headers || {}) },
    });
  } catch {
    throw new StudioFetchError("network_error");
  }
  let body = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok) {
    const code =
      body && body.error && typeof body.error.code === "string"
        ? body.error.code
        : `http_${response.status}`;
    throw new StudioFetchError(code);
  }
  return body;
}

function reportFailure(error) {
  const code = error instanceof StudioFetchError ? error.code : "unexpected_error";
  store.setError({ code });
}

// The controller (ui/app-controller.js) owns every contract the repair's
// review named -- the store subscriber, openProject/refreshProjectSnapshot
// (incl. condition 1's "unchanged data never repaints"), and the liveness
// poll/focus-return's own visibility gate -- built from the real fetch/DOM
// callbacks below. See that module's own banner; see
// tests/ui/app-controller.test.mjs for the mutation-tested contract.
const controller = createAppController({
  store,
  fetchSnapshot: (projectId) => fetchJson(`/api/projects/${encodeURIComponent(projectId)}/snapshot`),
  fetchProjects: () => fetchJson("/api/projects"),
  paintShell: (state) => renderShell(shellRoot, state),
  paintRail: (state) => renderProjectRail(railRoot, state),
  // Task 06: ui/actions.js's `postAction` never takes a project id itself
  // (see that module's own banner) -- the controller's subscriber is the
  // one place that keeps its module-level active-project id in step with
  // the store, on every commit, so a snapshot swap is never a separate
  // wiring path from any other store change.
  setActiveProject,
  reportFailure,
  isDocumentVisible: () => document.visibilityState === "visible",
});
// Paint the initial (loading) state immediately, before any fetch resolves
// -- the controller's own `store.subscribe` above only fires on *future*
// commits, never for the state the store already holds at construction.
renderShell(shellRoot, store.getState());
renderProjectRail(railRoot, store.getState());

document.addEventListener("studio:refresh-snapshot", (event) => {
  controller.requestRefresh(event?.detail?.projectId);
});

// Task 14 liveness: re-fetch the active project's own snapshot on a timer
// and on focus/visibility return, since chat-authored writes never emit
// SSE (see ui/shell-runtime.js's own liveness banner for why, and for the
// pure "should I fetch right now" policy `createLivenessScheduler` -- used
// inside the controller -- provides). One `setInterval` for the whole
// page: `controller.pollLiveness` reads `selectedProjectId` fresh off the
// store on every tick rather than closing over one captured at setup time,
// so switching projects never leaves a stale interval "writing into"
// whatever is open now -- there is no second interval to restart or tear
// down at all (ticket 14: "при смене проекта старый цикл не пишет в
// новый").
setInterval(controller.pollLiveness, controller.liveness.periodMs);
document.addEventListener("visibilitychange", controller.refreshOnReturn);
window.addEventListener("focus", controller.refreshOnReturn);

async function loadSession() {
  // Reuses ui/actions.js's own cached CSRF-token fetch (ticket 06
  // condition 11: "/api/session запрашивается на страницу один раз") --
  // calling `fetchJson("/api/session")` here too used to cost a second,
  // separate GET whose result this function immediately discarded, and
  // the first click's own `postAction` would then fetch the token all
  // over again. Session failure must never block browsing already-public
  // snapshot data.
  try {
    await fetchCsrfToken();
  } catch {
    // ignored: the project index/snapshot fetches below report their own
    // failures, and the shell stays usable read-only either way.
  }
}

document.addEventListener("studio:project-selected", (event) => {
  const projectId = event?.detail?.projectId;
  if (typeof projectId === "string" && projectId) {
    controller.openProject(projectId);
  }
  // Mobile-only: on desktop the rail is always the visible, persistent
  // column (deriveRailChrome never reports it inert there), so closing it
  // here has no visible effect and must not steal focus into #main away
  // from the project button a desktop/keyboard user just activated.
  const wasOpen = mobileRailQuery.matches && railOpenIntent;
  closeRail();
  // On mobile the rail (and the button that had focus) just became inert;
  // move attention to the content that's now loading instead of leaving
  // focus wherever the browser happens to drop it.
  if (wasOpen) {
    main?.focus();
  }
});

document.addEventListener("studio:retry-snapshot", () => {
  const { selectedProjectId } = store.getState();
  if (selectedProjectId) {
    controller.openProject(selectedProjectId);
  } else {
    controller.loadProjectIndex();
  }
});

document.addEventListener("studio:filter-changed", (event) => {
  store.setFilter(event?.detail?.filter);
});

document.addEventListener("studio:query-changed", (event) => {
  store.setQuery(event?.detail?.query);
});

// Task 06: the one cross-module signal ui/scenario.js, ui/timeline.js and
// ui/media.js's scene tags (see ticket 06 amendment 6) all dispatch instead
// of touching the store directly -- same bubbling-CustomEvent pattern as
// `studio:project-selected` above. `origin` names which of the three
// surfaces made the request; ui/shell.js's renderShell reads it back off
// the store to decide which of the *other* surfaces is allowed to
// auto-scroll (see ui/timeline.js's `shouldAutoScroll`).
// Repair, 2026-09-17 (ticket 06 condition 7). Used to only forward a
// *truthy* sceneId, which meant a deliberate "clear the selection" dispatch
// -- ui/scenario.js's new "Все сцены" control -- was silently swallowed
// right here: `store.selectScene` itself already normalizes a falsy id to
// `null` correctly (see ui/state.js), so the extra guard below only ever
// blocked the one case that needed to reach it.
document.addEventListener("studio:scene-selected", (event) => {
  const { sceneId, origin } = event?.detail || {};
  store.selectScene(typeof sceneId === "string" ? sceneId : null, typeof origin === "string" ? origin : null);
});

document.addEventListener("studio:stage-viewed", (event) => {
  const stage = event?.detail?.stage;
  if (typeof stage !== "string" || !stage) {
    return;
  }
  controller.viewStage(stage);
  document
    .querySelector(`[data-hook="stage-tab"][data-stage="${CSS.escape(stage)}"]`)
    ?.focus();
});

// --- Mobile rail: local, server-independent chrome -----------------------
//
// A single function, setRailOpen, drives the panel and backdrop together,
// so they can never desync: `data-open` is set on (or removed from) both
// elements atomically, and `inert`/`aria-expanded`/the toggle's accessible
// name always match what deriveRailChrome (ui/shell-runtime.js) computes
// for the current layout x intent pair -- never just whatever the last
// click happened to leave behind. Closed also means `inert` on the rail,
// not just visually off-screen -- a `transform` alone still leaves its
// search input/buttons in the Tab order and the accessibility tree even
// though nothing is visible.

// Must match layout.css's `@media (max-width: 900px)` off-canvas breakpoint.
const mobileRailQuery = window.matchMedia("(max-width: 900px)");

// The user's last explicit open/close choice. Only meaningful on the
// narrow layout -- deriveRailChrome ignores it entirely on a wide one, so
// a drawer left "open" on a phone and then resized to desktop can never
// leave the always-visible desktop rail `inert`.
let railOpenIntent = false;

function setRailOpen(open) {
  railOpenIntent = open;
  if (!railRoot) {
    return;
  }
  const { open: resolvedOpen, inert } = deriveRailChrome(mobileRailQuery.matches, railOpenIntent);
  if (resolvedOpen) {
    railRoot.setAttribute("data-open", "true");
    railBackdrop?.setAttribute("data-open", "true");
  } else {
    railRoot.removeAttribute("data-open");
    railBackdrop?.removeAttribute("data-open");
  }
  railRoot.inert = inert;
  // The toggle is hidden (display: none) outside the off-canvas layout, so
  // it is never really "expanded" there -- but keep the state honest
  // rather than relying on that CSS fact alone.
  const expanded = mobileRailQuery.matches && resolvedOpen;
  railToggle?.setAttribute("aria-expanded", String(expanded));
  if (railToggleLabel) {
    railToggleLabel.textContent = expanded ? "Закрыть панель проектов" : "Открыть панель проектов";
  }
}

function closeRail() {
  setRailOpen(false);
}

function openRail() {
  setRailOpen(true);
  if (mobileRailQuery.matches) {
    railRoot?.querySelector("input, button")?.focus();
  }
}

function syncHistoryBackground() {
  applyHistoryBackgroundInert(
    shellRoot,
    Boolean(store.getState().historyOpen),
    mobileRailQuery.matches,
  );
}

function closeHistory() {
  // Remove mobile inert before the synchronous store commit repaints the
  // topbar and restores focus to its newly-built history button.
  applyHistoryBackgroundInert(shellRoot, false, mobileRailQuery.matches);
  controller.closeHistory();
  setRailOpen(false);
}

document.addEventListener("studio:history-toggle", () => {
  if (store.getState().historyOpen) {
    closeHistory();
    return;
  }
  closeRail();
  controller.toggleHistory();
  syncHistoryBackground();
});

document.addEventListener("studio:history-close", closeHistory);

railToggle?.addEventListener("click", () => {
  if (railOpenIntent) {
    closeRail();
    railToggle.focus();
  } else {
    openRail();
  }
});

railBackdrop?.addEventListener("click", () => {
  closeRail();
  railToggle?.focus();
});

document.addEventListener("keydown", (event) => {
  if (
    store.getState().historyOpen &&
    trapHistoryPanelTab(historyPanel, event, mobileRailQuery.matches)
  ) {
    return;
  }
  if (event.key === "Escape" && store.getState().historyOpen) {
    closeHistory();
  } else if (event.key === "Escape" && railOpenIntent) {
    closeRail();
    railToggle?.focus();
  }
});

// Crossing the breakpoint in either direction -- rotating a device,
// resizing a window, with no click at all -- must resync `inert`/
// `data-open` to the layout that is now actually visible. Re-running the
// same setRailOpen used everywhere else (rather than a bespoke handler) is
// what guarantees the wide layout is always reported open and never inert.
mobileRailQuery.addEventListener("change", () => {
  if (store.getState().historyOpen) {
    railOpenIntent = false;
  }
  setRailOpen(railOpenIntent);
  syncHistoryBackground();
  if (store.getState().historyOpen && mobileRailQuery.matches) {
    historyPanel?.querySelector('[data-hook="history-close"]')?.focus();
  }
});

// Paint the initial chrome immediately: on a narrow first load the closed
// panel must already be `inert`, not just off-screen, or its search field
// stays reachable by Tab despite being invisible.
setRailOpen(railOpenIntent);
syncHistoryBackground();

loadSession().then(controller.loadProjectIndex);
