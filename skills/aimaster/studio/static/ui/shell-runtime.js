// Pure, DOM-free helpers factored out of app.js. Both concerns below are
// races/state-sync bugs that only show up over a sequence of events (a
// stale fetch resolving late, a viewport crossing the off-canvas
// breakpoint with no click in between) -- exactly the kind of thing that
// is easy to get right once and silently regress later. Keeping the
// decision itself here, with zero references to `document`/`window`, means
// it is directly testable with the Node test runner and no DOM shim; every
// DOM-touching consequence (fetch, element attributes, matchMedia) stays in
// app.js.

/**
 * Monotonic "is this still the latest request" ticket, used to drop a late
 * fetch response for a project the user has since navigated away from.
 * `next()` issues a new ticket and immediately supersedes every earlier
 * one; `isCurrent` reports whether a previously issued ticket is still the
 * latest. Equivalent to the inline `latestRequestToken` counter this
 * replaces, just extracted so the "was this superseded" logic is testable
 * on its own.
 */
export function createRequestGuard() {
  let latest = 0;
  return {
    next() {
      latest += 1;
      return latest;
    },
    isCurrent(token) {
      return token === latest;
    },
  };
}

/**
 * The mobile off-canvas rail's `{open, inert}` chrome, derived purely from
 * the current layout (`isMobileLayout`, i.e. the <=900px off-canvas
 * breakpoint matches) and the user's last open/close intent
 * (`wantsOpen`). On a wide layout the rail is the persistent, always-
 * visible desktop column -- never off-canvas -- so it is always reported
 * "open" and is never `inert`, regardless of what the user last clicked on
 * a narrow layout. This is the single source of truth both the initial
 * paint and a breakpoint-change listener call (in addition to every
 * open/close action), so crossing 900px in either direction -- with no
 * click at all -- cannot leave `inert` stuck out of sync with what is
 * actually visible.
 */
export function deriveRailChrome(isMobileLayout, wantsOpen) {
  const open = isMobileLayout ? Boolean(wantsOpen) : true;
  return { open, inert: isMobileLayout && !open };
}

// -----------------------------------------------------------------------
// Task 14 liveness: chat-authored writes (studio/authoring_*.py, ticket 12)
// never emit an SSE event -- they call `ProjectStore.transact` directly,
// with no `ActionLedger` entry for `events.py`'s `LedgerEventSource` to
// read at all (see interfaces.md, "Из таска 09": events come only from
// `action_events ⋈ actions`). So the dashboard's only way to notice a
// `scenes set`/`result add-version`/`question answer --channel chat` is to
// re-fetch the active project's own snapshot itself, on a timer and on
// focus/visibility return (spec §9 "Stale tab", ticket 14's own "Живость").
//
// `createLivenessScheduler` is the pure "should I fetch right now" policy,
// deliberately factored out of app.js exactly like `createRequestGuard`/
// `deriveRailChrome` above -- app.js owns the actual `setInterval`/
// `visibilitychange`/`focus` wiring and the one call to its existing
// `refreshProjectSnapshot`, this module owns the decision of *when*, so
// that decision is directly testable with `node --test` and no DOM at all
// (there is no fake `document.visibilityState`/`setInterval` under
// `node --test` -- see ui/timeline.js's own file banner on why DOM-timing
// concerns live in app.js, not here).
// -----------------------------------------------------------------------

const LIVENESS_PERIOD_MS = 8000; // within ticket 14's "не чаще раза в 5-10 с"
const LIVENESS_MIN_GAP_MS = 3000; // de-dupe window shared by every trigger

/**
 * `periodMs`/`minGapMs` default to the constants above; tests override them
 * so a real (but otherwise identical) scheduler test does not take real
 * seconds. Returns `{shouldPoll, shouldRefreshNow, noteRefresh, periodMs}`:
 *
 *   - `shouldPoll(now, isVisible)` -- the periodic timer's own tick,
 *     called every `periodMs` regardless of layer: `false` outright while
 *     `isVisible` is false (ticket 14: "пока вкладка скрыта -- ноль
 *     запросов" -- the request must never even start, so this is checked
 *     *before* any fetch, not used to cancel one already in flight), and
 *     `false` when a refresh -- from *any* trigger, periodic, focus-
 *     return, or an action's own post-submit `studio:refresh-snapshot`
 *     (ui/scenario.js's `requestProjectRefresh`) -- already happened
 *     within `minGapMs` ("Если SSE уже вызвал перечитывание, периодическое
 *     не дублирует его в том же окне": nothing here ever wires up a real
 *     SSE client, but the same de-dupe rule covers every refresh source
 *     this codebase actually has).
 *   - `shouldRefreshNow(now)` -- window-focus/visibility-return's own
 *     immediate check, gated only by the same `minGapMs` de-dupe (focus
 *     and `visibilitychange` firing together for one real tab-switch must
 *     not cost two fetches).
 *   - `noteRefresh(now)` -- call after *every* successful or attempted
 *     refresh, from any of the three sources above, so the de-dupe window
 *     is shared rather than tracked separately per trigger.
 */
export function createLivenessScheduler({ periodMs = LIVENESS_PERIOD_MS, minGapMs = LIVENESS_MIN_GAP_MS } = {}) {
  let lastRefreshAt = -Infinity;
  return {
    periodMs,
    minGapMs,
    shouldPoll(now = Date.now(), isVisible = true) {
      if (!isVisible) {
        return false;
      }
      return now - lastRefreshAt >= minGapMs;
    },
    shouldRefreshNow(now = Date.now()) {
      return now - lastRefreshAt >= minGapMs;
    },
    noteRefresh(now = Date.now()) {
      lastRefreshAt = now;
    },
  };
}

// -----------------------------------------------------------------------
// Task 14 repair 1, condition 1 ("Опрос, чьи данные не изменились...
// ничего не перерисовывает"). Every `fetch(...).then(r => r.json())` call
// produces a brand-new object graph even when the server's own answer is
// byte-for-byte the same JSON -- and ui/shell.js's `shellZonesNeedRepaint`
// keys off `snapshot` *identity*, not content (see that function's own
// banner: "the exact seam that decides whether... is allowed to reach
// them at all"). Before this, every successful background poll committed a
// structurally-identical-but-new object, which still forced a full main/
// inspector repaint for nothing -- tearing down and rebuilding whatever the
// operator was mid-typing into, mid-scroll-position on, or had manually
// expanded. `ui/app-controller.js`'s `refreshProjectSnapshot` calls this
// against the currently-applied snapshot before ever calling `store.
// replaceSnapshot`, and skips the commit entirely when it is `true`.
// -----------------------------------------------------------------------

/**
 * Structural equality for a `/api/projects/{id}/snapshot` JSON payload --
 * order-independent for object keys (two independent `json.dumps` calls
 * over an equal dict are already key-order-stable in this codebase's own
 * server, but this does not rely on that), order-*sensitive* for arrays
 * (scenes/results/versions are ordered lists; a snapshot that only
 * reordered one is genuinely a different snapshot, not a false positive to
 * suppress). Plain recursive structural comparison -- no JSON.stringify
 * round trip, so key order in the two inputs never matters either way.
 */
export function snapshotsEqual(a, b) {
  if (a === b) {
    return true;
  }
  if (typeof a !== "object" || typeof b !== "object" || a === null || b === null) {
    return false;
  }
  if (Array.isArray(a) !== Array.isArray(b)) {
    return false;
  }
  if (Array.isArray(a)) {
    if (a.length !== b.length) {
      return false;
    }
    for (let index = 0; index < a.length; index += 1) {
      if (!snapshotsEqual(a[index], b[index])) {
        return false;
      }
    }
    return true;
  }
  const aKeys = Object.keys(a);
  const bKeys = Object.keys(b);
  if (aKeys.length !== bKeys.length) {
    return false;
  }
  for (const key of aKeys) {
    if (!Object.prototype.hasOwnProperty.call(b, key) || !snapshotsEqual(a[key], b[key])) {
      return false;
    }
  }
  return true;
}

// -----------------------------------------------------------------------
// Task 14 repair 1, condition 4 ("приёмная сторона снятия метки фокуса в
// shell.js... закреплена тестом"). Extracted from ui/shell.js's own
// module-level `pendingSceneFocus` variable so its exact note/clear/take
// semantics are directly testable with `node --test` -- no `document`/
// `CustomEvent` at all, the same reasoning as `createRequestGuard`/
// `createLivenessScheduler` above. ui/shell.js is the only real caller: it
// owns the lazy `document.addEventListener("studio:scene-focus-pending",
// ...)` relay (DOM-only glue, see that module's own banner for why it is
// attached lazily rather than at import time) and drives this registry
// from that listener's body, and also exports its own instance so a test
// can call `note`/`clear`/`take` directly against the exact registry
// production code uses.
// -----------------------------------------------------------------------

/**
 * A single pending "restore focus to this scene-linked control on the next
 * repaint" note. `note(entry)` records `{hook, sceneId}`, overwriting
 * whatever was there. `clear(match)` drops the current note only on an
 * *exact* `{hook, sceneId}` match (ticket 14 leftover 1: a different,
 * newer note -- a second scene's edit form concurrently in flight -- must
 * never be cancelled by a late `clear` meant for someone else's submit).
 * `take()` returns and clears the note unconditionally, so a stale note can
 * never resurface on a later, unrelated repaint whether or not this
 * particular call needed it.
 */
export function createPendingFocusRegistry() {
  let pending = null;
  return {
    note(entry) {
      pending = entry;
    },
    clear(match) {
      if (pending && pending.hook === match?.hook && pending.sceneId === match?.sceneId) {
        pending = null;
      }
    },
    take() {
      const note = pending;
      pending = null;
      return note;
    },
  };
}
