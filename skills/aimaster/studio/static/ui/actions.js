// Thin HTTP client for `POST /api/actions` -- the one route the dashboard
// is allowed to mutate canonical state through. This module owns the CSRF
// handshake and the exact request shape; every caller (this task's
// approve-scenario/revise-scenario/scene-edit controls, and task 08's
// later approve/reject/vary/regenerate/hide/retire/reorder/answer
// controls -- see interfaces.md's ticket-06 note: "таск 08 расширяет этот
// же модуль, а не пишет второй") only ever sees a small, allowlisted
// `{ok, code}` result, never a thrown exception or raw server text.
//
// `postAction` never takes a project id: exactly one project is ever open
// in this dashboard at a time, so `setActiveProject` (called once per
// project switch, from app.js's store subscription) is the one place that
// changes, and every click during that project's lifetime reuses it --
// instead of every call site re-threading an id that never actually
// varies between two clicks in a row.
//
// Repair, 2026-09-17 (ticket 06 conditions 1/5/10). Two more exports live
// here now: `waitForProjectUpdate` (bounded polling for the decisions
// worker to actually apply a queued action) and `runAction` (the shared
// "post, then wait if the action is one that mutates state" pipeline
// every dashboard control -- this task's and task 08's alike -- submits
// through). Both stay network-only, no DOM: see `runAction`'s own banner
// for why.
//
// Second repair, 2026-09-17 (ticket 06 conditions 7/8/9/10/11). Four more
// pieces, all still DOM-free:
//   - `waitForProjectUpdate` now reports whether it actually saw the
//     revision move (`{confirmed}`) instead of resolving to nothing
//     either way -- a caller could not previously tell "applied" from
//     "the wait budget simply ran out" (condition 7), and each of its own
//     polls is now bounded by an `AbortController` sized to whatever
//     budget remains, not left free to hang past it on a stalled request.
//   - `runAction` forwards that `confirmed` flag on its own result.
//   - `ACTION_ERROR_MESSAGES`/`resolveActionErrorMessage` moved here from
//     ui/scenario.js, so they sit next to the `runAction` result they
//     translate -- task 08's later controls reuse this one copy instead
//     of a second, scenario.js-only dictionary (condition 10).
//   - `submitAction` bundles the "disable controls -> runAction -> maybe
//     re-enable" shape every dashboard control already repeats by hand
//     (condition 10); it takes plain `{disabled}` targets, never
//     `document` itself, so it stays exactly as DOM-free and directly
//     testable as everything else here.
//   - `fetchCsrfToken` is now exported so app.js's own startup session
//     check shares this module's one cached token promise instead of
//     firing a second, separate `/api/session` GET whose result it just
//     discarded (condition 11).

import { resolveLabel } from "./state.js";

let activeProjectId = null;
let csrfTokenPromise = null;

/**
 * The "find the one action entry matching (action_type, target_id), then
 * turn a `failed` one into this caller's own dictionary text" shape --
 * ticket 17 condition 1: ui/scenario-reopen.js's `resolveReopenFailureText`
 * (target `("reopen-scenario", "scenario")`, text `REOPEN_PENDING_HINT_TEXT`)
 * and ui/scenario.js's `resolveSceneEditFailureText` (target
 * `("edit", sceneId)`, text `SCENE_EDIT_FAILURE_TEXT`) used to each
 * parallel-implement this same lookup by hand. `undefined` for anything
 * else -- no attempt yet, still queued/running, or a genuine success --
 * never a second, invented explanation; each caller still owns its own
 * dictionary text and passes it in as `failedText`, so this stays a pure
 * lookup with no opinion on wording.
 */
export function resolveActionFailureText(actions, actionType, targetId, failedText) {
  const list = Array.isArray(actions) ? actions : [];
  const entry = list.find((item) => item && item.action_type === actionType && item.target_id === targetId);
  return entry && entry.status === "failed" ? failedText : undefined;
}

/**
 * Record which project subsequent `postAction` calls target. Safe to call
 * with the same id repeatedly (a no-op session-token-wise) and with `null`/
 * anything non-string (clears it, so a call before any project has loaded
 * fails closed instead of silently addressing a stale project).
 */
export function setActiveProject(projectId) {
  activeProjectId = typeof projectId === "string" && projectId ? projectId : null;
}

/**
 * Fetch and cache the CSRF token from `GET /api/session`. A failed lookup
 * is never cached -- the next `postAction` call gets a fresh attempt
 * instead of being stuck replaying one dead rejected promise for the rest
 * of the page's life (a transient network hiccup on the very first click
 * must not permanently disable every click after it).
 *
 * Exported (ticket 06 condition 11) so app.js's own page-load session
 * check calls this instead of running its own separate `fetch("/api/session")`
 * -- the two used to cost two GETs per page load, one of them for a
 * token app.js immediately discarded; now there is exactly one, shared by
 * whichever of the two callers runs first.
 */
export function fetchCsrfToken() {
  if (!csrfTokenPromise) {
    csrfTokenPromise = fetch("/api/session", { headers: { Accept: "application/json" } })
      .then((response) => {
        if (!response.ok) {
          throw new Error("session_error");
        }
        return response.json();
      })
      .then((body) => {
        const token = body && body.csrf_token;
        if (typeof token !== "string" || !token) {
          throw new Error("session_error");
        }
        return token;
      })
      .catch((error) => {
        csrfTokenPromise = null;
        throw error;
      });
  }
  return csrfTokenPromise;
}

async function parseErrorBody(response) {
  let body = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  const code =
    body && body.error && typeof body.error.code === "string"
      ? body.error.code
      : `http_${response.status}`;
  const result = { ok: false, code };
  if (body && body.error && typeof body.error.current_revision === "number") {
    result.currentRevision = body.error.current_revision;
  }
  if (body && typeof body.accepted_answer !== "undefined") {
    result.acceptedAnswer = body.accepted_answer;
  }
  return result;
}

/**
 * Shared CSRF-handshake + fetch + error-parsing core behind `postAction`
 * and `postQuestionAnswer` (ticket 14 repair, condition 10: "postAction и
 * postQuestionAnswer используют один помощник CSRF/fetch/ошибок" -- the two
 * used to each run their own, separately-written copy of exactly this
 * sequence). POSTs `body` as JSON to `path` with the cached CSRF token
 * (`fetchCsrfToken`, shared across both callers already); resolves to
 * `{ok:true, body}` once `response.status === expectedStatus`, or the same
 * `{ok:false, code, ...}` shape `parseErrorBody` already produces for every
 * other outcome -- a failed token fetch or network error included. Never
 * throws, so neither caller needs its own try/catch around this.
 */
async function postJson(path, body, expectedStatus) {
  let csrfToken;
  try {
    csrfToken = await fetchCsrfToken();
  } catch {
    return { ok: false, code: "session_error" };
  }

  let response;
  try {
    response = await fetch(path, {
      method: "POST",
      headers: {
        // Exactly "application/json" -- no ";charset=utf-8" suffix, which
        // the server treats as a *different* Content-Type and rejects.
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken,
        Accept: "application/json",
      },
      body: JSON.stringify(body),
    });
  } catch {
    return { ok: false, code: "network_error" };
  }

  if (response.status !== expectedStatus) {
    return parseErrorBody(response);
  }
  try {
    return { ok: true, body: await response.json() };
  } catch {
    return { ok: false, code: "network_error" };
  }
}

/**
 * Submit exactly one dashboard action: `POST /api/actions` with the CSRF
 * token from `/api/session`, `Content-Type: application/json` (no charset
 * -- the server's `_parse_json` requires an exact match) and precisely the
 * six keys `studio/http_app.py`'s `_ACTION_KEYS` accepts.
 *
 * `expectedRevision` must be the *snapshot's own* top-level `revision` the
 * caller is currently showing -- never `active_project.revision` (a
 * different, optional field) and never a value this module invents.
 * `idempotencyKey` must be freshly generated per click (`crypto.
 * randomUUID()` is the usual choice at the call site); reusing one key
 * across two distinct clicks would make the second a no-op replay of the
 * first rather than a new attempt.
 *
 * Resolves to `{ok:true, actionId, revision, status}` on `202`, or
 * `{ok:false, code, ...}` for every other outcome -- no active project yet,
 * a network failure, or any documented error code (`forbidden`,
 * `payload_too_large`, `bad_request`, `revision_conflict` [+
 * `currentRevision`], `idempotency_conflict`, `not_found`,
 * `method_not_allowed`, `internal_error`) -- never a thrown exception a
 * caller must additionally wrap in try/catch.
 */
export async function postAction(actionType, targetId, payload, expectedRevision, idempotencyKey) {
  // Captured into a local *before* the first `await` below (repair
  // 2026-09-17, ticket 06 condition 5: "project_id и expected_revision
  // берутся из одного snapshot до первого await"). The old code re-read
  // the module-level `activeProjectId` a second time from inside the
  // `fetch(...)` call, *after* `await fetchCsrfToken()` had already
  // suspended this function -- if `setActiveProject` ran during that
  // suspension (the operator switched projects while this click's CSRF
  // fetch was still in flight), the POST body would silently address the
  // *new* project with the *old* click's `expected_revision`, a
  // mismatched pair neither the caller nor the server-side revision check
  // was ever designed to catch (the numbers just happen to be for two
  // different projects). Reading it once, here, makes this call's target
  // project a fixed fact for its whole lifetime, exactly like
  // `expectedRevision` already is by virtue of being a plain parameter.
  const projectId = activeProjectId;
  if (!projectId) {
    return { ok: false, code: "no_active_project" };
  }
  const result = await postJson(
    "/api/actions",
    {
      project_id: projectId,
      action_type: actionType,
      target_id: targetId,
      payload: payload && typeof payload === "object" ? payload : {},
      expected_revision: expectedRevision,
      idempotency_key: idempotencyKey,
    },
    202,
  );
  if (!result.ok) {
    return result;
  }
  const body = result.body;
  return { ok: true, actionId: body.action_id, revision: body.revision, status: body.status };
}

/**
 * Submit one dashboard answer: `POST /api/questions/{id}/answers` with the
 * same CSRF handshake `postAction` uses, `Content-Type: application/json`
 * (no charset) and exactly the two keys `http_app.py`'s `_ANSWER_KEYS`
 * accepts -- `revision` (the *question's own* `revision` field, never the
 * snapshot's top-level one -- `QuestionStore.answer` compares against the
 * row it stamped at `question create` time) and `answer` (a string for
 * `single`/`free_text`, a list of strings for `multi`, a boolean for
 * `confirm` -- ui/question-modal.js's `buildAnswerPayload` is what decides
 * the shape; this function passes it through unexamined).
 *
 * Resolves to `{ok:true, questionId, projectId, revision, status, answer}`
 * on `200`, or `{ok:false, code, ...}` for every other outcome -- reuses
 * `parseErrorBody` exactly like `postAction` does, which already lifts
 * `body.accepted_answer` onto the result (task 14 uses this for the
 * `already_answered` 409: "поздний ответ показывает принятый, без
 * перезаписи"). Never a thrown exception a caller must additionally wrap.
 */
export async function postQuestionAnswer(questionId, revision, answer) {
  const result = await postJson(
    `/api/questions/${encodeURIComponent(questionId)}/answers`,
    { revision, answer },
    200,
  );
  if (!result.ok) {
    return result;
  }
  const body = result.body;
  return {
    ok: true,
    questionId: body.question_id,
    projectId: body.project_id,
    revision: body.revision,
    status: body.status,
    answer: body.answer,
  };
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

const REVISION_POLL_INITIAL_MS = 120;
const REVISION_POLL_MAX_MS = 1500;
const REVISION_POLL_BUDGET_MS = 10000;

/** One bare GET of `projectId`'s own snapshot, reduced to just its
 * top-level `revision` -- `null` on any transport/parse failure (including
 * a timeout, see below), never a thrown error, since this is only ever
 * used as a polling probe (see `waitForProjectUpdate`) that must degrade
 * to "no signal yet" rather than abort the wait it is part of.
 *
 * `timeoutMs` bounds this one call via `AbortController` (ticket 06
 * condition 7: "каждый опрос ограничен остатком бюджета"): without it, a
 * single stalled request could sit past `waitForProjectUpdate`'s own
 * overall budget, since nothing else in that loop would ever notice a
 * `fetch` that never settles at all. A non-positive value aborts
 * essentially immediately -- the caller is expected to only pass what
 * `waitForProjectUpdate`'s own deadline still has left. */
async function fetchSnapshotProbe(projectId, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), Math.max(0, timeoutMs));
  try {
    const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/snapshot`, {
      headers: { Accept: "application/json" },
      signal: controller.signal,
    });
    if (!response.ok) {
      return null;
    }
    const body = await response.json();
    return Number.isFinite(body?.revision)
      ? { revision: body.revision, actions: Array.isArray(body.actions) ? body.actions : [] }
      : null;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Wait for `projectId`'s own snapshot revision to move past
 * `baselineRevision` -- bounded, growing-interval polling, ~10s total
 * (repair 2026-09-17, ticket 06 condition 1: "опросом /api/events с
 * Last-Event-ID или ограниченным опросом snapshot (нарастающий интервал,
 * предел около 10 с)"). The decisions worker (task 11) applies a queued
 * action asynchronously -- "клик применяется за десятки миллисекунд"
 * once `enqueue` wakes it (interfaces.md, "Из таска 11") -- so refreshing
 * on the bare `202` this function's caller already received, instead of
 * waiting for that to actually happen, is exactly what used to show stage
 * 1 with a stale, still-enabled "Одобрить сценарий" button.
 *
 * Resolves -- never rejects -- to `{confirmed: true}` once the revision
 * has genuinely moved, or to `{confirmed: false}` once either the time
 * budget runs out with no signal at all, or the operator switches away to
 * a different project mid-wait. `confirmed` is second-repair, 2026-09-17
 * (ticket 06 condition 7): a failed decision (e.g. a stage check that
 * rejects a now-stale action) never bumps the revision, so "it moved" is
 * not a promise this function can always keep, and a caller that could
 * not tell that apart from a genuine confirmation used to report a
 * click's outcome as settled even when the budget had simply run out.
 * `runAction` never refreshes anything itself -- that has always been the
 * caller's own job (compare ui/scenario.js's handlers) -- and, since this
 * same second repair, an honest caller deliberately does *not* refresh on
 * `confirmed: false`: live-browser testing against a real stalled
 * decision worker found that refreshing there raced the resulting repaint
 * against the caller's own "Исход не подтверждён" message and erased it
 * before it was ever visible, on a project whose data genuinely had not
 * changed. `confirmed` is what makes that distinction possible in the
 * first place.
 *
 * `abandoned` is task 14's own leftover-2 fix: `true` only when the wait
 * ended early because `activeProjectId` changed out from under it (the
 * operator switched projects mid-wait), `false` when the full `budgetMs`
 * genuinely ran out with the operator still on this project. Both cases
 * resolve `confirmed:false` -- a caller cannot tell them apart from that
 * alone -- but they call for different UI: a genuine timeout is still
 * this project's own problem to show ("Исход не подтверждён", keep the
 * draft so the operator can retry); an abandoned wait belongs to a
 * project the operator is no longer even looking at, whose *next* fresh
 * open (a full `openProject` fetch, never this in-place wait) will show
 * the true current state on its own -- persisting a stale "unconfirmed"
 * draft for it invites a duplicate resubmission of an edit that may have
 * already gone through.
 *
 * `budgetMs`/`initialMs`/`maxMs` default to the ~10s/120ms/1.5s shape
 * above; tests/ui/actions.test.mjs overrides them so a real (but
 * otherwise identical) bounded-poll test does not take a real 10 seconds.
 */
export async function waitForProjectUpdate(
  projectId,
  baselineRevision,
  { budgetMs = REVISION_POLL_BUDGET_MS, initialMs = REVISION_POLL_INITIAL_MS, maxMs = REVISION_POLL_MAX_MS } = {},
) {
  if (!projectId) {
    return { confirmed: false, abandoned: false };
  }
  const deadline = Date.now() + budgetMs;
  let intervalMs = initialMs;
  while (Date.now() < deadline) {
    await delay(intervalMs);
    if (activeProjectId !== projectId) {
      return { confirmed: false, abandoned: true }; // superseded by a project switch mid-wait
    }
    const remainingMs = deadline - Date.now();
    if (remainingMs <= 0) {
      break;
    }
    const probe = await fetchSnapshotProbe(projectId, remainingMs);
    if (probe !== null && probe.revision !== baselineRevision) {
      return { confirmed: true, abandoned: false, revision: probe.revision };
    }
    intervalMs = Math.min(intervalMs * 2, maxMs);
  }
  return { confirmed: false, abandoned: false };
}

const TERMINAL_ACTION_STATUSES = new Set([
  "succeeded",
  "failed",
  "needs_chat",
  "needs_chat_setup",
  "outcome_unknown",
]);

/**
 * Stronger wait used by multi-field saves: a different project revision is
 * not evidence that this action succeeded. Continue until the exact action
 * id is visible as succeeded, or stop on its own terminal failure.
 */
export async function waitForActionUpdate(
  projectId,
  baselineRevision,
  actionId,
  { budgetMs = REVISION_POLL_BUDGET_MS, initialMs = REVISION_POLL_INITIAL_MS, maxMs = REVISION_POLL_MAX_MS } = {},
) {
  if (!projectId || !actionId) {
    return { confirmed: false, abandoned: false };
  }
  const deadline = Date.now() + budgetMs;
  let intervalMs = initialMs;
  while (Date.now() < deadline) {
    await delay(intervalMs);
    if (activeProjectId !== projectId) {
      return { confirmed: false, abandoned: true };
    }
    const remainingMs = deadline - Date.now();
    if (remainingMs <= 0) break;
    const probe = await fetchSnapshotProbe(projectId, remainingMs);
    if (probe) {
      const action = probe.actions.find((entry) => entry?.action_id === actionId);
      if (action?.status === "succeeded" && probe.revision !== baselineRevision) {
        return { confirmed: true, abandoned: false, revision: probe.revision, actionStatus: action.status };
      }
      if (action && TERMINAL_ACTION_STATUSES.has(action.status) && action.status !== "succeeded") {
        return { confirmed: false, abandoned: false, revision: probe.revision, actionStatus: action.status };
      }
    }
    intervalMs = Math.min(intervalMs * 2, maxMs);
  }
  return { confirmed: false, abandoned: false };
}

/**
 * Shared submit pipeline behind every dashboard action control (this
 * task's approve-scenario/revise-scenario/scene edit; task 08's approve/
 * reject/vary/regenerate/hide/unhide/retire/restore/reorder -- see
 * interfaces.md's ticket-06 notes 7 and 10, "одна обёртка, которую
 * переиспользует таск 08"). Generates its own fresh `idempotency_key` --
 * `crypto.randomUUID()`, never a value a caller passes in or reuses --
 * and calls `postAction` exactly once per invocation; the follow-up wait
 * only ever issues extra `GET` polls, never a second `POST /api/actions`
 * for the same call.
 *
 * On a `202` for an action the decisions worker actually mutates project
 * state for (`awaitUpdate: true`, the default), waits for the revision to
 * move (`waitForProjectUpdate`) before resolving, and forwards that wait's
 * own `confirmed` flag on the returned result -- so that by the time a
 * caller's own success branch asks app.js to refresh (via ui/scenario.js's
 * `requestProjectRefresh`, or task 08's own equivalent), the decision has
 * almost always already been applied, and the caller can tell a genuine
 * confirmation from a budget that simply ran out (ticket 06 condition 7)
 * instead of treating both the same way. A chat-only action
 * (`revise-scenario`) passes `awaitUpdate: false`: chat applies it, not
 * this process, so there is nothing here to wait for, and `confirmed` is
 * left off the result entirely (not `false` -- "not applicable" is not
 * the same claim as "waited and did not confirm").
 *
 * Deliberately touches nothing on `document` and builds no DOM -- unlike
 * ui/timeline.js's `requestSceneSelection`, this module stays the "thin
 * HTTP client" its own original banner describes, so it stays directly
 * testable (tests/ui/actions.test.mjs) with a mocked `fetch` alone, no
 * DOM. Callers own their own buttons/status text and decide what a
 * success, an unconfirmed wait or a `revision_conflict` should trigger on
 * screen; this function only decides *when* the network side of one click
 * is settled, and how confident the result is.
 */
export async function runAction({
  actionType,
  targetId,
  payload,
  expectedRevision,
  awaitUpdate = true,
  waitOptions,
  requireActionSuccess = false,
}) {
  const projectId = activeProjectId;
  const result = await postAction(actionType, targetId, payload, expectedRevision, crypto.randomUUID());
  if (result.ok && awaitUpdate) {
    const wait = requireActionSuccess
      ? await waitForActionUpdate(projectId, expectedRevision, result.actionId, waitOptions)
      : await waitForProjectUpdate(projectId, expectedRevision, waitOptions);
    if (requireActionSuccess && wait.actionStatus && wait.actionStatus !== "succeeded") {
      return {
        ...result,
        ok: false,
        code: "action_failed",
        confirmed: false,
        abandoned: wait.abandoned,
        actionStatus: wait.actionStatus,
      };
    }
    return {
      ...result,
      confirmed: wait.confirmed,
      abandoned: wait.abandoned,
      ...(wait.confirmed ? { confirmedRevision: wait.revision } : {}),
    };
  }
  return result;
}

/**
 * Submit several state-changing actions as one UI save. Every next action
 * uses the revision observed from the previous action's real snapshot poll;
 * it never guesses `revision + 1` and never reuses the render-time revision.
 */
export async function submitActionsSequentially({
  actions,
  expectedRevision,
  controls = [],
  waitOptions,
}) {
  const steps = Array.isArray(actions) ? actions : [];
  if (steps.length === 0) {
    return { ok: true, confirmed: true, completed: 0, confirmedRevision: expectedRevision };
  }
  const previousDisabled = controls.map((control) => (control ? control.disabled : undefined));
  for (const control of controls) {
    if (control) {
      control.disabled = true;
    }
  }
  let revision = expectedRevision;
  let completed = 0;
  let result = { ok: true, confirmed: true, confirmedRevision: revision };
  for (const step of steps) {
    result = await runAction({
      actionType: step.actionType,
      targetId: step.targetId,
      payload: step.payload,
      expectedRevision: revision,
      waitOptions,
      requireActionSuccess: true,
    });
    if (!result.ok || result.confirmed === false || !Number.isFinite(result.confirmedRevision)) {
      controls.forEach((control, index) => {
        if (control) {
          control.disabled = previousDisabled[index];
        }
      });
      return { ...result, completed, confirmedRevision: revision };
    }
    revision = result.confirmedRevision;
    completed += 1;
  }
  return { ...result, completed, confirmedRevision: revision };
}

// Never the server's raw error text (spec §8/interfaces.md: "Разбор
// 202/409/403 -- без сырого текста в UI"). Routed through ui/state.js's
// `resolveLabel` so an unrecognized/hostile code (including
// `constructor`/`__proto__`) never resolves to anything but the fallback.
//
// Moved here from ui/scenario.js (second repair, 2026-09-17, ticket 06
// condition 10: "словарь ошибок действий... экспортируются рядом с
// runAction"): every caller of `runAction`/`postAction` needs the same
// translation, task 08's later controls included, so it sits next to what
// it translates instead of living only inside the one module that
// happened to need it first.
// Repair, 2026-09-17 (ticket 08 amendment 11, ticket-06-review point
// "текст для not_found не завязан на сцены"). `not_found` used to read
// "Сцена не найдена" -- correct only for ui/scenario.js's own `edit`
// control (target_id is always a scene there), wrong for every one of task
// 08's card/stage controls, whose target_id is a prompt/result version, a
// card group id or a milestone stage name, never necessarily a scene. The
// message is generic now, matching what the code actually means: no entity
// by this id exists in the collection the current stage owns right now
// (studio/decision_cards.py's resolvers, studio/decision_stages.py's
// plan_milestone).
export const ACTION_ERROR_MESSAGES = Object.freeze({
  blocked: "Шаг заблокирован. Вернитесь в чат.",
  already_approved: "Шаг уже одобрен.",
  incomplete_storyboard: "Добавьте кадры и укажите длительность каждого.",
  missing_prompts: "Сначала напишите промпты для всех нужных позиций.",
  unaccepted_positions: "Сначала примите все нужные результаты.",
  missing_final_material: "Сначала подготовьте финальный материал проекта.",
  revision_conflict: "Проект обновился — показываю актуальную версию.",
  idempotency_conflict: "Это действие уже выполняется.",
  forbidden: "Не удалось подтвердить запрос. Обновите страницу.",
  bad_request: "Не удалось выполнить действие.",
  payload_too_large: "Текст слишком длинный.",
  not_found: "Не найдено. Обновите страницу.",
  method_not_allowed: "Не удалось выполнить действие.",
  internal_error: "Что-то пошло не так. Попробуйте ещё раз.",
  network_error: "Нет соединения с сервером.",
  session_error: "Не удалось подтвердить запрос. Обновите страницу.",
  no_active_project: "Проект не выбран.",
  action_failed: "Не удалось выполнить действие.",
  // Task 14: `POST /api/questions/{id}/answers`' own extra code (see
  // http_app.py's `_answer`). Shown together with `body.accepted_answer`
  // (ui/question-modal.js), never on its own -- this fallback only covers
  // a caller that, for some reason, has no accepted answer to display yet.
  // `QuestionNotFound`/`QuestionExpired` surface as the existing
  // `not_found` code above, not a separate one -- both are `QuestionError`,
  // not `QuestionValidationError`, so http_app.py's generic handler maps
  // them to 404 the same as an unknown question id.
  already_answered: "Ответ уже принят в другом канале.",
});

export function resolveActionErrorMessage(code) {
  return resolveLabel(ACTION_ERROR_MESSAGES, code) || ACTION_ERROR_MESSAGES.internal_error;
}

/**
 * The "disable controls -> runAction -> maybe re-enable" shape every
 * dashboard action control already runs by hand (this task's approve/
 * revise/edit; task 08's later approve/reject/vary/regenerate/hide/
 * retire/reorder -- interfaces.md's ticket-06 note: "таск 08 расширяет
 * этот же модуль"). Second repair, 2026-09-17 (ticket 06 condition 10).
 *
 * `controls` are plain `{disabled}` targets, never real DOM elements --
 * like the rest of this module, `submitAction` itself never touches
 * `document` (see the file banner), so a plain object literal exercises
 * it exactly as well as a real button does. They are disabled for the
 * whole call and re-enabled unless the action both succeeded *and*
 * settled with a confirmed outcome and `reenableOnSuccess` was not asked
 * for -- a genuine, confirmed success is the one case a control should
 * stay disabled for (the caller's own refresh is about to repaint it
 * away); a failure, a `revision_conflict`, or a settled-but-unconfirmed
 * wait (`confirmed === false`, ticket 06 condition 7) all re-enable,
 * since the operator may reasonably want to look again or retry.
 *
 * Status text, refreshing and any other side effect stay the caller's own
 * job -- they differ per action (compare ui/scenario.js's approve/revise/
 * edit handlers) far more than the disable/re-enable shape does.
 *
 * Repair, 2026-09-17 (ticket 08 amendment 11, ticket-06-review point
 * "submitAction возвращает каждому контролу прежнее значение disabled, а
 * не включает всё подряд"). The re-enable branch used to hardcode
 * `control.disabled = false` for every control -- correct only when every
 * control genuinely started enabled. A control task 08 hands in already
 * disabled for an unrelated reason (a sibling "Вариация"/"Перегенерировать"
 * pair that share one confirm row and must not both become clickable the
 * instant either one's own network call settles; a control the current
 * stage does not currently allow at all) used to be silently re-enabled by
 * this function regardless -- a repaint would eventually correct it, but
 * between "failure resolves" and "the caller's own next repaint runs" the
 * control was clickable when it should never have been. Each control's own
 * `disabled` value is read once, before this sets any of them, and that
 * exact prior value -- never a hardcoded `false` -- is what a re-enabling
 * outcome restores.
 */
export async function submitAction({
  actionType,
  targetId,
  payload,
  expectedRevision,
  controls = [],
  awaitUpdate = true,
  waitOptions,
  reenableOnSuccess = false,
  requireActionSuccess = false,
}) {
  const previousDisabled = controls.map((control) => (control ? control.disabled : undefined));
  for (const control of controls) {
    if (control) {
      control.disabled = true;
    }
  }
  // `requireActionSuccess` (дашборд v2): подтверждением считается статус
  // своего `action_id`, а не любой сдвиг ревизии проекта — иначе чужая
  // запись в проект выдала бы проваленное решение за принятое.
  const result = await runAction({
    actionType, targetId, payload, expectedRevision, awaitUpdate, waitOptions, requireActionSuccess,
  });
  const staysDisabled = result.ok && result.confirmed !== false && !reenableOnSuccess;
  if (!staysDisabled) {
    controls.forEach((control, index) => {
      if (control) {
        control.disabled = previousDisabled[index];
      }
    });
  }
  return result;
}
