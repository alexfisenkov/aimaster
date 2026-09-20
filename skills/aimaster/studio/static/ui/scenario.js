// The scenario surface: dashboard's main, first-class content zone (spec
// §2/§2.1/G01), not a secondary inspector panel. Two modes, entirely
// determined by what the snapshot's progressive disclosure has unlocked --
// never guessed from `project.type` or cached client state:
//
//   - "script" (stage 1, `scenario`): the whole script, its version
//     history, pending questions and the real approve/revise controls.
//     `scenes` is absent from the snapshot at this stage (projection.py
//     only adds it from `image_plan` on), so this is the *only* content
//     stage 1 can ever render -- there is nothing here to hide behind CSS.
//   - "scenes" (`image_plan` onward, every later stage too -- spec §2:
//     the scenario surface "остаётся видимой при просмотре проекта"): one
//     block per scene, each showing its own current text and, once scenes
//     carry real time ranges, ui/timeline.js's vertical navigator alongside
//     them, kept in sync through the store's shared `selectedSceneId`.
//
// Editing a scene's block (`edit`, target_id=scene_id) is offered only
// while `edit` is actually in `view_stage.allowed_actions` -- i.e. only at
// `image_plan`; every later stage's blocks render read-only, matching
// decisions.py's own server-side rule ("Решения по карточкам -- только в
// коллекции текущей стадии").
//
// `scenarioModel`/`resolveSceneDisplayText` are pure and exercised by
// tests/ui/scenario-timeline.test.mjs. `renderScenario` and its DOM helpers
// are verified only through the browser visual gate (no DOM under
// `node --test` -- see ui/timeline.js's file banner).
//
// Repair, 2026-09-17 (ticket 06 conditions 1-4, 7, 10). Four fixes to the
// approve/revise/edit controls, folded into this file rather than any
// rewrite of the surrounding structure:
//   1. approve/revise/edit now submit through `runAction` (ui/actions.js),
//      which waits for the decisions worker to actually apply a queued
//      action before this module asks for a snapshot refresh -- see that
//      function's own banner. The old code refreshed on the bare `202`,
//      which usually landed before the worker had run at all.
//   2. `scenarioModel` now also resolves the approved script (`model.
//      script`) whenever `scenes` exists, and `renderScenesLayout` shows it
//      read-only above either the per-scene blocks or, once `scenes` is an
//      empty array (approved but not yet split by chat), a "Сцены ещё не
//      созданы" empty state -- previously this whole surface went blank
//      the instant `scenes` appeared with nothing in it yet.
//   3. `renderScenesLayout` no longer calls `scrollSceneIntoView` itself:
//      it used to run before its own caller (ui/shell.js's `paintMain`)
//      had inserted anything into the live document, so every
//      `scrollIntoView()` call was a silent no-op on a detached node. The
//      scroll now happens in `ui/shell.js`, right after insertion.
//   4. Scene-edit-form drafts (`editDrafts`, below) survive a repaint --
//      selecting a different scene, or this task's own post-save wait --
//      instead of silently resetting to the unedited text every time
//      `buildEditControl` is rebuilt from scratch.
// Condition 7's "Все сцены" deselect control and condition 10's shared
// `requestSceneSelection` (renamed from `timeline.js`'s `selectScene`, to
// stop confusing it with the store method of the same name) round out the
// same pass.
//
// Second repair, 2026-09-17 (ticket 06 conditions 1, 3, 4, 6, 7, 10, 12).
//   1. Scene-edit drafts (`editDrafts`) are now keyed by *project* and
//      scene together (`draftKey`), never scene id alone -- two different
//      projects that happen to number their scenes the same way (chat
//      assigns ids per project, nothing stops two projects both having a
//      "scene-2") used to show and would have submitted one project's
//      unsaved draft into whichever *other* project the operator switched
//      to next.
//   3/4. `requestProjectRefresh` replaces the old bare
//      `document.dispatchEvent(new CustomEvent("studio:retry-snapshot"))`
//      call: it names the *project the action was actually for* (captured
//      once, in `scenarioModel`'s own `projectId`, at render time -- never
//      re-read from whatever happens to be open by the time an async
//      click settles) and app.js's own listener only fetches/repaints when
//      that project is still the one open. A stale action's completion
//      settling after the operator has already moved to a different
//      project used to reload *that* different, still-open project from
//      scratch -- a spurious GET, a loading-skeleton flash, and a wiped
//      scene selection, none of which had anything to do with the project
//      the click was for.
//   6. `reorderScenarioLayout`, below, keeps the timeline/scenario-panel
//      DOM order in sync with the active CSS layout on a bare resize --
//      not only after the next real repaint, which `isDesktopScenarioLayout`
//      alone could never do by itself, since nothing re-evaluates it
//      between two repaints.
//   7. `approve-scenario`/`revise-scenario`/`edit`'s own success handlers
//      now read `result.confirmed` (`runAction`'s new field, ui/actions.js)
//      before claiming success: a settled-but-unconfirmed wait shows a
//      neutral "Исход не подтверждён" instead of the same silent, cleared
//      status a confirmed success gets -- and re-enables the control, so
//      it never looks like the click was simply never sent.
//   10. `submitAction`/`ACTION_ERROR_MESSAGES`/`resolveActionErrorMessage`
//      moved to ui/actions.js (imported below instead of defined here),
//      and all three handlers now submit through the one shared
//      `submitAction` wrapper instead of each hand-rolling its own
//      disable/run/re-enable sequence.
//   12. `renderSceneBlockVersions` (exported for ui/shell.js's inspector)
//      shows the selected scene's own script-block version history,
//      reusing `buildScriptVersions`/`buildScriptVersionsList` exactly as
//      the stage-1 script panel already does for the top-level script --
//      the same shape, `{active_version_id, versions}`, either way.
//
// Ticket 16, 2026-09-18 (G05, return to an approved scenario). Task 15's own
// server contract added a new "scenes" case this module had never seen
// before: `current_stage === "scenario"` while `scenes` still exists,
// reached only via `reopen-scenario` (a fresh project's own `scenario`
// stage never has `scenes` at all -- see `scenarioModel`'s own
// `reopened` field). Three changes, kept inside this file rather than a
// parallel rewrite of the surrounding "scenes" layout:
//   - `buildReopenedScriptPanel` (new) owns that one state -- live
//     approve/revise controls, no "Одобрен" badge -- while
//     `buildApprovedScriptSummary` keeps owning every *other* "scenes"
//     stage exactly as before. Both share `buildApproveReviseControls`
//     (extracted from `renderScriptPanel`, unchanged behaviour) rather than
//     two copies of the same submit protocol.
//   - "Вернуться к сценарию" itself (`ui/scenario-reopen.js`'s
//     `buildReopenControl`) is offered only in the *other* branch --
//     `reopen-scenario` is never in `allowed_actions` at `scenario` itself.
//   - `buildSceneBlock`'s own scene-block edit control needed no new branch
//     at all: `canEdit` already reads straight off `allowed_actions`, and
//     task 15 now lists `edit` there at the reopened stage too -- the same
//     code already serving `image_plan` just keeps working.

import { resolveActionErrorMessage, resolveActionFailureText, submitAction } from "./actions.js";
import { resolveLabel } from "./state.js";
import { buildReopenControl } from "./scenario-reopen.js";
import {
  renderTimeline,
  requestSceneSelection,
  resolveSceneOrder,
  resolveSceneRange,
} from "./timeline.js";

// -----------------------------------------------------------------------
// Pure view-model building
// -----------------------------------------------------------------------

/**
 * The text a scene block actually shows: its active dashboard-edited block
 * version when one exists (`append_scene_block_version`'s own output, see
 * domain.py), otherwise the scene's original `content` -- never both, and
 * never a synthesized combination. An empty result (neither present yet)
 * is the caller's cue to show a neutral "not written yet" placeholder
 * rather than a blank block.
 */
export function resolveSceneDisplayText(scene) {
  const block = scene?.script_block && typeof scene.script_block === "object" ? scene.script_block : null;
  const versions = block && Array.isArray(block.versions) ? block.versions : [];
  const active = versions.find((version) => version?.version_id === block?.active_version_id);
  if (active && typeof active.text === "string" && active.text) {
    return active.text;
  }
  return typeof scene?.content === "string" ? scene.content : "";
}

function buildSceneEntry(scene, position, selectedSceneId) {
  const sceneId = typeof scene?.scene_id === "string" ? scene.scene_id : undefined;
  return {
    sceneId,
    order: resolveSceneOrder(scene, position),
    ...resolveSceneRange(scene),
    displayText: resolveSceneDisplayText(scene),
    linkageStatus: scene?.linkage_status,
    selected: Boolean(selectedSceneId) && sceneId === selectedSceneId,
  };
}

// Task 14 leftover 4 ("Служебная причина версии... не показывается как
// текст интерфейса"): `reason` strings authoring/server code writes for
// its *own* bookkeeping, never typed by a human -- currently exactly one,
// `authoring_scenes.py`'s own literal `"scenes set"`, tagging the block
// version `set_scenes` auto-creates for every scene the instant chat
// splits the script (see that module's `_append_group_version` call). A
// real `--reason`/`payload.reason` a person wrote (via `script add-version`,
// `prompt add-version`, or this file's own edit form) is never restricted
// to an allowlist -- only this one exact internal marker is filtered, denylist-
// style, rather than every other dictionary in this codebase's own
// allowlist-only convention (ui/state.js's `resolveLabel`): `reason` is
// free text in the general case, so there is no fixed set of "known good"
// values to allowlist against.
const INTERNAL_VERSION_REASONS = new Set(["scenes set"]);

function resolveVersionReasonLabel(reason) {
  if (typeof reason !== "string" || !reason || INTERNAL_VERSION_REASONS.has(reason)) {
    return "";
  }
  return reason;
}

function buildScriptVersions(script) {
  const versions = Array.isArray(script?.versions) ? script.versions : [];
  const activeVersionId = script?.active_version_id;
  return versions.map((version, index) => ({
    versionId: typeof version?.version_id === "string" ? version.version_id : undefined,
    ordinal: index + 1,
    text: typeof version?.text === "string" ? version.text : "",
    reason: resolveVersionReasonLabel(version?.reason),
    active: Boolean(activeVersionId) && version?.version_id === activeVersionId,
  }));
}

/**
 * Build the scenario surface's pure view model. `kind`:
 *   - "empty": no project, or a project with neither `scenes` nor a
 *     started script yet (the caller falls back to the existing "Сценарий
 *     ещё не создан" empty state -- ui/shell.js's `buildScenarioSlot`).
 *   - "script": stage 1 -- see the file banner.
 *   - "scenes": `image_plan` onward -- see the file banner. Always
 *     carries `script` too (`{versions}`, or `null` on the -- not expected
 *     in practice, since scenes never exist before a script does --
 *     defensive case of no script at all): ticket 06 condition 2/G01/R26,
 *     "завершённая стадия не исчезает" -- the approved script stays
 *     visible, read-only, at every stage from `image_plan` on, not only
 *     while `scenes` is still empty.
 *
 * Both "script" and "scenes" also carry `projectId` (second repair,
 * 2026-09-17, ticket 06 conditions 1/3/4): *this* snapshot's own project
 * id, not whatever project happens to be open by the time an async click
 * later settles -- `editDrafts`' cross-project isolation and
 * `requestProjectRefresh`'s "only refresh if this project is still open"
 * check both depend on capturing it here, once, at render time.
 */
export function scenarioModel(snapshot, selectedSceneId) {
  const project = snapshot && typeof snapshot === "object" ? snapshot.active_project : null;
  if (!project || typeof project !== "object") {
    return { kind: "empty" };
  }
  const viewStage = snapshot.view_stage && typeof snapshot.view_stage === "object" ? snapshot.view_stage : {};
  const allowedActions = Array.isArray(viewStage.allowed_actions) ? viewStage.allowed_actions : [];
  const revision = Number.isFinite(snapshot.revision) ? snapshot.revision : undefined;
  const projectId = typeof project.id === "string" ? project.id : undefined;

  const scenes = Array.isArray(project.scenes) ? project.scenes : undefined;
  if (scenes) {
    const approvedVersions = buildScriptVersions(project.script);
    return {
      kind: "scenes",
      revision,
      projectId,
      canEdit: allowedActions.includes("edit"),
      scenes: scenes.map((scene, position) => buildSceneEntry(scene, position, selectedSceneId)),
      script: approvedVersions.length > 0 ? { versions: approvedVersions } : null,
      // Ticket 16/G05: `scenes` now also exists on the `scenario` stage
      // itself once a return-to-scenario has happened (task 15's
      // projection: "на стадии scenario при существующих сценах отдаёт
      // scenes... без links") -- the *only* way this "scenes" kind is ever
      // reached with `current_stage === "scenario"`, since scenes never
      // exist before a first approval already split them. `canApprove`/
      // `canRevise` mirror the "script" kind below exactly (the server only
      // ever lists `approve-scenario`/`revise-scenario` at that one stage),
      // and `viewStage`/`actions` are threaded through for
      // `buildReopenControl`'s own gating and pending-action check.
      reopened: viewStage.current_stage === "scenario",
      canApprove: allowedActions.includes("approve-scenario"),
      canRevise: allowedActions.includes("revise-scenario"),
      viewStage,
      actions: Array.isArray(snapshot.actions) ? snapshot.actions : [],
    };
  }

  const versions = buildScriptVersions(project.script);
  if (versions.length === 0) {
    return { kind: "empty" };
  }
  const activeVersion = versions.find((version) => version.active) || versions[versions.length - 1];
  const questions = Array.isArray(snapshot.questions)
    ? snapshot.questions.filter((question) => question && typeof question.question_id === "string")
    : [];
  return {
    kind: "script",
    revision,
    projectId,
    versions,
    activeText: activeVersion ? activeVersion.text : "",
    canApprove: allowedActions.includes("approve-scenario"),
    canRevise: allowedActions.includes("revise-scenario"),
    questions,
  };
}

function formatStoryboardTime(milliseconds) {
  if (!Number.isInteger(milliseconds) || milliseconds < 0) {
    return "";
  }
  const seconds = Math.floor(milliseconds / 1000);
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
}

function lastScenarioBaselineSeq(history) {
  let baseline = 0;
  for (const entry of Array.isArray(history) ? history : []) {
    if (
      entry?.stage === "scenario" &&
      (entry.kind === "scenes-ready" || entry.kind === "stage-approved") &&
      Number.isInteger(entry.seq)
    ) {
      baseline = Math.max(baseline, entry.seq);
    }
  }
  return baseline;
}

/**
 * Pure Task-35 model for the new step-1 surface. History is intentionally
 * treated as the visible snapshot window only (projection caps it at 200),
 * never as a complete lifetime audit of the project.
 */
export function storyboardModel(snapshot, { readOnly = false } = {}) {
  const project = snapshot?.active_project && typeof snapshot.active_project === "object"
    ? snapshot.active_project
    : null;
  if (!project) {
    return { kind: "empty", scenes: [], historyLimited: true };
  }
  const viewStage = snapshot?.view_stage && typeof snapshot.view_stage === "object"
    ? snapshot.view_stage
    : {};
  const allowedActions = Array.isArray(viewStage.allowed_actions) ? viewStage.allowed_actions : [];
  const scriptVersions = buildScriptVersions(project.script);
  const activeScript = scriptVersions.find((version) => version.active) || scriptVersions.at(-1) || null;
  const history = Array.isArray(project.history) ? project.history : [];
  const baselineSeq = lastScenarioBaselineSeq(history);
  const changedSceneIds = new Set(
    history
      .filter(
        (entry) =>
          entry?.stage === "scenario" &&
          entry.actor === "you" &&
          entry.kind === "scene-edited" &&
          Number.isInteger(entry.seq) &&
          entry.seq > baselineSeq &&
          typeof entry.params?.scene_id === "string",
      )
      .map((entry) => entry.params.scene_id),
  );
  const isPhoto = project.type === "photo";
  const rawScenes = Array.isArray(project.scenes) ? project.scenes : [];
  const scenes = rawScenes.map((scene, position) => {
    const sceneId = typeof scene?.scene_id === "string" ? scene.scene_id : "";
    const title = typeof scene?.title === "string" ? scene.title : "";
    const text = resolveSceneDisplayText(scene);
    const durationMs = !isPhoto && Number.isInteger(scene?.duration_ms) ? scene.duration_ms : null;
    const titleValid = Boolean(title.trim());
    const durationValid = isPhoto || (Number.isInteger(durationMs) && durationMs >= 1000 && durationMs % 1000 === 0);
    const start = !isPhoto ? formatStoryboardTime(scene?.start_ms) : "";
    const end = !isPhoto ? formatStoryboardTime(scene?.end_ms) : "";
    return {
      sceneId,
      order: resolveSceneOrder(scene, position),
      title,
      text,
      durationMs,
      durationSeconds: durationMs === null ? null : durationMs / 1000,
      rangeLabel: start && end ? `${start}–${end}` : "",
      changedByYou: changedSceneIds.has(sceneId),
      valid: titleValid && durationValid,
      errors: {
        title: titleValid ? "" : "Введите название кадра.",
        duration: durationValid ? "" : "Длительность должна быть не меньше 1 секунды.",
      },
    };
  });
  const totalDurationMs = isPhoto
    ? null
    : scenes.reduce((sum, scene) => sum + (Number.isInteger(scene.durationMs) ? scene.durationMs : 0), 0);
  const current = viewStage.current_stage === "scenario" && !readOnly;
  const storyboardComplete = scenes.length > 0 && scenes.every((scene) => scene.valid);
  return {
    kind: "storyboard",
    projectId: typeof project.id === "string" ? project.id : "",
    projectType: project.type,
    revision: Number.isFinite(snapshot?.revision) ? snapshot.revision : undefined,
    activeScriptText: activeScript?.text || "",
    activeScriptVersion: activeScript?.ordinal || null,
    activeScriptVersionId: activeScript?.versionId || null,
    scriptApproved: !current,
    canEdit: current && allowedActions.includes("edit"),
    canAdd: current && allowedActions.includes("scene-add"),
    canReorder: current && allowedActions.includes("reorder"),
    canApprove: current && allowedActions.includes("approve-scenario") && storyboardComplete,
    canRevise: current && allowedActions.includes("revise-scenario"),
    actions: Array.isArray(snapshot?.actions) ? snapshot.actions : [],
    approveHint: storyboardComplete
      ? ""
      : scenes.length === 0
        ? "Добавьте хотя бы один кадр."
        : "Заполните названия и длительность кадров.",
    scenes,
    totalDurationMs,
    totalDurationLabel: totalDurationMs === null ? "" : formatStoryboardTime(totalDurationMs),
    historyLimited: true,
  };
}

// -----------------------------------------------------------------------
// DOM rendering -- browser-gate-only, see the file banner.
// -----------------------------------------------------------------------

// The neutral text shown when `runAction`/`submitAction`'s wait settles
// without ever confirming the decision worker actually applied the click
// (ticket 06 condition 7: `result.confirmed === false`). Reuses the exact
// phrase ui/media.js's own `MEDIA_STATUS_LABELS.outcome_unknown` already
// shows for the conceptually adjacent "a generation's own outcome could
// not be confirmed" case, rather than inventing a second one -- this is
// not an error (the click really was sent and accepted), just an
// unconfirmed result.
const OUTCOME_UNCONFIRMED_TEXT = "Исход не подтверждён. Обновите страницу.";

/**
 * Ask app.js to refresh `projectId`'s own snapshot in place -- no loading
 * skeleton, no reset scene selection, unlike a full `openProject` (ticket
 * 06 conditions 3/4). `projectId` must be the project the action that
 * triggered this refresh was actually for (`scenarioModel`'s own
 * `projectId`, captured once per render -- see `renderScriptPanel`/
 * `buildEditControl`'s call sites below), not whatever happens to be open
 * by the time an async click settles: app.js's own listener is what
 * decides whether that project is still the one on screen, and does
 * nothing at all (no GET, no repaint) when it is not.
 */
function requestProjectRefresh(projectId) {
  document.dispatchEvent(
    new CustomEvent("studio:refresh-snapshot", { bubbles: true, detail: { projectId } }),
  );
}

// --- stage 1: script panel ----------------------------------------------

function buildScriptVersionItem(version) {
  const li = document.createElement("li");
  li.className = "script-version";
  if (version.versionId) {
    li.dataset.versionId = version.versionId;
  }
  li.dataset.selected = String(version.active);

  const meta = document.createElement("div");
  meta.className = "script-version-meta";
  const badge = document.createElement("span");
  badge.className = "media-version-badge";
  badge.textContent = `v${version.ordinal}`;
  meta.append(badge);
  if (version.active) {
    const current = document.createElement("span");
    current.className = "media-current-badge";
    current.textContent = "Текущая";
    meta.append(current);
  }
  if (version.reason) {
    const reason = document.createElement("span");
    reason.className = "script-version-reason";
    reason.textContent = version.reason;
    meta.append(reason);
  }

  const text = document.createElement("p");
  text.className = "script-version-text";
  text.textContent = version.text;

  li.append(meta, text);
  return li;
}

/** Shared by the stage-1 script panel and, from `image_plan` on, the
 * read-only approved-script summary (`buildApprovedScriptSummary`) --
 * exactly the same version markup either way, only the surrounding
 * controls differ. */
function buildScriptVersionsList(versions) {
  const list = document.createElement("ol");
  list.className = "script-version-list";
  for (const version of versions) {
    list.append(buildScriptVersionItem(version));
  }
  return list;
}

/**
 * The approve/revise controls shared by stage 1's own script panel
 * (`renderScriptPanel`, below) and, since ticket 16, the reopened-scenario
 * panel `buildReopenedScriptPanel` shows once `reopen-scenario` has sent the
 * project's milestones back to `draft` while `scenes` still exist. Both
 * callers pass the exact same shape -- `{revision, canApprove, canRevise,
 * projectId}` -- so this is one submit protocol, not two copies that could
 * silently drift apart (the same "one client, taught once" reasoning
 * ui/actions.js's own `submitAction` already documents).
 */
function buildApproveReviseControls({ revision, canApprove, canRevise, projectId }) {
  const actions = document.createElement("div");
  actions.className = "scenario-actions";
  const status = document.createElement("p");
  status.className = "scenario-action-status";
  status.setAttribute("role", "status");

  const approveButton = document.createElement("button");
  approveButton.type = "button";
  approveButton.className = "scenario-approve-button";
  approveButton.dataset.action = "approve-scenario";
  approveButton.textContent = "Одобрить сценарий";
  approveButton.disabled = !canApprove;

  const reviseButton = document.createElement("button");
  reviseButton.type = "button";
  reviseButton.className = "scenario-revise-button";
  reviseButton.dataset.action = "revise-scenario";
  reviseButton.textContent = "Отправить на доработку";
  reviseButton.disabled = !canRevise;

  approveButton.addEventListener("click", async () => {
    status.textContent = "Отправляется…";
    // `submitAction` (ui/actions.js) disables both controls for the call
    // and waits for the decisions worker to actually apply this action --
    // see its own banner for why the old "refresh on the bare 202" version
    // showed stage 1 with a stale, still-enabled button roughly 7ms after
    // every click (ticket 06 condition 1). It re-enables both controls on
    // its own unless the wait genuinely confirmed the revision moved, so
    // the only two things left for this handler to decide are the status
    // text and whether to refresh.
    const result = await submitAction({
      actionType: "approve-scenario",
      targetId: "scenario",
      payload: {},
      expectedRevision: revision,
      controls: [approveButton, reviseButton],
    });
    if (result.ok && result.confirmed === false) {
      // Settled but unconfirmed (ticket 06 condition 7): the click really
      // was sent and accepted, so this says so neutrally -- and,
      // deliberately, requests no refresh. Live-browser testing against a
      // real stalled decision worker found that refreshing here raced its
      // own repaint against this very message: the fetch it triggers
      // rebuilds the whole panel with a fresh, empty status the instant it
      // lands, which on an unchanged project (still `scenario`, still
      // approvable) happens fast enough that the message was never
      // visible at all -- indistinguishable from "nothing was sent",
      // exactly what this condition exists to prevent.
      status.textContent = OUTCOME_UNCONFIRMED_TEXT;
      return;
    }
    if (result.ok) {
      // A genuinely confirmed success: the revision moved, so the refresh
      // below will very likely repaint this whole panel away (image_plan
      // opening) -- leave both buttons disabled (submitAction's own job)
      // rather than flash them back on for a moment.
      status.textContent = "";
      requestProjectRefresh(projectId);
      return;
    }
    status.textContent = resolveActionErrorMessage(result.code);
    if (result.code === "revision_conflict") {
      requestProjectRefresh(projectId);
    }
  });

  reviseButton.addEventListener("click", async () => {
    status.textContent = "Отправляется…";
    // `revise-scenario` is a chat-only action type (runner.CHAT_ACTION_TYPES):
    // it never auto-applies in this process, so success here only means
    // "queued for chat" -- the milestone and both buttons' enabled state
    // stay exactly as the current snapshot already says, never optimistically
    // advanced. `awaitUpdate: false` -- nothing here will ever change
    // canonical state, so there is nothing to wait for; `reenableOnSuccess:
    // true` is what makes `submitAction` re-enable both controls even on
    // this "queued" success, since -- unlike approve-scenario -- nothing
    // about this project's revision is expected to move because of it.
    const result = await submitAction({
      actionType: "revise-scenario",
      targetId: "scenario",
      payload: {},
      expectedRevision: revision,
      controls: [approveButton, reviseButton],
      awaitUpdate: false,
      reenableOnSuccess: true,
    });
    status.textContent = result.ok ? "Передано в чат." : resolveActionErrorMessage(result.code);
    if (!result.ok && result.code === "revision_conflict") {
      requestProjectRefresh(projectId);
    }
  });

  actions.append(approveButton, reviseButton, status);
  return actions;
}

function renderScriptPanel(root, model) {
  const panel = document.createElement("div");
  panel.className = "scenario-script";

  const heading = document.createElement("h2");
  heading.textContent = "Сценарий";
  // Ticket 16 condition 1 ("фокус — на заголовке сценария" after a
  // confirmed reopen): the one hook ui/shell.js's `focusScenarioHeadingIfPending`
  // looks for, once the reopened repaint has actually landed. Also present
  // on `buildReopenedScriptPanel`'s own heading below -- deliberately absent
  // from `buildApprovedScriptSummary`'s (the *not*-reopened "Одобрен" case),
  // so an unrelated repaint landing before the reopen has actually applied
  // can never match this hook and steal focus prematurely.
  heading.dataset.hook = "scenario-heading";
  panel.append(heading, buildScriptVersionsList(model.versions));


  panel.append(
    buildApproveReviseControls({
      revision: model.revision,
      canApprove: model.canApprove,
      canRevise: model.canRevise,
      projectId: model.projectId,
    }),
  );
  root.append(panel);
}

// --- image_plan onward: per-scene blocks --------------------------------

function buildOverlapBadge() {
  const badge = document.createElement("span");
  badge.className = "scenario-block-overlap-badge";
  badge.textContent = "Пересекается по времени с другой сценой";
  return badge;
}

// Ticket 16 condition 3 ("сцены с review_linkage помечены... подпись из
// одного словаря") -- the one allowlist source for this badge's own text.
// Ticket 17 condition 1 (orchestrator correction, 2026-09-17, to ticket 16):
// the badge reads "на пересмотр" -- ticket 16's own line 46 wording -- not
// the spec's earlier literal draft phrase. spec.md §9's failure-recovery
// sentence (link update fails after the version save) names this same
// status and was updated to the same final wording so the two sources
// don't diverge. Sourced from this one dictionary, not a bespoke inline
// string, so this stays exactly the same text whether a scene entered
// review_linkage from an `edit` at `image_plan` or an `edit` at the reopened
// `scenario` stage: `buildSceneBlock` below is
// stage-agnostic and never special-cases the reopened case for this one
// badge.
const SCENE_LINKAGE_LABELS = Object.freeze({
  review_linkage: "на пересмотр",
});

function buildLinkageBadge(label) {
  const badge = document.createElement("span");
  badge.className = "scenario-block-linkage-badge";
  badge.textContent = label;
  return badge;
}

// Per-scene edit-form drafts that survive a full repaint of the scenario
// surface -- selecting a different scene, or this task's own post-save
// wait for the decisions worker (ticket 06 condition 4: "Выбор сцены не
// уничтожает фокус и черновик... Сообщение о 409 не стирается
// перерисовкой, черновик сохраняется"). `renderScenesLayout`/
// `renderScenario` rebuild every scene's block from scratch on every
// commit (see ui/shell.js's own note that this surface, unlike ui/rail.js,
// never patches in place) -- without this, `buildEditControl` had no way
// to tell "the operator has an open, half-written edit for scene X" from
// "scene X has never been edited", and reset both to the same blank state.
// Presentation-only scratch state, deliberately outside the store, exactly
// like app.js's own `railOpenIntent` (see that file's banner) -- scoped to
// scene ids that currently exist via `pruneEditDrafts`, called from
// `renderScenario` on every "scenes" paint, so a retired/reordered-away
// scene's draft cannot linger for the rest of the session.
//
// Second repair, 2026-09-17 (ticket 06 condition 1: "черновик привязан к
// паре «проект + сцена»"). Keyed by `draftKey(projectId, sceneId)`, never
// scene id alone: chat assigns scene ids per project, nothing stops two
// different projects from both having a "scene-2", and this map is
// module-level, shared across every project the dashboard ever opens in
// one page session -- keying by scene id alone let one project's unsaved
// draft appear, and would have been submitted, in whichever *other*
// project the operator switched to next.
const editDrafts = new Map();

/**
 * The one function that decides `editDrafts`' key -- exported so
 * tests/ui/scenario-timeline.test.mjs can assert the cross-project
 * isolation directly (ticket 06 condition 1: "мутация «ключ только по
 * сцене» краснеет") without needing a DOM to drive `buildEditControl`
 * itself.
 */
export function draftKey(projectId, sceneId) {
  return `${projectId}::${sceneId}`;
}

/** Drop every draft keyed under `projectId` whose scene id is not in
 * `sceneIds` -- *only* this project's own entries; a different project's
 * drafts, however many scene ids they happen to share with this one, are
 * untouched (each is pruned in turn only when *that* project is itself
 * rendered in "scenes" mode). */
function pruneEditDrafts(projectId, sceneIds) {
  const known = new Set(sceneIds.map((sceneId) => draftKey(projectId, sceneId)));
  const prefix = `${projectId}::`;
  for (const key of editDrafts.keys()) {
    if (key.startsWith(prefix) && !known.has(key)) {
      editDrafts.delete(key);
    }
  }
}

/**
 * Task 14 leftover 1: cancels a *matching* pending-focus note the edit
 * form's own submit handler dispatched via `studio:scene-focus-pending`
 * (see `buildEditControl`'s submit handler, below) -- used exactly when
 * that submit did *not* end in a refresh, so nothing else is ever going to
 * consume the note productively. `hook`/`sceneId` (`clear:true`) let
 * ui/shell.js's own listener cancel only the note this exact dispatch set,
 * never a different, newer one another scene's edit may have queued in the
 * meantime (a low-probability but real race between two concurrently
 * in-flight submits) -- see that listener's own comment for the match.
 */
function clearPendingSceneFocus(sceneId) {
  if (!sceneId) {
    return;
  }
  document.dispatchEvent(
    new CustomEvent("studio:scene-focus-pending", {
      bubbles: true,
      detail: { hook: "scenario-edit-save", sceneId, clear: true },
    }),
  );
}

// Ticket 16 condition 5: a server refusal while editing a scene uses the
// public message dictionary, never raw server text. Stage and payload
// checks run inside the decisions worker, *after* the POST already
// answered 202 -- so such a refusal never reaches `submitAction`'s own
// `result.code` at all; it only ever shows up, later, as this exact scene's
// own `edit` entry in a freshly fetched `snapshot.actions` turning `failed`
// (task 08's `latest_actions_by_target`, carrying a server-computed
// `message` this module deliberately never renders raw -- see the file
// banner's own allowlist-everywhere convention). `buildEditControl` below
// reads this fresh on every repaint, the same way ui/scenario-reopen.js's
// `resolveReopenFailureText` does for `reopen-scenario` -- both now share
// actions.js's `resolveActionFailureText` for the actual (action_type,
// target_id) lookup (ticket 17 condition 1), rather than each keeping its
// own copy of that same `find`.
export const SCENE_EDIT_FAILURE_TEXT = "Не удалось сохранить правку. Проверьте актуальность сценария в чате.";

export function resolveSceneEditFailureText(actions, sceneId) {
  return resolveActionFailureText(actions, "edit", sceneId, SCENE_EDIT_FAILURE_TEXT);
}

function buildEditControl(entry, revision, projectId, actions) {
  const wrap = document.createElement("div");
  wrap.className = "scenario-edit";
  const draft = entry.sceneId ? editDrafts.get(draftKey(projectId, entry.sceneId)) : undefined;
  // A fresh, server-confirmed failure always wins over a stale draft
  // message from a *previous* attempt -- once a new one supersedes it
  // (succeeds, or simply has not failed), this resolves to `undefined` and
  // the draft's own message (if any) takes over again below.
  const editFailureText = resolveSceneEditFailureText(actions, entry.sceneId);

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "scenario-edit-toggle";
  toggle.textContent = "Править";
  // Repair 1, ticket 14 (review: "«Править»" among the six control types
  // an unrelated background repaint dropped focus from) -- real hooks so
  // ui/state.js's SCENE_FOCUS_HOOKS/ui/shell.js's captureSceneFocus can
  // find this exact button again after the block it lives in is rebuilt
  // from scratch, the same way every other scene-linked control here
  // already does.
  if (entry.sceneId) {
    toggle.dataset.hook = "scenario-edit-toggle";
    toggle.dataset.sceneId = entry.sceneId;
  }

  const form = document.createElement("form");
  form.className = "scenario-edit-form";
  form.hidden = !draft?.open;

  const textLabel = document.createElement("label");
  textLabel.className = "scenario-edit-label";
  const textCaption = document.createElement("span");
  textCaption.textContent = "Текст сцены";
  const textarea = document.createElement("textarea");
  textarea.className = "scenario-edit-textarea";
  textarea.dataset.hook = "scenario-edit-textarea";
  if (entry.sceneId) {
    textarea.dataset.sceneId = entry.sceneId;
  }
  textarea.required = true;
  textarea.value = draft ? draft.text : entry.displayText || "";
  textLabel.append(textCaption, textarea);

  const reasonLabel = document.createElement("label");
  reasonLabel.className = "scenario-edit-label";
  const reasonCaption = document.createElement("span");
  reasonCaption.textContent = "Причина правки";
  const reasonInput = document.createElement("input");
  reasonInput.type = "text";
  reasonInput.className = "scenario-edit-reason";
  reasonInput.dataset.hook = "scenario-edit-reason";
  if (entry.sceneId) {
    reasonInput.dataset.sceneId = entry.sceneId;
  }
  reasonInput.required = true;
  reasonInput.value = draft ? draft.reason : "";
  reasonLabel.append(reasonCaption, reasonInput);

  const status = document.createElement("p");
  status.className = "scenario-edit-status";
  status.setAttribute("role", "status");
  status.textContent = editFailureText || (draft ? draft.message : "");

  const actionsRow = document.createElement("div");
  actionsRow.className = "scenario-edit-actions";
  const saveButton = document.createElement("button");
  saveButton.type = "submit";
  saveButton.textContent = "Сохранить";
  const cancelButton = document.createElement("button");
  cancelButton.type = "button";
  cancelButton.textContent = "Отмена";
  // `data-hook`/`data-scene-id` on both (second repair, 2026-09-17, ticket
  // 06 condition 4): a mouse click focuses the button it lands on, so by
  // the time "Сохранить"'s own submit handler below settles and this
  // scene's block gets torn down and rebuilt, focus is very often still
  // sitting on one of these two, not the textarea -- ui/state.js's
  // `SCENE_FOCUS_HOOKS` and ui/shell.js's capture/restore need real hooks
  // here to have anything to find. The rebuilt block's own scene header
  // (`scenario-block-select`) is ui/shell.js's fallback once the form
  // collapses on a genuine save, so focus never falls to `<body>`.
  if (entry.sceneId) {
    saveButton.dataset.hook = "scenario-edit-save";
    saveButton.dataset.sceneId = entry.sceneId;
    cancelButton.dataset.hook = "scenario-edit-cancel";
    cancelButton.dataset.sceneId = entry.sceneId;
  }
  actionsRow.append(saveButton, cancelButton);

  form.append(textLabel, reasonLabel, status, actionsRow);

  function saveDraft() {
    if (!entry.sceneId) {
      return;
    }
    editDrafts.set(draftKey(projectId, entry.sceneId), {
      open: !form.hidden,
      text: textarea.value,
      reason: reasonInput.value,
      message: status.textContent,
    });
  }

  toggle.addEventListener("click", () => {
    form.hidden = !form.hidden;
    if (!form.hidden) {
      textarea.focus();
    }
    saveDraft();
  });
  textarea.addEventListener("input", saveDraft);
  reasonInput.addEventListener("input", saveDraft);
  cancelButton.addEventListener("click", () => {
    form.hidden = true;
    textarea.value = entry.displayText || "";
    reasonInput.value = "";
    status.textContent = "";
    if (entry.sceneId) {
      editDrafts.delete(draftKey(projectId, entry.sceneId));
    }
    toggle.focus();
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = textarea.value.trim();
    const reason = reasonInput.value.trim();
    if (!text || !reason) {
      status.textContent = "Заполните текст и причину правки.";
      saveDraft();
      return;
    }
    status.textContent = "Сохраняется…";
    saveDraft();
    // Second repair, 2026-09-17 (ticket 06 condition 4): `submitAction`
    // (below) disables "Сохранить" *synchronously*, before its own first
    // await -- and a browser blurs a disabled, focused button to `<body>`
    // immediately, well before the eventual repaint. Live-browser testing
    // found focus already stranded on `<body>` by the time ui/shell.js's
    // own capture ever ran, so this notes the scene *now*, while
    // `document.activeElement` still genuinely is this button, for
    // `ui/shell.js`'s `renderShell` to fall back to once its own capture
    // (which only sees whatever is focused *at repaint time*) comes back
    // empty.
    if (entry.sceneId) {
      document.dispatchEvent(
        new CustomEvent("studio:scene-focus-pending", {
          bubbles: true,
          detail: { hook: "scenario-edit-save", sceneId: entry.sceneId },
        }),
      );
    }
    // Same shared pipeline as approve-scenario, so "Сохранить" waits for
    // the new block version to actually exist before the refresh below
    // shows it (ticket 06 condition 4: "дождись обновления, как в п. 1").
    // `submitAction` (ui/actions.js) owns disabling/re-enabling both
    // controls; re-enabling happens automatically unless the wait settled
    // with a genuinely confirmed revision move.
    const result = await submitAction({
      actionType: "edit",
      targetId: entry.sceneId,
      payload: { text, reason },
      expectedRevision: revision,
      controls: [saveButton, cancelButton],
    });
    if (result.ok && result.confirmed !== false) {
      if (entry.sceneId) {
        editDrafts.delete(draftKey(projectId, entry.sceneId));
      }
      // Controls stay disabled/the form stays as it is: the repaint a
      // real revision change triggers rebuilds this whole block from the
      // fresh snapshot, with the new version already active.
      requestProjectRefresh(projectId);
      return;
    }
    // Task 14 leftover 2: an abandoned wait (the operator switched
    // projects mid-wait, ui/actions.js's `waitForProjectUpdate` own
    // `abandoned` flag) is not this project's problem to keep showing --
    // by the time this continuation runs, `main` has already been torn
    // down and rebuilt for whatever project is now open (`store.
    // selectProject`'s own commit already repainted it), so `status`/
    // `textarea` here are detached nodes nobody is looking at. Discarding
    // the draft outright, rather than persisting it with a stale "Исход не
    // подтверждён", is what keeps "по возвращении... повторная отправка не
    // создаёт дубль версии" true: a fresh `openProject` fetch on return
    // shows the true current state (already updated if the edit actually
    // went through), and there is no leftover draft inviting a second,
    // duplicate submit of an edit that may already have landed.
    if (result.ok && result.abandoned) {
      if (entry.sceneId) {
        editDrafts.delete(draftKey(projectId, entry.sceneId));
      }
      clearPendingSceneFocus(entry.sceneId);
      return;
    }
    if (result.ok) {
      // Settled but unconfirmed (ticket 06 condition 7): the click really
      // was sent and accepted -- says so neutrally and keeps the draft,
      // since the decisions worker may simply still be catching up, and
      // discarding the operator's own typed text on a mere guess would be
      // worse than leaving it in place for another look or attempt.
      // Deliberately requests no refresh here -- see approveButton's own
      // note on why racing a refresh against this exact message risks
      // erasing it (live-browser tested against a real stalled worker).
      status.textContent = OUTCOME_UNCONFIRMED_TEXT;
      saveDraft();
      // Task 14 leftover 1: no refresh means no repaint will drain the
      // pending-focus note this handler dispatched above -- left alone, it
      // would resurface on the *next*, unrelated repaint (a different
      // scene's own selection, task 14's own background poll) and steal
      // focus onto this scene's "Сохранить" the instant that fires,
      // exactly the "чужая кнопка «Сохранить»" bug the ticket names.
      // Cleared explicitly instead: the operator is still looking at this
      // very form, so there is nothing for the note to restore focus *to*.
      clearPendingSceneFocus(entry.sceneId);
      return;
    }
    status.textContent = resolveActionErrorMessage(result.code);
    // The draft (including this message) is saved *before* the refresh a
    // `revision_conflict` triggers below repaints this block away and
    // rebuilds it fresh -- so the rebuilt form reopens with the same text
    // and the same message still showing, never silently reset (ticket 06
    // condition 4: "Сообщение о 409 не стирается перерисовкой, черновик
    // сохраняется").
    saveDraft();
    if (result.code === "revision_conflict") {
      // The refresh below repaints this exact scene's block shortly, which
      // is the normal, *legitimate* consumer of the pending-focus note
      // dispatched above (it puts focus right back on this same,
      // freshly-rebuilt "Сохранить") -- left alone on purpose, unlike the
      // two branches above.
      requestProjectRefresh(projectId);
    } else {
      // Task 14 leftover 1 (see the unconfirmed branch's own note above):
      // every other failure code never triggers a refresh at all, so the
      // same stale-note risk applies here too.
      clearPendingSceneFocus(entry.sceneId);
    }
  });

  wrap.append(toggle, form);
  return wrap;
}

function buildSceneBlock(entry, canEdit, revision, projectId, actions) {
  const li = document.createElement("li");
  li.className = "scenario-block";
  if (entry.sceneId) {
    li.dataset.sceneId = entry.sceneId;
  }
  li.dataset.selected = String(entry.selected);

  const header = document.createElement("button");
  header.type = "button";
  header.className = "scenario-block-select";
  header.dataset.hook = "scenario-block-select";
  if (entry.sceneId) {
    header.dataset.sceneId = entry.sceneId;
  }
  if (entry.selected) {
    header.setAttribute("aria-current", "true");
  }
  const order = document.createElement("span");
  order.className = "scenario-block-order";
  order.textContent = String(entry.order);
  header.append(order);
  if (entry.rangeLabel) {
    const range = document.createElement("span");
    range.className = "scenario-block-range";
    range.textContent = entry.rangeLabel;
    header.append(range);
  }
  const srLabel = document.createElement("span");
  srLabel.className = "visually-hidden";
  srLabel.textContent = entry.selected ? `Сцена ${entry.order}, выбрана` : `Выбрать сцену ${entry.order}`;
  header.append(srLabel);
  header.addEventListener("click", () => requestSceneSelection(entry.sceneId, "scenario"));

  const body = document.createElement("div");
  body.className = "scenario-block-body";
  const text = document.createElement("p");
  text.className = "scenario-block-text";
  text.textContent = entry.displayText || "Текст сцены ещё не написан.";
  body.append(text);

  if (entry.overlapping) {
    body.append(buildOverlapBadge());
  }
  const linkageLabel = resolveLabel(SCENE_LINKAGE_LABELS, entry.linkageStatus);
  if (linkageLabel) {
    body.append(buildLinkageBadge(linkageLabel));
  }
  if (canEdit && entry.sceneId) {
    body.append(buildEditControl(entry, revision, projectId, actions));
  }

  li.append(header, body);
  return li;
}

// Task 14 repair 1, condition 2 ("раскрытые пользователем версии"
// survive a repaint). `buildCollapsedScriptVersionItem` below decides each
// `<details>`'s starting `open` purely from `version.active` (leftover
// 5) -- correct for a fresh mount, but a repaint that rebuilds this list
// from scratch (every poll-triggered snapshot swap, any other unrelated
// commit) used to silently re-collapse whichever *other* version the
// operator had manually opened to compare against the current one, and
// just as silently re-open one they had manually collapsed.
//
// Repair 2, ticket 14 condition 13 (craft review finding 1). Two bugs,
// both fixed here together since they touch the same map:
//
// 1. Keyed by version id alone used to be the design -- the comment here
//    used to argue no project scoping was needed, since a real version id
//    is server-generated and never reused across projects. Live review
//    found that argument does not hold up in practice (two projects whose
//    own fixtures/history happened to produce the same version id string
//    both read and wrote the *same* map entry: "script-v1 проекта e-plan
//    раскрыт, потому что в a-live он текущий"). `versionOverrideKey` below
//    is the same `draftKey`-style `${projectId}::${versionId}` composite
//    `editDrafts` above already uses, closing that off the same way.
// 2. Real Chrome fires a native "toggle" event even for the *programmatic*
//    `details.open = ...` assignment in `buildCollapsedScriptVersionItem`
//    below, not only for a genuine click/keyboard interaction (confirmed
//    live) -- dom-stubs.mjs's own fake DOM never auto-dispatches "toggle"
//    at all, which is exactly why the pre-repair test suite stayed green
//    through this. Left unguarded, that spurious event landed in the very
//    same listener and recorded "opened by the operator" for a version
//    nobody ever touched; once a new version became current, the old one
//    (v1 in the review's own repro) stayed open forever, since its own
//    override now permanently disagreed with `version.active`. See that
//    function's own `ignoreNextToggle` for the fix.
//
// `pruneVersionDisclosureOverrides`, called every time the summary itself
// is rebuilt, drops any override for *this* project's own version ids that
// are no longer in its history -- a different project's entries, sharing
// the exact same `${projectId}::` prefix scoping `pruneEditDrafts` above
// already uses, are left untouched.
const versionDisclosureOverrides = new Map();

function versionOverrideKey(projectId, versionId) {
  return `${projectId}::${versionId}`;
}

function pruneVersionDisclosureOverrides(projectId, knownVersionIds) {
  const known = new Set(knownVersionIds.map((versionId) => versionOverrideKey(projectId, versionId)));
  const prefix = `${projectId}::`;
  for (const key of versionDisclosureOverrides.keys()) {
    if (key.startsWith(prefix) && !known.has(key)) {
      versionDisclosureOverrides.delete(key);
    }
  }
}

/**
 * One version row for the approved-script summary -- a native `<details>`
 * disclosure, collapsed by default and opened only for the current
 * version (task 14 leftover 5: "Панель одобренного сценария не
 * разрастается полным текстом каждой версии: версии сворачиваются"). A
 * project edited many times over its life can carry a long version
 * history; dumping every one's full text into this *read-only echo* (the
 * live, editable stage-1 panel -- buildScriptVersionItem, unchanged --
 * stays fully expanded, since an operator working there is actively
 * comparing text) used to make this summary grow without bound. `<summary>`
 * carries exactly the same meta row buildScriptVersionItem shows (badge,
 * "Текущая", reason) so collapsing costs nothing but the body text; native
 * `<details>` needs no extra script for keyboard/toggle behavior.
 */
function buildCollapsedScriptVersionItem(version, projectId) {
  const li = document.createElement("li");
  li.className = "script-version script-version-collapsed";
  if (version.versionId) {
    li.dataset.versionId = version.versionId;
  }
  li.dataset.selected = String(version.active);

  const overrideKey = version.versionId ? versionOverrideKey(projectId, version.versionId) : null;

  const details = document.createElement("details");
  details.className = "script-version-details";
  // "«Текущая» стоит там, где её задают данные" -- driven by `version.
  // active`, the same flag the badge below reads, UNLESS the operator has
  // explicitly toggled *this* version open/closed since the panel last
  // mounted fresh (repair 1, condition 2) -- an override always wins, in
  // either direction, over what the data alone would default to. Repair 2,
  // condition 13: keyed by `overrideKey` (project + version id), never the
  // bare version id alone -- see this map's own file banner for why.
  const initialOpen = overrideKey && versionDisclosureOverrides.has(overrideKey)
    ? versionDisclosureOverrides.get(overrideKey)
    : version.active;
  // Repair 2, condition 13 (craft review finding 1): real Chrome fires a
  // native "toggle" event even for *this* programmatic assignment below,
  // whenever it actually flips `open` from its own just-constructed default
  // of `false` -- never only for a genuine click/keyboard interaction, and
  // never for assigning `false` (a no-op there in every browser, since the
  // state never actually changes). A naive "ignore whichever toggle event
  // arrives first" flag cannot tell that spurious echo apart from a
  // genuine first click, though: a real interaction is exactly as likely to
  // be the first event this fresh listener ever sees (confirmed against
  // this file's own pre-existing repaint test, which drives a real user
  // *close* of a version that started open via a manually dispatched
  // "toggle" with no assignment-echo involved at all -- a first-event flag
  // would have silently eaten that closing click). Comparing against the
  // value *this assignment itself just set* is what actually distinguishes
  // them: the spurious echo fires before anything else touches `open`, so
  // `details.open` still equals `assignedOpen` when it arrives; a genuine
  // click always flips it away from that value first. Only eligible for the
  // *one* event where that could still be true (`maybeSpuriousEcho`,
  // consumed unconditionally the first time the handler runs, from either
  // cause) -- a later genuine toggle back to the same value it started at
  // (close, then reopen) is a second event and is always recorded.
  const assignedOpen = initialOpen;
  let maybeSpuriousEcho = initialOpen === true;
  details.open = initialOpen;
  if (overrideKey) {
    details.addEventListener("toggle", () => {
      if (maybeSpuriousEcho && details.open === assignedOpen) {
        maybeSpuriousEcho = false;
        return;
      }
      maybeSpuriousEcho = false;
      versionDisclosureOverrides.set(overrideKey, details.open);
    });
  }

  const summary = document.createElement("summary");
  summary.className = "script-version-summary";
  // Repair, ticket 14 (review blocker G04): a native `<summary>` is
  // genuinely keyboard-focusable (an operator tabbed to a version's own
  // disclosure toggle, or just opened/closed it and kept focus there), but
  // carried no axis of its own at all -- neither a scene id (this panel is
  // the *approved script*, above any per-scene block; ui/state.js's
  // SCENE_FOCUS_HOOKS is scene-keyed only) nor `card-control`'s
  // target-id/action pair (this is a read-only disclosure toggle, never a
  // decision control, and calls no submitAction). A real, unrelated repaint
  // landing while this exact row held focus -- the same poll-driven
  // scenario the rest of this ticket's review named -- had nothing in
  // ui/shell.js able to find it again, dropping focus to <body>/the stage
  // heading fallback exactly like the other five control types did.
  // `data-version-id` is the one real, stable identity a version already
  // has (this same string already keys `versionDisclosureOverrides` above,
  // and `li.dataset.versionId` on this row's own parent) -- ui/shell.js's
  // new captureVersionSummaryFocus/restoreVersionSummaryFocus read this
  // exact attribute, deliberately keyed by version id and never by list
  // position, so restoring focus after a repaint that reordered or added
  // versions still lands on the *same* version's own row, not merely
  // "whichever summary is now in the same spot".
  summary.dataset.hook = "script-version-summary";
  if (version.versionId) {
    summary.dataset.versionId = version.versionId;
  }
  const badge = document.createElement("span");
  badge.className = "media-version-badge";
  badge.textContent = `v${version.ordinal}`;
  summary.append(badge);
  if (version.active) {
    const current = document.createElement("span");
    current.className = "media-current-badge";
    current.textContent = "Текущая";
    summary.append(current);
  }
  if (version.reason) {
    const reason = document.createElement("span");
    reason.className = "script-version-reason";
    reason.textContent = version.reason;
    summary.append(reason);
  }
  details.append(summary);

  const text = document.createElement("p");
  text.className = "script-version-text";
  text.textContent = version.text;
  details.append(text);

  li.append(details);
  return li;
}

function buildCollapsedScriptVersionsList(versions, projectId) {
  const list = document.createElement("ol");
  list.className = "script-version-list script-version-list-collapsed";
  for (const version of versions) {
    list.append(buildCollapsedScriptVersionItem(version, projectId));
  }
  return list;
}

/**
 * Read-only echo of the approved script, shown above the per-scene blocks
 * from `image_plan` onward (ticket 06 condition 2/G01/R26/spec §9: "На
 * image_plan без сцен главная зона показывает одобренный сценарий (только
 * чтение, с версиями)... Завершённая стадия не исчезает"). No approve/
 * revise controls here -- those only exist while `approve-scenario`/
 * `revise-scenario` are actually in `view_stage.allowed_actions`, i.e.
 * stage 1 alone (`decisions.py` never re-adds them once scenes exist) --
 * and, since ticket 16, a *reopened* stage 1 with scenes already, which
 * `buildReopenedScriptPanel` below owns instead of this function (poправка
 * "финальное ревью таска 15": "на стадии scenario со сценами... одобрение и
 * доработка видны, пометки «Одобрен» нет" -- the two states never share one
 * function, since one shows a static badge and the other live controls).
 */
// Shared by `buildApprovedScriptSummary` and `buildReopenedScriptPanel`
// below (ticket 17 condition 1: the two had verbatim-duplicated this same
// prune call plus panel/heading assembly). Repair 1, condition 2: pruning
// is scoped to *this* rebuild's own version ids only -- a version dropped
// from history (never expected in practice; the ledger is append-only) has
// no override left to prune from under it, and a still-present one is
// untouched regardless of order. Repair 2, condition 13: also scoped to
// *this* project alone (`projectId`) -- a sibling project's own overrides,
// sharing this exact same module-level map, are never touched by this call.
// Returns the live `heading`/`panel` elements (heading already appended)
// so each caller can still add its own badge/hook/trailing controls --
// mutating an already-inserted element is exactly as valid as mutating it
// first, so the two callers' resulting DOM is unchanged by this split.
function buildScriptSummaryPanelBase(script, projectId) {
  pruneVersionDisclosureOverrides(projectId, script.versions.map((version) => version.versionId).filter(Boolean));
  const panel = document.createElement("div");
  panel.className = "scenario-script scenario-script-approved";
  const heading = document.createElement("h2");
  heading.textContent = "Сценарий";
  panel.append(heading, buildCollapsedScriptVersionsList(script.versions, projectId));
  return { panel, heading };
}

function buildApprovedScriptSummary(script, projectId) {
  const { panel, heading } = buildScriptSummaryPanelBase(script, projectId);
  const badge = document.createElement("span");
  badge.className = "media-current-badge";
  badge.textContent = "Одобрен";
  heading.append(" ", badge);
  return panel;
}

/**
 * Ticket 16 ("финальное ревью таска 15" poправка): the scenario stage,
 * reopened, with scenes already split out by an earlier approval cycle --
 * `scenarioModel`'s own `reopened` flag (`current_stage === "scenario"`
 * while `scenes` still exists). Same version-history echo as
 * `buildApprovedScriptSummary` above (still useful context: "what was this
 * scenario before the return"), but never the "Одобрен" badge -- it is not
 * approved right now -- and *with* the real approve/revise controls
 * (`buildApproveReviseControls`, shared with stage 1's own
 * `renderScriptPanel`) instead: "На стадии scenario со сценами... одобрение
 * и доработка видны, пометки «Одобрен» нет." Per-scene block editing itself
 * needs no separate branch here at all -- `buildSceneBlock`'s own `canEdit`
 * already reads straight off `view_stage.allowed_actions`, which server-side
 * task 15 now includes `edit` in at the reopened `scenario` stage exactly
 * the same way it already does at `image_plan`.
 */
function buildReopenedScriptPanel(script, model) {
  const { panel, heading } = buildScriptSummaryPanelBase(script, model.projectId);
  panel.classList.add("scenario-script-reopened");
  heading.dataset.hook = "scenario-heading";
  panel.append(
    buildApproveReviseControls({
      revision: model.revision,
      canApprove: model.canApprove,
      canRevise: model.canRevise,
      projectId: model.projectId,
    }),
  );
  return panel;
}

/** The scenario is approved, but chat has not split it into scenes yet
 * (`active_project.scenes` is an empty array) -- ticket 06 condition 2's
 * "пустое состояние «Сцены ещё не созданы» со следующим шагом «разбейте
 * сценарий в чате»". Reuses the same global `.empty-state`/`.content-slot`
 * look ui/shell.js's own empty states already use (styles/layout.css),
 * rather than a second, scenario-only definition of the same look. */
function buildNoScenesState() {
  const wrap = document.createElement("div");
  wrap.className = "content-slot";
  const empty = document.createElement("div");
  empty.className = "empty-state";
  const heading = document.createElement("h2");
  heading.textContent = "Сцены ещё не созданы";
  const text = document.createElement("p");
  text.textContent = "Разбейте сценарий на сцены в чате, чтобы продолжить работу.";
  empty.append(heading, text);
  wrap.append(empty);
  return wrap;
}

/**
 * "Все сцены" -- clears the scene selection (ticket 06 condition 7),
 * returning the inspector to whole-project materials. Disabled while
 * nothing is selected: there is then nothing to clear. `requestSceneSelection`
 * with a falsy id dispatches the same `studio:scene-selected` event with an
 * empty `sceneId`, which app.js's listener (repaired alongside this) now
 * actually forwards to `store.selectScene(null, ...)` instead of silently
 * dropping it.
 */
function buildDeselectSceneButton(selectedSceneId) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "scenario-deselect-button";
  button.textContent = "Все сцены";
  button.disabled = !selectedSceneId;
  button.addEventListener("click", () => requestSceneSelection(null, "scenario"));
  return button;
}

/**
 * Desktop's two-column grid (styles/scenario.css, `@media (min-width:
 * 901px)`) places the timeline visually to the LEFT of the scene blocks via
 * `grid-area`, independent of DOM order -- but keyboard *tab* order always
 * follows DOM order, regardless of visual grid position (ticket 06
 * condition 9: "порядок DOM совпадает с визуальным"). Mobile's plain flex
 * column has no such visual/DOM split (whichever is appended first *is*
 * both the top item and the first tab stop), and spec §10 requires scenario
 * before timeline there, so only the desktop order needs to flip.
 *
 * `desktopScenarioQuery` (below) is the one JS-side `901px`; both this
 * function and `reorderScenarioLayout` read the same `MediaQueryList`
 * instead of each creating their own, so there is exactly one JS literal
 * to keep in step with styles/scenario.css's own `901px` media query --
 * not two that could drift apart from each other on top of that.
 *
 * Created lazily, on first actual DOM render, rather than at module
 * top-level: this module is imported directly by
 * tests/ui/scenario-timeline.test.mjs for its pure functions (no DOM/
 * `window` exists under `node --test`, see ui/timeline.js's file banner),
 * so a bare `window.matchMedia(...)` sitting at the top of the file would
 * throw the instant the module loads, in every test that imports it --
 * not only the ones that ever reach a DOM renderer.
 */
let desktopScenarioQuery = null;

function getDesktopScenarioQuery() {
  if (!desktopScenarioQuery) {
    desktopScenarioQuery = window.matchMedia("(min-width: 901px)");
    desktopScenarioQuery.addEventListener("change", reorderScenarioLayout);
  }
  return desktopScenarioQuery;
}

function isDesktopScenarioLayout() {
  return getDesktopScenarioQuery().matches;
}

/**
 * Re-order `.scenario-layout`'s two children (the timeline nav, the
 * scenario panel) to match whichever layout is now actually active --
 * without waiting for a snapshot-driven repaint (second repair,
 * 2026-09-17, ticket 06 condition 6: "порядок таймлайна и сценария
 * следует раскладке и при ресайзе"). `renderScenesLayout` below only ever
 * decides this DOM order once, at the moment it runs; crossing the 901px
 * breakpoint afterwards -- resizing a window, rotating a device -- with no
 * data change at all used to leave stage 1's *previous* render-time order
 * stuck until the next real repaint happened to run, which on a quiet
 * project could be never. Queries fresh every time rather than closing
 * over the node `renderScenesLayout` built, since this module rebuilds
 * that node from scratch on every repaint (unlike ui/rail.js's own
 * patch-in-place list) -- a listener closed over one render's node would
 * be reordering a detached element after the very next repaint.
 * `insertBefore` relocates the existing nodes rather than rebuilding them,
 * so anything focused inside either one (an open edit form, mid-edit)
 * survives the reorder untouched.
 */
/**
 * Task 14 leftover 3 ("Переставка узлов при переходе через 901 px не
 * роняет фокус"). Live-browser testing found focus landing on `<body>`
 * after crossing the breakpoint with a scene block header focused --
 * `insertBefore` relocates an attached node without detaching it from the
 * document at any point, but Chromium still blurs whatever it (or an
 * ancestor) contains the instant that reparenting also lands inside a
 * grid/flex container whose own CSS layout just changed in the same tick
 * (the `@media (max-width: 900px)` rule in styles/scenario.css/layout.css
 * changing `.scenario-layout`'s own `grid-template-columns`), regardless
 * of same-document, same-parent status. The fix is the same
 * capture-reorder-restore bracket `ui/shell.js`'s own `captureSceneFocus`/
 * `restoreSceneFocus` already uses for every *other* repaint in this
 * codebase -- explicit, not assumed for free from `insertBefore` alone.
 */
function reorderScenarioLayout() {
  const layout = document.querySelector('[data-hook="scenario-layout"]');
  if (!layout) {
    return; // stage 1, or nothing painted yet
  }
  const timeline = layout.querySelector('[data-hook="timeline-panel"]');
  const panel = layout.querySelector(".scenario-panel");
  if (!timeline || !panel) {
    return; // a photo project: no timeline exists to reorder around
  }
  const active = document.activeElement;
  const focusWasInLayout = active instanceof Element && layout.contains(active);
  if (isDesktopScenarioLayout()) {
    layout.insertBefore(timeline, panel);
  } else {
    layout.insertBefore(panel, timeline);
  }
  // `insertBefore` above already keeps `active` itself alive and attached
  // (it relocates the container, never removes+recreates the focused node
  // itself) -- refocusing it directly, rather than re-deriving a selector
  // for it, is exactly right here and cannot land on the wrong element the
  // way a hook-based re-find elsewhere in this codebase has to guard
  // against.
  if (focusWasInLayout && typeof active.focus === "function") {
    active.focus();
  }
}

function renderScenesLayout(root, model, snapshot, selectedSceneId) {
  const layout = document.createElement("div");
  layout.className = "scenario-layout";
  layout.dataset.hook = "scenario-layout";

  const panel = document.createElement("section");
  panel.className = "scenario-panel";
  panel.setAttribute("aria-label", "Сценарий по сценам");

  if (model.script) {
    if (model.reopened) {
      // Ticket 16: scenario reopened, scenes already exist -- live
      // approve/revise controls, never the static "Одобрен" badge, and
      // never the "Вернуться к сценарию" control either (the server itself
      // never lists `reopen-scenario` on the `scenario` stage -- there is
      // nothing to reopen from here).
      panel.append(buildReopenedScriptPanel(model.script, model));
    } else {
      panel.append(buildApprovedScriptSummary(model.script, model.projectId));
      // Ticket 16 condition 1: only on a genuinely approved, later stage --
      // `buildReopenControl` itself also re-checks `reopen-scenario ∈
      // allowed_actions` and returns `null` otherwise (e.g. while blocked),
      // so this is not the only gate, just the one that also skips the call
      // entirely at the reopened stage above.
      const reopenControl = buildReopenControl({
        viewStage: model.viewStage,
        actions: model.actions,
        revision: model.revision,
        projectId: model.projectId,
      });
      if (reopenControl) {
        panel.append(reopenControl);
      }
    }
  }

  if (model.scenes.length === 0) {
    panel.append(buildNoScenesState());
  } else {
    const header = document.createElement("div");
    header.className = "scenario-panel-header";
    header.append(buildDeselectSceneButton(selectedSceneId));
    const list = document.createElement("ol");
    list.className = "scenario-block-list";
    for (const entry of model.scenes) {
      list.append(buildSceneBlock(entry, model.canEdit, model.revision, model.projectId, model.actions));
    }
    panel.append(header, list);
  }

  if (isDesktopScenarioLayout()) {
    renderTimeline(layout, snapshot, selectedSceneId);
    layout.append(panel);
  } else {
    layout.append(panel);
    renderTimeline(layout, snapshot, selectedSceneId);
  }
  root.append(layout);
}

/**
 * Render the scenario surface into `root` (an already-mounted container --
 * ui/shell.js's `buildScenarioSlot`). Returns `true` when it painted the
 * script/scenes content, `false` for "empty" -- the caller falls back to
 * the pre-existing "Сценарий ещё не создан" state in that case.
 *
 * Auto-scroll to a newly selected scene is *not* triggered from here --
 * `root` is not necessarily attached to the live document yet when this
 * runs (ui/shell.js's `buildScenarioSlot` builds it detached, then appends
 * it), and `scrollIntoView()` on a detached node is a silent no-op (ticket
 * 06 condition 3). `ui/shell.js`'s `renderShell` calls `ui/timeline.js`'s
 * `scrollSceneIntoView` itself, right after the real insertion.
 */
export function renderScenario(root, snapshot, selectedSceneId) {
  root.textContent = "";
  root.className = "scenario";
  root.dataset.slot = "scenario";
  const model = scenarioModel(snapshot, selectedSceneId);
  if (model.kind === "scenes") {
    // Second repair, 2026-09-17 (ticket 06 condition 1): scoped to *this*
    // project's own drafts only -- a blanket `editDrafts.clear()` here
    // would have wiped a different, currently-unopened project's pending
    // draft merely because the operator happened to look at this one.
    pruneEditDrafts(model.projectId, model.scenes.map((entry) => entry.sceneId).filter(Boolean));
    renderScenesLayout(root, model, snapshot, selectedSceneId);
  } else if (model.kind === "script") {
    // No scenes exist yet at this project -- `buildEditControl` was never
    // reachable for it, so it has no drafts of its own to preserve; this
    // still only touches *this* project's entries (empty target list),
    // never another project's.
    pruneEditDrafts(model.projectId, []);
    renderScriptPanel(root, model);
  }
  return model.kind !== "empty";
}

/**
 * Render the selected scene's own script-block version history into
 * `root` (the `[data-hook="inspector"]` zone, called from ui/shell.js's
 * `paintInspector`). Second repair, 2026-09-17, ticket 06 condition 12:
 * "версии блока выбранной сцены видны в инспекторе" -- `buildSceneEntry`
 * used to compute a `blockVersionCount` for exactly this purpose but
 * nothing ever rendered it anywhere (removed as dead weight once this
 * function took over, reading the scene's own `script_block` directly
 * instead); spec §2's own listing of what the inspector shows leads with
 * "версии", before references or decisions.
 *
 * Reuses `buildScriptVersions`/`buildScriptVersionsList` unchanged -- a
 * scene's `script_block` carries exactly the same shape
 * (`{active_version_id, versions:[{version_id,text,reason}]}`) as the
 * project's own top-level `script`, so this is the very same version list
 * the stage-1 script panel already renders (`renderScriptPanel`), not a
 * second definition of the same thing.
 *
 * Returns `true` only when it painted something -- no scene selected, an
 * unknown scene id, or a scene with no block versions at all (never
 * expected in practice: `set_scenes` always creates one) all return
 * `false` -- so the caller falls back to its own "nothing yet" copy
 * exactly like ui/media.js's renderReferencePanel/renderMediaGallery.
 */
export function renderSceneBlockVersions(root, snapshot, selectedSceneId) {
  if (!selectedSceneId) {
    return false;
  }
  const scenes = snapshot?.active_project?.scenes;
  const scene = Array.isArray(scenes)
    ? scenes.find((candidate) => candidate?.scene_id === selectedSceneId)
    : undefined;
  const versions = buildScriptVersions(scene?.script_block);
  if (versions.length === 0) {
    return false;
  }
  const section = document.createElement("div");
  section.dataset.hook = "scene-block-versions";
  const heading = document.createElement("h3");
  heading.textContent = "Версии сцены";
  section.append(heading, buildScriptVersionsList(versions));
  root.append(section);
  return true;
}
