// Task 14 repair 1, Part A condition 3 ("Связка в app.js закреплена
// тестами"). app.js itself cannot be unit-tested at all: importing it
// queries the real `document` for its DOM roots and, at the bottom of the
// file, kicks off `loadSession().then(loadProjectIndex)` as a side effect
// of module load alone -- there is no seam to import it safely under
// `node --test`. Every piece of *wiring* the repair's review named --
// the store subscriber's own repaint wiring, the
// liveness poll/focus-return's own `document.visibilityState` gate, and
// the poll calling `refreshProjectSnapshot` (an in-place patch) rather than
// `openProject` (which resets `status` to "loading" and drops the scene
// selection) -- lives here instead, built from injected dependencies alone.
// No bare `document`/`window`/`fetch` reference anywhere in this file:
// app.js's own job shrinks to gathering the real DOM roots/fetch/document/
// window and calling `createAppController` exactly once; every other
// caller (a test) supplies plain fakes instead and exercises the *real*
// production wiring, not a re-implementation of it.

import { createLivenessScheduler, createRequestGuard, snapshotsEqual } from "./shell-runtime.js";

/**
 * `deps`:
 *   - `store` -- ui/state.js's `createStore()` instance.
 *   - `fetchSnapshot(projectId) -> Promise<snapshot>` -- already narrowed
 *     to one project's `GET .../snapshot`, JSON-decoded.
 *   - `fetchProjects() -> Promise<{projects}>` -- `GET /api/projects`,
 *     JSON-decoded.
 *   - `paintShell(state)`, `paintRail(state)` -- one call each, per store
 *     commit; app.js passes closures pre-bound to the real DOM roots
 *     (`(state) => renderShell(shellRoot, state)`), so this module itself
 *     never needs to know about them.
 *   - `setActiveProject(id)` -- ui/actions.js's own module-level active
 *     project id, kept in step with the store on every commit (task 06).
 *   - `reportFailure(error)` -- wired to `store.setError` in app.js.
 *   - `isDocumentVisible()` -- reads `document.visibilityState ===
 *     "visible"` in production; a plain closure over a mutable flag in
 *     tests, so the visibility gate itself (not just createLivenessScheduler's
 *     own already-tested internals) is exercised.
 *   - `now`, `liveness`, `requestGuard` -- all optional, for deterministic
 *     tests; default to real `Date.now`/fresh scheduler/fresh guard.
 */
export function createAppController({
  store,
  fetchSnapshot,
  fetchProjects,
  paintShell,
  paintRail,
  setActiveProject,
  reportFailure,
  isDocumentVisible,
  now = Date.now,
  liveness = createLivenessScheduler(),
  requestGuard = createRequestGuard(),
}) {
  // The one subscriber app.js used to register inline. Every commit -- a
  // project switch, a background refresh, a filter keystroke, anything --
  // re-syncs the active-project id ui/actions.js's `postAction` reads,
  // repaints the shell/rail.
  store.subscribe((state) => {
    setActiveProject(state.snapshot?.active_project?.id ?? state.selectedProjectId ?? null);
    paintShell(state);
    paintRail(state);
  });

  // Selecting project B while project A's fetch is still in flight must not
  // let A's late response or error land on top of B once it resolves --
  // see ui/shell-runtime.js's createRequestGuard.
  async function openProject(projectId) {
    const requestToken = requestGuard.next();
    store.selectProject(projectId);
    try {
      const snapshot = await fetchSnapshot(projectId);
      if (!requestGuard.isCurrent(requestToken)) {
        return; // superseded by a newer selection/retry
      }
      store.replaceSnapshot(snapshot);
    } catch (error) {
      if (!requestGuard.isCurrent(requestToken)) {
        return;
      }
      reportFailure(error);
    }
  }

  /**
   * Re-fetch `projectId`'s own snapshot and replace it *in place* -- never
   * through `openProject`/`store.selectProject` (which unconditionally
   * resets `status` to "loading", clears the snapshot and drops the scene
   * selection): a control that already has live data on screen and just
   * wants it refreshed must not flash a loading skeleton or drop the
   * operator's scene selection merely because a background poll fired or a
   * `POST /api/actions` happened to succeed.
   *
   * Condition 1 ("Опрос, чьи данные не изменились... ничего не
   * перерисовывает"): the fetched body is compared, via `snapshotsEqual`
   * (ui/shell-runtime.js), against whatever is *currently applied* in the
   * store before ever calling `store.replaceSnapshot` -- an unconditional
   * replace committed a structurally-identical-but-new object on every
   * successful poll, which still forced a full main/inspector repaint
   * (ui/shell.js's `shellZonesNeedRepaint` keys off `snapshot` identity,
   * not content) for nothing.
   */
  async function refreshProjectSnapshot(projectId) {
    if (typeof projectId !== "string" || !projectId || store.getState().selectedProjectId !== projectId) {
      return;
    }
    const requestToken = requestGuard.next();
    try {
      const snapshot = await fetchSnapshot(projectId);
      if (!requestGuard.isCurrent(requestToken) || store.getState().selectedProjectId !== projectId) {
        return; // the operator switched projects (or retried) during the fetch
      }
      if (snapshotsEqual(store.getState().snapshot, snapshot)) {
        return; // nothing changed -- no commit, so no repaint at all
      }
      store.replaceSnapshot(snapshot);
    } catch {
      // A soft refresh's own failure must not blank out an already-visible
      // project: the operator still has live (if now slightly stale) data
      // on screen, and the next poll/focus-return/explicit retry gets
      // another chance.
    }
  }

  /** `studio:refresh-snapshot`'s handler body (ui/scenario.js's
   * `requestProjectRefresh`, dispatched after an action settles): refresh
   * the project the action was actually for, and count it toward the
   * liveness de-dupe window so a poll due a moment later does not repeat
   * the same fetch. */
  function requestRefresh(projectId) {
    refreshProjectSnapshot(projectId);
    liveness.noteRefresh(now());
  }

  /**
   * The periodic timer's own tick (`setInterval(controller.pollLiveness,
   * liveness.periodMs)` in app.js). Reads `selectedProjectId` fresh off the
   * store on every call rather than closing over one captured at setup
   * time, so switching projects never leaves this "writing into" whatever
   * is open now -- there is only ever this one interval, never a second
   * one to restart or tear down per project.
   *
   * BLOCKING finding: must check `isDocumentVisible()` itself (not merely
   * trust that `createLivenessScheduler`'s own internals are correct in
   * isolation -- a call site that hardcoded `true` here would pass every
   * one of that module's own tests while still polling a hidden tab), and
   * must call `refreshProjectSnapshot` -- never `openProject`, which would
   * flash a loading skeleton and wipe the scene selection on every single
   * background tick.
   */
  function pollLiveness() {
    const isVisible = isDocumentVisible();
    if (!liveness.shouldPoll(now(), isVisible)) {
      return; // hidden tab: zero requests; or a refresh from any source just happened
    }
    const { selectedProjectId, status } = store.getState();
    if (!selectedProjectId || (status !== "ready" && status !== "blocked")) {
      return; // nothing loaded yet, or still mid-initial-load/error
    }
    liveness.noteRefresh(now());
    refreshProjectSnapshot(selectedProjectId);
  }

  /** Window-focus/`visibilitychange`'s own immediate check -- same
   * visibility/visible-project guards as `pollLiveness`, gated on the
   * shared de-dupe window instead of the periodic-tick one so focus and a
   * `visibilitychange` firing together for one real tab-switch cost at
   * most one fetch. */
  function refreshOnReturn() {
    if (!isDocumentVisible() || !liveness.shouldRefreshNow(now())) {
      return;
    }
    const { selectedProjectId, status } = store.getState();
    if (!selectedProjectId || (status !== "ready" && status !== "blocked")) {
      return;
    }
    liveness.noteRefresh(now());
    refreshProjectSnapshot(selectedProjectId);
  }

  async function loadProjectIndex() {
    try {
      const data = await fetchProjects();
      const projects = Array.isArray(data?.projects) ? data.projects : [];
      store.setProjects(projects);
      if (projects.length === 0) {
        store.setStatus("empty");
        return;
      }
      await openProject(projects[0].id);
    } catch (error) {
      reportFailure(error);
    }
  }

  function viewStage(stage) {
    store.setViewedStage(stage);
  }

  function toggleHistory() {
    store.setHistoryOpen(!store.getState().historyOpen);
  }

  function closeHistory() {
    store.setHistoryOpen(false);
  }

  return {
    openProject,
    refreshProjectSnapshot,
    requestRefresh,
    pollLiveness,
    refreshOnReturn,
    loadProjectIndex,
    viewStage,
    toggleHistory,
    closeHistory,
    liveness,
    requestGuard,
  };
}
