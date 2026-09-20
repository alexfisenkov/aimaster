// Renders the top bar, the main scenario/inspector slots and the
// empty/loading/blocked/error shells. Every branch is keyed on
// `state.status`; future-stage content never appears here because the
// scenario/inspector bodies are placeholders owned by tasks 06-08.

import {
  displayProjectTitle,
  resolveModeLabel,
  resolveStatusLabel,
  resolveTypeLabel,
  SCENE_FOCUS_HOOKS,
  STAGE_LABELS,
} from "./state.js";
import { createPendingFocusRegistry } from "./shell-runtime.js";
import { renderMediaGallery, renderReferencePanel } from "./media.js";
import { renderScenario, renderSceneBlockVersions, scenarioModel } from "./scenario.js";
import { scrollSceneIntoView } from "./timeline.js";
import { renderNeedAnswer } from "./need-answer.js";
// Task 08 repair 1: card/stage decisions decorate the DOM ui/media.js's/
// ui/scenario.js's own renderers already built (data-hook query, not an
// import into either of those two modules -- see ui/card-decorate.js's own
// file banner for why). Split into focused modules (repair condition 11):
// ui/card-decorate.js owns card decoration, ui/card-reorder.js owns scene
// reorder, ui/decision-history.js owns the inspector history, and
// ui/stage-review.js composes the assembly/stage-approval bar.
import { decoratePromptCards, decorateResultCards } from "./card-decorate.js";
import { decorateSceneReorder } from "./card-reorder.js";
import { renderDecisionHistory } from "./decision-history.js";
import {
  getRegisteredStep,
  registerStep,
  renderRegisteredStep,
  resolveViewedStage,
  resolveStepHint,
  stepPosition,
  STEP_HINTS,
} from "./step-router.js";
import { renderHistoryPanel } from "./history-panel.js";
import { renderScenarioStep } from "./step-scenario.js";
import { renderPlanStep } from "./step-plan.js";
import { renderAudioStep } from "./step-audio.js";
import { renderAssemblyStep } from "./step-assembly.js";
import { renderImagesStep } from "./step-images.js";
import { renderVideoStep } from "./step-video.js";
import { requestAgentPrompt } from "./chat-prompt-dialog.js";

// Tone only — the label TEXT for every status comes from the one shared
// STATUS_LABELS dictionary in state.js (also used by the rail), so the two
// surfaces can never disagree on wording. Keyed on the same project.status
// vocabulary as STATUS_LABELS -- never on view_stage.gate_status, which is
// a different field surfaced elsewhere, not as a second, competing status pill here.
const STATUS_TONES = Object.freeze({
  active: "neutral",
  review: "attention",
  done: "ready",
});

// Single source for this exact phrase: both the blocked notice heading and
// the live-region announcement below quote it, so the two surfaces can
// never drift apart. "blocked" is a normal, expected workflow state
// (waiting on an answer), not a failure -- the phrase says so neutrally.
const NEEDS_ANSWER_TEXT = "Нужен ответ";

function buildStageStepsNav(stageTabs, viewedStage) {
  const nav = document.createElement("nav");
  nav.className = "stage-steps";
  nav.setAttribute("aria-label", "Стадии проекта");
  const ol = document.createElement("ol");
  for (const tab of stageTabs) {
    const li = document.createElement("li");
    const step = document.createElement("button");
    step.type = "button";
    step.className = "stage-step";
    step.dataset.hook = "stage-tab";
    step.dataset.stage = tab.stage;
    step.dataset.current = String(tab.current);
    step.dataset.completed = String(tab.completed);
    step.dataset.viewed = String(tab.stage === viewedStage);
    if (tab.stage === viewedStage) {
      step.setAttribute("aria-current", "step");
    }
    if (tab.completed || tab.current) {
      const mark = document.createElement("span");
      mark.className = "stage-step-mark";
      mark.setAttribute("aria-hidden", "true");
      mark.textContent = tab.completed ? "✓" : "●";
      step.append(mark);
    }
    const label = document.createElement("span");
    label.textContent = tab.label;
    step.append(label);
    step.addEventListener("click", () => {
      document.dispatchEvent(
        new CustomEvent("studio:stage-viewed", {
          bubbles: true,
          detail: { stage: tab.stage },
        }),
      );
    });
    li.append(step);
    ol.append(li);
  }
  nav.append(ol);
  return nav;
}

function buildEmptyState(headingText, bodyText, action) {
  const wrap = document.createElement("div");
  wrap.className = "content-slot";
  const empty = document.createElement("div");
  empty.className = "empty-state";
  const heading = document.createElement("h2");
  heading.textContent = headingText;
  const text = document.createElement("p");
  text.textContent = bodyText;
  empty.append(heading, text);
  if (action) {
    empty.append(action);
  }
  wrap.append(empty);
  return wrap;
}

function buildLoadingSlot() {
  const wrap = document.createElement("div");
  wrap.className = "content-slot";
  const skeleton = document.createElement("div");
  skeleton.className = "stage-skeleton";
  skeleton.setAttribute("aria-hidden", "true");
  for (let index = 0; index < 4; index += 1) {
    const bar = document.createElement("div");
    bar.className = "skeleton";
    skeleton.append(bar);
  }
  const srText = document.createElement("p");
  srText.className = "visually-hidden";
  srText.textContent = "Загрузка проекта";
  wrap.append(skeleton, srText);
  return wrap;
}

function buildRetryButton() {
  const retry = document.createElement("button");
  retry.type = "button";
  retry.className = "retry-button";
  retry.textContent = "Повторить";
  retry.addEventListener("click", () => {
    document.dispatchEvent(new CustomEvent("studio:retry-snapshot", { bubbles: true }));
  });
  return retry;
}

/**
 * The main scenario surface (task 06): the whole script at stage 1, or --
 * from `image_plan` onward -- the per-scene blocks plus, for a video
 * project, ui/timeline.js's vertical range navigator alongside them.
 * `ui/scenario.js`'s `renderScenario` decides which of the two from the
 * snapshot alone (never from `project.type` or cached client state) and
 * paints nothing at all for a project with neither a started script nor
 * any scenes yet -- the pre-existing "Сценарий ещё не создан" empty state
 * below is what a truly blank project still shows.
 */
function buildScenarioSlot(snapshot, selectedSceneId) {
  const wrap = document.createElement("div");
  if (renderScenario(wrap, snapshot, selectedSceneId)) {
    // Task 08: scene reorder (image_plan only, allowlist-gated) decorates
    // the just-built scenario blocks in place -- see
    // ui/card-reorder.js's decorateSceneReorder.
    decorateSceneReorder(wrap, snapshot);
    return wrap;
  }
  const empty = buildEmptyState(
    "Сценарий ещё не создан",
    "Опишите замысел в чате, чтобы собрать первый вариант сценария.",
  );
  empty.dataset.slot = "scenario";
  return empty;
}

export function topbarMetaLabels(project) {
  const labels = ["AI Мастерская"];
  const typeLabel = resolveTypeLabel(project?.type);
  const modeLabel = resolveModeLabel(project?.mode);
  if (typeLabel) {
    labels.push(typeLabel);
  }
  if (modeLabel) {
    labels.push(modeLabel);
  }
  return labels;
}

function paintTopbar(container, state) {
  container.textContent = "";
  const project = state?.snapshot?.active_project;
  if (!project) {
    return;
  }

  const identity = document.createElement("div");
  identity.className = "topbar-identity";
  const title = document.createElement("h1");
  title.className = "topbar-title";
  title.textContent = displayProjectTitle(project);
  const meta = document.createElement("div");
  meta.className = "topbar-meta";
  // Type and mode are allowlist-only: an unrecognized raw token renders
  // nothing rather than leaking the raw value or a generic placeholder.
  const metaLabels = topbarMetaLabels(project);
  metaLabels.forEach((label, index) => {
    if (index > 0) {
      const separator = document.createElement("span");
      separator.setAttribute("aria-hidden", "true");
      separator.textContent = " · ";
      meta.append(separator);
    }
    const typeText = document.createElement("span");
    typeText.textContent = label;
    meta.append(typeText);
  });
  identity.append(title, meta);

  // Single source of truth for the overall project status: project.status,
  // the exact same field and dictionary the rail uses (spec §2's "общий
  // статус"). view_stage.gate_status is a different, stage-level field --
  // it never drives this pill; a "blocked" gate is instead communicated by
  // the stage area staying on the current stage plus the neutral "Нужен
  // ответ" notice, not by a second status label here.
  const projectStatus = project.status;
  const hasPendingQuestions = Array.isArray(state?.snapshot?.questions)
    && state.snapshot.questions.length > 0;
  const statusLabel = hasPendingQuestions ? NEEDS_ANSWER_TEXT : resolveStatusLabel(projectStatus);
  const controls = document.createElement("div");
  controls.className = "topbar-controls";
  if (statusLabel) {
    const pill = document.createElement("span");
    pill.className = "status-pill";
    pill.dataset.tone = hasPendingQuestions ? "attention" : (STATUS_TONES[projectStatus] || "neutral");
    pill.textContent = statusLabel;
    controls.append(pill);
  }
  const historyToggle = document.createElement("button");
  historyToggle.type = "button";
  historyToggle.className = "history-toggle";
  historyToggle.dataset.hook = "history-toggle";
  historyToggle.setAttribute("aria-expanded", String(Boolean(state.historyOpen)));
  historyToggle.textContent = state.historyOpen ? "Скрыть историю" : "История решений";
  historyToggle.addEventListener("click", () => {
    document.dispatchEvent(new CustomEvent("studio:history-toggle", { bubbles: true }));
  });
  const agentPrompt = document.createElement("button");
  agentPrompt.type = "button";
  agentPrompt.className = "agent-prompt-button agent-prompt-button-primary";
  agentPrompt.textContent = "Запрос агенту";
  agentPrompt.addEventListener("click", () => {
    const stage = state?.viewedStage || state?.snapshot?.view_stage?.current_stage || "текущий шаг";
    requestAgentPrompt({
      title: "Продолжить проект в чате",
      prompt: `Продолжи проект «${project.title || project.id}» (ID: ${project.id}). Открой его текущее состояние и помоги мне с этапом «${STAGE_LABELS[stage] || stage}». Сначала коротко скажи, что уже готово и какое одно действие сейчас логичнее всего. Ничего внешнего и платного не запускай без моего выбора маршрута и отдельного разрешения.`,
    }, agentPrompt);
  });
  controls.append(agentPrompt, historyToggle);
  container.append(identity, controls);
}

function buildStepSummary(stage, projectType) {
  const descriptor = getRegisteredStep(stage);
  const position = stepPosition(stage, projectType);
  if (!descriptor || !position) {
    return null;
  }
  const summary = document.createElement("section");
  summary.className = "step-summary";
  summary.dataset.hook = "step-summary";
  const heading = document.createElement("h2");
  heading.textContent = `Шаг ${position.number} из ${position.total} — ${resolveStepHint(stage, projectType) || descriptor.hint}`;
  summary.append(heading);
  return summary;
}

function readOnlySnapshot(snapshot, readOnly) {
  if (!readOnly || !snapshot) {
    return snapshot;
  }
  return {
    ...snapshot,
    view_stage: {
      ...(snapshot.view_stage || {}),
      allowed_actions: [],
    },
  };
}

function mediaSnapshotForStage(snapshot, stage) {
  if (!snapshot?.active_project) {
    return snapshot;
  }
  const project = { ...snapshot.active_project };
  if (stage === "image_results") {
    delete project.video_results;
  } else if (stage === "motion") {
    delete project.image_results;
  }
  return { ...snapshot, active_project: project };
}

function renderLegacyStep(root, { state, stage, readOnly, scenarioOptions }) {
  const snapshot = readOnlySnapshot(state.snapshot, readOnly);
  const scenarioSnapshot = snapshot
    ? {
        ...snapshot,
        view_stage: {
          ...(snapshot.view_stage || {}),
          allowed_actions: Array.isArray(snapshot.view_stage?.allowed_actions)
            ? snapshot.view_stage.allowed_actions.filter((action) => action !== "reopen-scenario")
            : [],
        },
      }
    : snapshot;
  if (stage === "scenario") {
    root.append(buildScenarioSlot(scenarioSnapshot, state.selectedSceneId ?? null));
  } else if (stage === "image_plan") {
    root.append(buildScenarioSlot(scenarioSnapshot, state.selectedSceneId ?? null));
    const references = document.createElement("div");
    if (renderReferencePanel(references, snapshot, state.selectedSceneId ?? null)) {
      if (!readOnly) {
        decoratePromptCards(references, snapshot);
      }
      root.append(references);
    }
  } else if (stage === "image_results" || stage === "motion") {
    appendMediaGallery(root, state, {
      snapshot: mediaSnapshotForStage(snapshot, stage),
      decorate: !readOnly,
    });
  } else if (stage === "assembly") {
    // The shared stage-review renderer below owns both the assembly panel
    // and its approval controls, so it is never duplicated here.
  } else {
    root.append(
      buildEmptyState(
        STAGE_LABELS[stage] || "Шаг",
        "Материалы этого шага появятся здесь после обновления интерфейса.",
      ),
    );
  }

  if (stage === "scenario" || stage === "image_plan") {
    scrollToSelectedSceneIfNeeded(root, state, scenarioOptions);
    focusScenarioHeadingIfPending(root, state);
  }
}

function paintMain(main, state, scenarioOptions) {
  main.textContent = "";
  main.removeAttribute("aria-busy");

  if (!state || state.status === "loading") {
    main.setAttribute("aria-busy", "true");
    main.append(buildLoadingSlot());
    return;
  }

  if (state.status === "empty") {
    main.append(
      buildEmptyState(
        "Проектов пока нет",
        "Новый проект создаётся в чате: опишите замысел, и он появится здесь.",
      ),
    );
    return;
  }

  if (state.status === "choose") {
    main.append(
      buildEmptyState(
        "Выберите проект",
        "Откройте меню проектов и выберите проект для просмотра.",
      ),
    );
    return;
  }

  if (state.status === "error") {
    if (state.stageTabs.length > 0) {
      main.append(buildStageStepsNav(state.stageTabs, state.viewedStage));
    }
    main.append(
      buildEmptyState(
        "Не удалось загрузить проект",
        "Проверьте соединение и попробуйте ещё раз.",
        buildRetryButton(),
      ),
    );
    return;
  }

  if (state.status === "blocked") {
    // Completed stages stay visible (the tabs), and the current stage's
    // own slot is NOT removed -- the blocked notice is additional, not a
    // replacement, per spec §9. The current stage's gallery paints exactly
    // as it does in "ready" -- blocked means "waiting on an answer", not
    // "hide what's already unlocked". Task 08's own decision/stage-review
    // controls are gated purely on `allowed_actions` (see
    // ui/card-decorate.js/ui/stage-approval.js), which is already just
    // `["continue-in-chat"]` while blocked, so calling them here is
    // harmless -- they paint nothing extra.
    main.append(buildStageStepsNav(state.stageTabs, state.viewedStage));
    renderNeedAnswer(main, {
      project: state.snapshot?.active_project,
      questions: state.snapshot?.questions,
      blocked: true,
    });
    if (state.snapshot) {
      appendViewedStep(main, state, scenarioOptions);
    }
    return;
  }

  if (!state.snapshot) {
    main.append(buildEmptyState("Выберите проект", "Список проектов — слева."));
    return;
  }

  main.append(buildStageStepsNav(state.stageTabs, state.viewedStage));
  renderNeedAnswer(main, {
    project: state.snapshot?.active_project,
    questions: state.snapshot?.questions,
    blocked: state.snapshot?.view_stage?.gate_status === "blocked",
  });
  appendViewedStep(main, state, scenarioOptions);
}

function appendViewedStep(main, state, scenarioOptions) {
  const currentStage = state.snapshot?.view_stage?.current_stage;
  const viewedStage = resolveViewedStage(state.viewedStage, state.stageTabs, currentStage);
  if (!viewedStage) {
    return;
  }
  const summary = buildStepSummary(viewedStage, state.snapshot?.active_project?.type);
  if (summary) {
    main.append(summary);
  }
  const surface = document.createElement("div");
  surface.className = "step-surface";
  surface.dataset.hook = "step-surface";
  surface.dataset.stage = viewedStage;
  surface.dataset.readOnly = "true";
  renderRegisteredStep(viewedStage, surface, {
    state,
    stage: viewedStage,
    readOnly: true,
    scenarioOptions,
  });
  main.append(surface);
}

/**
 * Auto-scroll the newly selected scene's blocks into view -- called only
 * *after* `main.append(...)` has actually inserted the scenario slot into
 * the live document (repair 2026-09-17, ticket 06 condition 3: calling
 * this against a still-detached node, as ui/scenario.js's own
 * `renderScenesLayout` used to, makes every `scrollIntoView()` a silent
 * no-op). `scenarioOptions.selectionChanged` -- computed once in
 * `renderShell`, from the very same previous/next comparison that also
 * decides `shellZonesNeedRepaint`'s key -- gates this so an unrelated
 * repaint with the same selection (a snapshot poll, a filter click) never
 * re-triggers a scroll; `reducedMotion` flows straight into
 * `scrollSceneIntoView`, which drops the scroll entirely for whichever
 * pane didn't originate the selection when the visitor prefers it (spec
 * §10).
 */
function scrollToSelectedSceneIfNeeded(main, state, scenarioOptions) {
  const sceneId = state.selectedSceneId ?? null;
  if (sceneId && scenarioOptions?.selectionChanged) {
    scrollSceneIntoView(main, sceneId, scenarioOptions.origin, Boolean(scenarioOptions.reducedMotion));
  }
}

// Image/video result galleries (ui/media.js, task 07). Progressive
// disclosure is enforced inside renderMediaGallery itself -- it paints
// nothing and returns false while active_project carries neither
// image_results nor video_results (i.e. at the scenario stage), so no
// wrapper is appended and the stage-1 DOM stays exactly scenario-only.
// Shared by both the "ready" and "blocked" branches above so they can never
// drift apart on what the current stage's gallery shows.
function appendMediaGallery(main, state, { snapshot = state.snapshot, decorate = true } = {}) {
  const galleryContainer = document.createElement("div");
  if (renderMediaGallery(galleryContainer, snapshot, state.selectedSceneId ?? null)) {
    // Task 08: card-level decisions decorate the just-built result cards
    // in place, gated on whether each card's own collection is the
    // current stage's (see ui/card-decorate.js's decorateResultCards) --
    // a past-stage card gets no row at all.
    if (decorate) {
      decorateResultCards(galleryContainer, snapshot);
    }
    main.append(galleryContainer);
  }
}

// Task 08: assembly deliverable and the "Одобрить стадию" /
// "Вернуть на доработку" bar -- each independently gated on the current
// stage (see ui/stage-review.js's renderStageReview), appended after the
// gallery so review controls always follow the material they review.
for (const stage of Object.keys(STAGE_LABELS)) {
  registerStep(stage, {
    title: STAGE_LABELS[stage],
    hint: STEP_HINTS[stage],
    render: renderLegacyStep,
  });
}

// Task 35 replaces only the scenario registration. `renderLegacyStep` and
// the other registrations stay intact as the owner-gated rollback path.
registerStep("scenario", {
  title: STAGE_LABELS.scenario,
  hint: STEP_HINTS.scenario,
  render: renderScenarioStep,
});

registerStep("image_plan", {
  title: STAGE_LABELS.image_plan,
  hint: STEP_HINTS.image_plan,
  render: renderPlanStep,
});

registerStep("audio", {
  title: STAGE_LABELS.audio,
  hint: STEP_HINTS.audio,
  render: renderAudioStep,
});

registerStep("assembly", {
  title: STAGE_LABELS.assembly,
  hint: STEP_HINTS.assembly,
  render: renderAssemblyStep,
});

registerStep("image_results", {
  title: STAGE_LABELS.image_results, hint: STEP_HINTS.image_results, render: renderImagesStep,
});
registerStep("motion", {
  title: STAGE_LABELS.motion, hint: STEP_HINTS.motion, render: renderVideoStep,
});

function paintInspector(container, state) {
  container.textContent = "";
  if (!state || (state.status !== "ready" && state.status !== "blocked")) {
    return;
  }
  const heading = document.createElement("h2");
  heading.textContent = "Инспектор";
  // Repair condition 7: `focusCardFallbackHeading`'s own absolute-last-resort
  // fallback (nothing at all left in either zone for a just-applied
  // decision) needs a hook-addressable landmark inside the inspector too,
  // mirroring main's own `[data-hook="stage-actions"] h3` -- found by this
  // hook, never by tag alone (`renderSceneBlockVersions`/
  // `renderReferencePanel` below may paint their own headings too).
  heading.dataset.hook = "inspector-heading";
  container.append(heading);

  const selectedSceneId = state.selectedSceneId ?? null;
  // Second repair, 2026-09-17 (ticket 06 condition 12: "версии блока
  // выбранной сцены видны в инспекторе"). Spec §2 leads the inspector's
  // own contents with "версии" -- painted first, above the prompts/
  // references below, for exactly that reason. Nothing is painted at all
  // (and this call is a no-op) while no scene is selected.
  const paintedVersions = renderSceneBlockVersions(container, state.snapshot, selectedSceneId);
  // Versioned prompts and role-grouped references (ui/media.js, task 07).
  // Same progressive-disclosure rule as the gallery above: nothing is
  // painted, and the placeholder copy below takes over, until image_plan
  // actually unlocks image_prompts/references.
  const paintedReferences = renderReferencePanel(container, state.snapshot, selectedSceneId);
  // Task 08: prompt-card decisions (approve/reject-with-comment/edit)
  // decorate the reference panel's own image-prompt entries in place --
  // only at image_plan, only for image_prompts (see ui/card-decorate.js's
  // decoratePromptCards); harmless no-op when renderReferencePanel painted
  // no prompt entries at all.
  decoratePromptCards(container, state.snapshot);
  // Task 08 point 9: decision history -- the selected card's own
  // decisions[] plus every reached stage's own milestone decision.
  const paintedHistory = renderDecisionHistory(container, state.snapshot, selectedSceneId);
  if (paintedVersions || paintedReferences || paintedHistory) {
    return;
  }
  const text = document.createElement("p");
  // References only exist from image_plan onward (spec §2.1); naming them
  // while the scenario stage is current would announce future-stage
  // content that isn't there yet. At stage 1 the script's own versions are
  // already sitting in the *center* (ui/scenario.js's `renderScriptPanel`)
  // -- repair 2026-09-17, ticket 06 condition 8: this text must not also
  // promise them here, in the inspector, as if they were still pending.
  const currentStage = state.snapshot?.view_stage?.current_stage;
  text.textContent =
    currentStage && currentStage !== "scenario"
      ? "Версии, референсы и решения появятся здесь, когда будут доступны."
      : "Решения появятся здесь, когда будут доступны.";
  container.append(text);
}

function updateLiveRegion(state) {
  const region = document.querySelector('[data-hook="live-region"]');
  if (!region) {
    return;
  }
  if (state?.status === "blocked") {
    region.textContent = `${NEEDS_ANSWER_TEXT}. Продолжите в чате.`;
  } else if (state?.status === "error") {
    region.textContent = "Не удалось загрузить проект.";
  } else {
    region.textContent = "";
  }
}

/**
 * Whether the topbar/main/inspector zones need repainting, given the key
 * cached from the last paint. Every pixel those three zones ever show is a
 * pure function of `{status, snapshot, selectedSceneId}` alone -- never of
 * the rail's filter/query text -- so this is the exact seam that decides
 * whether a filter/query-only commit (a search keystroke, a filter click)
 * is allowed to reach them at all. `selectedSceneId` is store state task 06
 * will start setting (ui/media.js's cards already read it, defensively,
 * today); it belongs in this key for the same reason `snapshot` does -- a
 * commit that only flips it must still repaint the gallery/reference panel
 * so their `data-selected` marks don't go stale.
 * Exported and DOM-free so that seam is directly testable: `renderShell` is
 * the only caller that also touches real elements and the live region.
 */
export function shellZonesNeedRepaint(previousKey, state) {
  if (!previousKey) {
    return true;
  }
  return (
    previousKey.status !== state?.status ||
    previousKey.snapshot !== state?.snapshot ||
    // `?? null` on both sides: an older/hand-built key that predates this
    // field (no `selectedSceneId` property at all, i.e. `undefined`) must
    // compare equal to a state that likewise has none yet, not force a
    // spurious repaint every call.
    (previousKey.selectedSceneId ?? null) !== (state?.selectedSceneId ?? null) ||
    (previousKey.viewedStage ?? null) !== (state?.viewedStage ?? null) ||
    Boolean(previousKey.historyOpen) !== Boolean(state?.historyOpen)
  );
}

// Repair, 2026-09-17 (ticket 06 condition 10). This used to be its own,
// separately maintained two-entry list -- `ui/timeline.js` kept an
// identical-looking one for `scrollSceneIntoView`, and the two could (and,
// per live review, effectively already had) drift apart silently. Both
// now read `ui/state.js`'s one `SCENE_FOCUS_HOOKS`, which as of the second
// repair (2026-09-17, ticket 06 conditions 4/5) also covers the scene
// edit form's Save/Cancel buttons (not only its textarea/reason fields)
// and ui/media.js's inspector-only scene tag button -- so an edit form
// left open and focused, or a scene tag inside the inspector, both
// survive a repaint the same way the two selection buttons already did,
// without this list itself having to grow a third capture/restore pair
// of its own for every new scene-linked control.
const SCENE_FOCUS_HOOK_NAMES = SCENE_FOCUS_HOOKS.map((entry) => entry.hook);

// One-shot note for a focus `captureSceneFocus` itself can no longer see
// by the time it runs (second repair, 2026-09-17, ticket 06 condition 4).
// Live-browser testing found that saving a scene edit still stranded
// focus on `<body>` even with the Save/Cancel hooks and the header
// fallback both in place below -- because `submitAction` (ui/actions.js)
// sets `disabled = true` on the just-clicked Save button *synchronously*,
// before its own first `await`, and a browser blurs a disabled element to
// `<body>` immediately, not on the later repaint. By the time this
// module's `renderShell` runs -- after the network round trip settles --
// `document.activeElement` has already been `<body>` for as long as the
// request was in flight; there is nothing left in the DOM to capture.
//
// `ui/scenario.js`'s edit-form submit handler dispatches
// `studio:scene-focus-pending` with its own scene id *before* calling
// `submitAction`, i.e. before that blur can happen, so this has a real
// fallback once the DOM capture below comes back empty. A plain
// bubbling DOM event (the same cross-module pattern every other
// inter-module signal in this codebase already uses -- `studio:scene-
// selected`, `studio:refresh-snapshot`, `studio:open-viewer`, ...)
// rather than an export, since shell.js already imports *from*
// scenario.js (`renderScenario`/`renderSceneBlockVersions`) and an
// import the other way would be circular.
//
// The listener is attached lazily, on first use, not at module top
// level: tests/ui/focus-preservation.test.mjs imports this module
// directly for `shellZonesNeedRepaint`, and no DOM/`document` exists
// under `node --test` (see ui/timeline.js's file banner) -- a bare
// `document.addEventListener(...)` sitting at the top of this file would
// throw the instant the module loads, in every test that imports it.
//
// Task 14 repair 1, condition 4 ("приёмная сторона снятия метки фокуса в
// shell.js... закреплена тестом"). The note/clear/take bookkeeping itself
// used to be a bare module-level `pendingSceneFocus` variable, private to
// this file and therefore unreachable from any test -- extracted into
// ui/shell-runtime.js's `createPendingFocusRegistry` (DOM-free, exported
// there so tests/ui/scenario-remainders.test.mjs can drive the exact
// `clear` semantics production code uses without needing `document`/
// `CustomEvent` at all) and exported here as `sceneFocusRegistry` for the
// same reason. This listener is now just the DOM-only relay onto it.
export const sceneFocusRegistry = createPendingFocusRegistry();
let sceneFocusListenerAttached = false;

function ensureSceneFocusListener() {
  if (sceneFocusListenerAttached) {
    return;
  }
  sceneFocusListenerAttached = true;
  document.addEventListener("studio:scene-focus-pending", (event) => {
    const { hook, sceneId, clear } = event?.detail || {};
    if (clear) {
      // Task 14 leftover 1 ("После неудачного «Сохранить» метка...
      // снимается"): ui/scenario.js's own `clearPendingSceneFocus` fires
      // this after a save that will *not* be followed by a repaint --
      // left alone, the note would otherwise resurface on the next
      // unrelated repaint (a different scene's selection, task 14's own
      // background poll) and steal focus onto a scene's "Сохранить" that
      // was never the point of that repaint at all, with a stray Enter
      // then silently resubmitting its stale draft. `sceneFocusRegistry.
      // clear` only drops an exact match -- a *different*, newer note (a
      // second scene's edit form, concurrently in flight) is left alone,
      // never cancelled by a late-arriving clear signal for someone
      // else's submit.
      sceneFocusRegistry.clear({ hook, sceneId });
      return;
    }
    if (typeof hook === "string" && hook && typeof sceneId === "string" && sceneId) {
      sceneFocusRegistry.note({ hook, sceneId });
    }
  });
}

/** Consumed (cleared) on every read, successful or not, so a note can
 * never resurface on a later, unrelated repaint. */
function takePendingSceneFocus() {
  ensureSceneFocusListener();
  return sceneFocusRegistry.take();
}

// -----------------------------------------------------------------------
// Ticket 16 (G05): "фокус — на заголовке сценария" once a confirmed
// `reopen-scenario` has actually landed. ui/scenario-reopen.js's own
// confirm button dispatches `studio:scenario-focus-pending` (with the
// project id the click was for) right before asking app.js to refresh --
// the same "note before the repaint that will make the real target exist"
// relay `studio:scene-focus-pending`/`studio:card-focus-pending` above
// already use, for the same reason: the heading this note targets does not
// exist in the DOM at all until the refreshed snapshot actually repaints
// `main` with the now-reopened stage 1.
//
// A plain one-shot project id, not `createPendingFocusRegistry` (used by
// the scene axis above): there is nothing here to `clear()` on an
// unsuccessful attempt (a failed/unconfirmed reopen never dispatches this
// note in the first place -- see that module's own submit handler), so the
// scene axis's extra `clear(match)` semantics would be dead weight here.
// -----------------------------------------------------------------------

let pendingScenarioFocusProjectId = null;
let scenarioFocusListenerAttached = false;

function ensureScenarioFocusListener() {
  if (scenarioFocusListenerAttached) {
    return;
  }
  scenarioFocusListenerAttached = true;
  document.addEventListener("studio:scenario-focus-pending", (event) => {
    const { projectId } = event?.detail || {};
    if (typeof projectId === "string" && projectId) {
      pendingScenarioFocusProjectId = projectId;
    }
  });
}

/** Drained on every `paintMain` call, matched or not (same "always drain"
 * rule the other pending-focus notes in this file follow) -- a note whose
 * own project is no longer the one open (the operator switched away mid-
 * refresh) is discarded rather than left to steal focus into whatever
 * project is open by the time a later, unrelated repaint happens to find a
 * matching heading. */
function focusScenarioHeadingIfPending(main, state) {
  ensureScenarioFocusListener();
  const pendingProjectId = pendingScenarioFocusProjectId;
  pendingScenarioFocusProjectId = null;
  if (!pendingProjectId || !main) {
    return;
  }
  const activeProjectId = state?.snapshot?.active_project?.id;
  if (activeProjectId !== pendingProjectId) {
    return;
  }
  // `[data-hook="scenario-heading"]` is deliberately only present on stage
  // 1's own two editable headings (ui/scenario.js's `renderScriptPanel` and
  // `buildReopenedScriptPanel`) -- never on the read-only, already-approved
  // summary a *different*, unrelated repaint might otherwise have shown
  // while this refresh was still in flight, which is what keeps this from
  // ever focusing a stale, pre-reopen heading.
  const heading = main.querySelector('[data-hook="scenario-heading"]');
  if (!heading) {
    return;
  }
  if (typeof heading.tabIndex !== "number" || heading.tabIndex < 0) {
    heading.tabIndex = -1;
  }
  heading.focus();
}

/**
 * Capture, before `zone` is torn down, which scene (if any) currently held
 * keyboard focus and in which surface -- `zone` (`main` or, second repair
 * 2026-09-17 ticket 06 condition 5, `inspector`) is fully rebuilt on every
 * repaint (unlike ui/rail.js's own list, which only patches), so this has
 * to run *before* `paintMain`/`paintInspector` clears it, not inside
 * either of them, where `document.activeElement` would already be
 * `<body>`.
 *
 * Falls back to `takePendingSceneFocus()` when nothing is currently
 * focused inside `zone` at all -- see that function's own comment for why
 * `document.activeElement` alone is not always enough.
 */
export function captureSceneFocus(zone) {
  const active = document.activeElement;
  if (active instanceof HTMLElement && zone.contains(active)) {
    const hook = active.dataset.hook;
    const sceneId = active.dataset.sceneId;
    if (sceneId && SCENE_FOCUS_HOOK_NAMES.includes(hook)) {
      takePendingSceneFocus(); // still consumed -- never leaks into a later repaint
      // Condition 2: captured alongside the hook/id, not just "focus was
      // here" -- restoreSceneFocus below is what actually re-applies it,
      // once the freshly-painted control for this same hook/id exists.
      return { hook, sceneId, selection: captureTextSelection(active) };
    }
  }
  const relayed = takePendingSceneFocus();
  return relayed ? { ...relayed, selection: null } : null;
}

/** Whether `.focus()` on `el` would actually move focus there -- the same
 * check ui/viewer.js's own `isFocusable` makes, duplicated rather than
 * imported (this module never imports viewer.js, and the check is three
 * lines). Guards `restoreSceneFocus`'s fallback below: a hidden or
 * disabled element (a collapsed edit form's own Save/Cancel buttons,
 * ticket 06 condition 4) still matches the selector but cannot take
 * focus, and calling `.focus()` on it anyway is a silent no-op that would
 * strand focus on `<body>` exactly as if nothing had been found at all. */
function isFocusable(el) {
  return Boolean(el) && typeof el.focus === "function" && el.offsetParent !== null && !el.disabled;
}

// -----------------------------------------------------------------------
// Task 14 repair 1, condition 2: a repaint that preserves *which* control
// gets focus back must also preserve *where in it* the operator was --
// live-browser testing found the caret jumping to the end of a scene-edit
// textarea on every repaint even once the control itself was correctly
// refocused (review finding: "курсор в правке блока прыгнул в конец"),
// because assigning a fresh `.value` to a brand-new element and then
// calling `.focus()` on it does not, by itself, put the caret back where
// it was -- only an explicit `setSelectionRange` does. Layered on top of
// both capture/restore pairs below (scene-hook and card-control alike)
// rather than duplicated in each: any text-like control reachable through
// either mechanism gets this for free.
// -----------------------------------------------------------------------

/** `null` for anything that is not a text control with a real selection
 * (a button, a `<select>`, ui/state.js's own scene-tag spans, ...) --
 * `selectionStart`/`selectionEnd` are only ever meaningful on an `<input>`/
 * `<textarea>`, and some `<input>` *types* (checkbox, radio, ...) throw
 * rather than return a number for them, so this is a `typeof` probe, never
 * an element-type allowlist that would have to know every text-like input
 * type in advance. */
function captureTextSelection(el) {
  if (!el || typeof el.selectionStart !== "number" || typeof el.selectionEnd !== "number") {
    return null;
  }
  return {
    selectionStart: el.selectionStart,
    selectionEnd: el.selectionEnd,
    selectionDirection: typeof el.selectionDirection === "string" ? el.selectionDirection : "none",
  };
}

/** The other half of `captureTextSelection`: re-apply a captured selection
 * to the freshly-painted `el` this same hook/id resolved to, clamped to
 * its own (possibly different -- a draft that changed length, a genuinely
 * new value after a save) current value length rather than trusting the
 * old offsets blindly. A no-op for anything that isn't a text control, or
 * when nothing was ever captured (a button-triggered repaint, a first
 * paint with nothing focused yet). */
function applyTextSelection(el, selection) {
  if (!selection || !el || typeof el.setSelectionRange !== "function") {
    return;
  }
  const length = typeof el.value === "string" ? el.value.length : 0;
  const start = Math.min(Math.max(selection.selectionStart, 0), length);
  const end = Math.min(Math.max(selection.selectionEnd, 0), length);
  try {
    el.setSelectionRange(Math.min(start, end), Math.max(start, end), selection.selectionDirection || "none");
  } catch {
    // Some input types accept focus but still throw on setSelectionRange
    // (browsers vary) -- a best-effort cursor restore must never break the
    // real focus restore it rides along with.
  }
}

/**
 * The other half of `captureSceneFocus`: after `zone` has been fully
 * rebuilt, refocus the freshly-painted element for the same scene and the
 * same hook. Falls back to that scene's own block header
 * (`scenario-block-select`) when the exact captured element either no
 * longer exists or exists but is no longer focusable -- second repair,
 * 2026-09-17, ticket 06 condition 4: saving a scene edit collapses its
 * form (the textarea/reason/Save/Cancel that may have held focus all
 * disappear behind `hidden`), and without this fallback that left focus
 * stranded on `<body>` instead of anywhere on the page a keyboard user
 * could see. A rebuild that dropped the scene entirely (e.g. a `reorder`)
 * still finds nothing at all, same as ui/rail.js's own refocus miss.
 */
export function restoreSceneFocus(zone, captured) {
  if (!captured) {
    return;
  }
  const selector = `[data-hook="${captured.hook}"][data-scene-id="${CSS.escape(captured.sceneId)}"]`;
  let target = zone.querySelector(selector);
  if (!isFocusable(target)) {
    target = zone.querySelector(
      `[data-hook="scenario-block-select"][data-scene-id="${CSS.escape(captured.sceneId)}"]`,
    );
  }
  if (isFocusable(target)) {
    target.focus();
    // Condition 2: only meaningful when `target` is genuinely the same
    // exact hook (the block-header fallback is a plain button, and
    // applyTextSelection is already a no-op on anything without
    // `setSelectionRange` -- no extra guard needed here for that case).
    applyTextSelection(target, captured.selection);
  }
}

// -----------------------------------------------------------------------
// Card/stage-control focus preservation -- repair condition 8: "После
// решения с клавиатуры и после «Выше/Ниже» фокус возвращается на тот же
// контрол или на перемещённый элемент, а не на body." A card/stage/
// reorder control (ui/card-forms.js's `buildSimpleButton`/
// `buildCommentForm`/`buildGrantAction`, ui/card-reorder.js's
// `buildReorderButtons`) is a different identity shape from a scene block
// (`data-target-id`/`data-action`, not `data-scene-id`), so this is a
// second, parallel capture/restore pair -- same overall shape as
// captureSceneFocus/restoreSceneFocus above, distinct data. The two never
// collide: `data-hook="card-control"` is never one of SCENE_FOCUS_HOOK_
// NAMES's own values, so a given focused element matches at most one of
// the two mechanisms.
// -----------------------------------------------------------------------

let pendingCardFocus = null;
let cardFocusListenerAttached = false;

function ensureCardFocusListener() {
  if (cardFocusListenerAttached) {
    return;
  }
  cardFocusListenerAttached = true;
  // Same relay ui/scenario.js's own `studio:scene-focus-pending` provides
  // (see that mechanism's own banner above for why a synchronous-disable
  // click handler needs it): ui/card-forms.js's `noteCardFocusPending`
  // fires *before* `submitAction`/`postAction` disables the just-clicked
  // control, i.e. before the browser's own disabled-element blur to
  // `<body>` can happen.
  document.addEventListener("studio:card-focus-pending", (event) => {
    const { targetId, action } = event?.detail || {};
    if (typeof targetId === "string" && targetId && typeof action === "string" && action) {
      pendingCardFocus = { targetId, action };
    }
  });
}

/** Drains the one global pending-focus note -- called exactly once per
 * `renderShell`, never per zone (see `renderShell`'s own tail below for why
 * per-zone draining, at capture time, was the actual repair-condition-7
 * bug), so a stale note can never resurface on a later, unrelated repaint
 * either way -- whether or not this particular render ends up needing it. */
function takePendingCardFocus() {
  ensureCardFocusListener();
  const note = pendingCardFocus;
  pendingCardFocus = null;
  return note;
}

/** Whether `document.activeElement`, right now, is a card/stage/reorder
 * control -- by its own `data-target-id`/`data-action` pair, the same real
 * hooks ui/card-forms.js/ui/card-reorder.js/ui/stage-approval.js mark
 * every control with. Deliberately *not* scoped to `main` or `inspector`
 * individually: `document.activeElement` is one single, global value, so
 * checking it once (rather than once per zone, the old shape) can never
 * itself introduce a cross-zone ambiguity -- `renderShell`'s own tail below
 * is the one place that resolves which zone a note belongs to (`main` tried
 * first, `inspector` only when `main` had nothing real for it -- repair 2,
 * condition 15: `inspector`'s own bracket call is handed `null` once `main`
 * has already placed the note, so it can never steal it back even when a
 * matching target/action genuinely exists in both zones at once), uniformly
 * for both this and the pending-relay case. Usually `null` in practice: a
 * synchronous-disable click handler (ui/card-forms.js's own
 * `submitAction`) already blurred the real control to `<body>` before
 * `renderShell` ever runs (see `captureSceneFocus`'s own banner for the
 * identical reasoning) -- `takePendingCardFocus` above is what covers
 * that case instead. */
export function captureLiveCardControlFocus() {
  const active = document.activeElement;
  if (active instanceof HTMLElement && active.dataset.hook === "card-control") {
    const { targetId, action } = active.dataset;
    if (targetId && action) {
      // Condition 2, same as captureSceneFocus above: this mechanism was
      // originally proven only against buttons (captureTextSelection is a
      // no-op on those). Repair, ticket 14 (review blocker G04):
      // ui/card-forms.js's own comment/prompt-edit textarea and reason
      // input, and ui/media.js's own result-card thumbnail button, now
      // carry this same hook too -- each with its own `data-action`
      // distinct from its row's toggle button (`"<action>-comment"`,
      // `"edit-text"`/`"edit-reason"`, `"open"`), so an exact match here
      // never confuses a text field with the button that opened it. No
      // change was needed in this function itself: it was already generic
      // over "whatever is focused right now carries this hook", cursor
      // preservation included.
      return { targetId, action, selection: captureTextSelection(active) };
    }
  }
  return null;
}

/**
 * The still-current control `note` (`{targetId, action}`) names, searched
 * inside `zone` alone -- the exact `[data-hook="card-control"]` match
 * first, or, when that one no longer exists or exists but is no longer
 * focusable (an edge-disabled "Ниже", a sibling action a fresh decision
 * just removed), the "ближайший контрол того же элемента" (repair
 * condition 7/craft finding 7): any *other* `[data-hook="card-control"]`
 * sharing the same `data-target-id`, found purely by that documented hook
 * -- never media.js's own `.media-thumb-button` class, an implementation
 * detail this module has no business knowing about. (The old fallback
 * here reached for exactly that class, and only ever recognized a card via
 * `data-result-id`/`data-version-id`/`data-prompt-id` -- a scene block,
 * identified by `data-scene-id` alone, never matched either of those, so a
 * scene that landed on the edge after "Ниже" fell straight through to the
 * stage-review heading below.) `null` when `zone` has nothing left for
 * this target at all -- the caller's cue to try elsewhere.
 */
function findCardControlFocusTarget(zone, note) {
  if (!zone || !note) {
    return null;
  }
  const { targetId, action } = note;
  const exact = zone.querySelector(
    `[data-hook="card-control"][data-target-id="${CSS.escape(targetId)}"][data-action="${CSS.escape(action)}"]`,
  );
  if (isFocusable(exact)) {
    return exact;
  }
  for (const candidate of zone.querySelectorAll(
    `[data-hook="card-control"][data-target-id="${CSS.escape(targetId)}"]`,
  )) {
    if (isFocusable(candidate)) {
      return candidate;
    }
  }
  return null;
}

/** The absolute-last-resort landmark for a card-control note that matched
 * nothing at all in either zone (an entire row -- prompt entry or result
 * card alike -- retired or advanced past in the very repaint that applied
 * the decision). Extracted (ticket 14 punch-list item 1) so
 * `repaintZonePreservingFocus`'s own cross-zone tail in `renderShell` is the
 * one place that picks this landmark, never a second copy that could
 * silently drift apart. `main`'s own stage-review heading always wins over
 * `inspector`'s whenever it exists at all -- an arbitrary but stable
 * tie-break, unrelated to which zone the note was actually about (there is
 * no better signal left once neither zone matched anything real). */
function focusCardFallbackHeading(main, inspector) {
  const stageHeading = main ? main.querySelector('[data-hook="stage-actions"] h3') : null;
  if (stageHeading) {
    // A heading is not natively focusable -- only reached once nothing
    // real is left in either zone for this target at all. Better than
    // leaving the browser to drop focus on `<body>` with no landmark at
    // all.
    stageHeading.tabIndex = -1;
    stageHeading.focus();
    return;
  }
  const inspectorHeading = inspector ? inspector.querySelector('[data-hook="inspector-heading"]') : null;
  if (inspectorHeading) {
    inspectorHeading.tabIndex = -1;
    inspectorHeading.focus();
  }
}

// Ticket 14 repair 2, condition 15 (craft review finding 3): `restoreCardFocus`
// used to live here -- a standalone "main first, then inspector, first match
// wins" resolver -- but nothing in production ever called it. The real path,
// `renderShell`'s own tail below, resolves the *same* question differently:
// each zone's own `repaintZonePreservingFocus` call restores card-control
// focus for itself, and `renderShell` gates `inspector`'s own call on
// whether `main`'s one already placed it (`mainCardFocusPlaced`) rather than
// asking one function to try both zones in order. Six tests here used to pin
// this dead function's own "main before inspector" behaviour instead of
// the real one; they now exercise `renderShell` itself (see the "questions-
// panel/card-control focus, production path" section below), including the
// one case a dead-code stand-in could never actually prove: a target/action
// pair that genuinely exists in *both* zones at once, where the real
// sequential-bracket-calls path could, without the `mainCardFocusPlaced`
// gate, have let `inspector` steal focus straight back from `main`.

// -----------------------------------------------------------------------
// Approved-script version-summary focus preservation -- repair, ticket 14
// (review blocker G04). A third, narrower axis alongside the two above: a
// native `<summary>` disclosure toggle (ui/scenario.js's own
// `buildCollapsedScriptVersionItem`, the read-only approved-script echo
// shown above the per-scene blocks) is genuinely focusable, but is neither
// scene-hooked (`SCENE_FOCUS_HOOKS` is keyed by `data-scene-id`; this panel
// sits above any one scene) nor a `card-control` (it submits nothing, so a
// `data-target-id`/`data-action` pair would not even mean anything here).
// `data-version-id` alone -- the one real, stable identity
// ui/scenario.js's own `versionDisclosureOverrides` already keys its own
// open/closed memory by -- is the whole axis. Main-only: the collapsed
// disclosure never appears in the inspector (`renderSceneBlockVersions`
// there reuses the *other*, always-expanded `buildScriptVersionItem`
// instead), so unlike captureSceneFocus/captureLiveCardControlFocus this
// pair never needs to resolve across two zones.
//
// Unlike the scene-edit-save button (ticket 06 condition 4), nothing ever
// disables or removes a `<summary>` synchronously before a repaint runs --
// toggling it only flips `versionDisclosureOverrides`, never triggers
// `submitAction`/a network call of its own -- so the live-DOM capture
// alone is enough; no pending-note relay is needed here the way
// `studio:scene-focus-pending`/`studio:card-focus-pending` are for their
// own mechanisms.
// -----------------------------------------------------------------------

/** `null` unless `document.activeElement` is, right now, a version
 * summary's own disclosure toggle inside `zone` -- mirrors
 * `captureLiveCardControlFocus`'s own shape (a live-DOM-only check, no
 * relay), for the one hook/id pair that mechanism does not itself cover. */
export function captureVersionSummaryFocus(zone) {
  const active = document.activeElement;
  if (
    zone &&
    active instanceof HTMLElement &&
    zone.contains(active) &&
    active.dataset.hook === "script-version-summary"
  ) {
    const versionId = active.dataset.versionId;
    if (versionId) {
      return { versionId, selection: captureTextSelection(active) };
    }
  }
  return null;
}

/** The other half: re-focus the freshly-painted `<summary>` for the same
 * version id, once `zone` has been fully rebuilt. No fallback beyond that
 * exact match -- a version dropped from history is not expected in
 * practice (the ledger is append-only, see `pruneVersionDisclosureOverrides`'s
 * own comment in ui/scenario.js), and there is no other row a lost version's
 * own disclosure could meaningfully fall back to. */
export function restoreVersionSummaryFocus(zone, captured) {
  if (!zone || !captured) {
    return;
  }
  const target = zone.querySelector(
    `[data-hook="script-version-summary"][data-version-id="${CSS.escape(captured.versionId)}"]`,
  );
  if (isFocusable(target)) {
    target.focus();
    applyTextSelection(target, captured.selection);
  }
}

// -----------------------------------------------------------------------
// The repaint-preserving-focus bracket itself -- ticket 14 punch-list item
// 1 ("Мутация 7: связка capture/restore в renderShell не закреплена").
// `renderShell`'s own `if (main) {...}`/`if (inspector) {...}` blocks used
// to inline "capture every axis -> repaint -> restore every axis" by hand,
// twice, with nothing exported that a test could drive against a fake
// repaint step -- so a mutation dropping one axis, or dropping the whole
// bracket call, went unnoticed by anything except a live browser. Extracted
// here, once, so `renderShell` becomes a thin caller and
// tests/ui/repaint-preservation.test.mjs can exercise the bracket itself
// with a synthetic zone and a synthetic repaint function, independent of
// paintMain/paintInspector's own much larger surface.
// -----------------------------------------------------------------------

/**
 * Capture the focus-preservable axes (scene, card-control, version) live inside
 * `zone`, run `repaint()` (whatever tears
 * `zone` down and rebuilds it -- `paintMain`/`paintInspector` in production,
 * a hand-built stand-in in a test), then restore whichever axis actually had
 * something. Returns `true` when the card-control axis was placed *in this
 * zone* -- `renderShell` uses that to decide whether the cross-zone heading
 * fallback (`focusCardFallbackHeading`) is still needed once both zones have
 * had their turn.
 *
 * Scene and version are cleanly single-zone concepts already; capturing them
 * right here, before `repaint()`, reuses their own focus helpers directly.
 *
 * Card-control is different: it can genuinely live in *either* zone, and
 * its own *relay* half (`studio:card-focus-pending`, the synchronous-
 * disable-before-repaint case ticket 06 condition 4 first diagnosed) is a
 * one-time, side-effecting drain that cannot belong to either zone's own
 * bracket call without risking the exact cross-zone bug repair condition 7
 * fixed (whichever zone asks first steals a note meant for the other). So
 * `cardFocusNote` is *not* captured in here at all -- `renderShell` computes
 * it once, globally, before calling this bracket for either zone (exactly
 * the same `captureLiveCardControlFocus() || takePendingCardFocus()` shape
 * the pre-extraction code already used), and hands the *same* value to both
 * calls -- except, repair 2 condition 15, once `main`'s own call has already
 * placed it: `renderShell`'s own tail then hands `inspector` a bare `null`
 * instead, so this bracket is never even asked to look for a target/action
 * pair `main` already claimed. This bracket's own job for that axis is
 * purely the *restore* half, scoped to `zone`: does a control matching
 * `cardFocusNote` exist here, post-repaint? If both zones say no,
 * `renderShell`'s own tail falls back to a heading -- this bracket never
 * guesses at that on its own, since it only ever sees one zone at a time.
 */
export function repaintZonePreservingFocus(zone, repaint, cardFocusNote) {
  if (!zone) {
    if (typeof repaint === "function") {
      repaint();
    }
    return false;
  }
  const capturedScene = captureSceneFocus(zone);
  const capturedVersion = captureVersionSummaryFocus(zone);

  repaint();

  restoreSceneFocus(zone, capturedScene);
  restoreVersionSummaryFocus(zone, capturedVersion);

  if (!cardFocusNote) {
    return false;
  }
  const target = findCardControlFocusTarget(zone, cardFocusNote);
  if (!target) {
    return false;
  }
  target.focus();
  applyTextSelection(target, cardFocusNote.selection);
  return true;
}

/**
 * Render the top bar and main/inspector slots into `root` (the `.app-shell`
 * container). `state` is the store's full view model
 * (`{status, snapshot, stageTabs, error, ...}`); only the current stage's
 * slot is ever painted — future stages never reach the DOM.
 *
 * A commit that only changes the rail's filter/query (typing in the search
 * box, clicking a filter chip) leaves `status`/`snapshot` untouched, so it
 * is skipped here entirely: nothing in these three zones would change, and
 * repainting anyway would needlessly tear down whatever currently holds
 * focus inside them and re-announce the live region on every keystroke.
 * The cached key lives on `root` itself (mirrors rail.js's `__railRefs`
 * pattern) so this holds across every call, not just consecutive ones.
 *
 * A commit that changes `selectedSceneId` still fully repaints `main`
 * (task 06/07's shared decision -- see `shellZonesNeedRepaint`'s own test),
 * so scene-selection focus survival is this function's own job:
 * `captureSceneFocus`/`restoreSceneFocus` bracket the repaint below, mirroring
 * ui/rail.js's identical capture-rebuild-restore shape for the project list.
 * Auto-scroll (ui/timeline.js's `scrollSceneIntoView`) is gated on
 * `selectionChanged` -- computed here, once, from the very same previous/next
 * comparison this function already makes for the repaint key -- so an
 * unrelated repaint with the same selection (a snapshot poll, a filter
 * click) never re-triggers a scroll.
 */
export function renderShell(root, state) {
  if (!root) {
    throw new TypeError("root is required");
  }
  const previousKey = root.__shellRenderKey;
  const nextSelectedSceneId = state?.selectedSceneId ?? null;
  const selectionChanged =
    Boolean(nextSelectedSceneId) &&
    (!previousKey || previousKey.selectedSceneId !== nextSelectedSceneId);
  root.__shellRenderKey = {
    status: state?.status,
    snapshot: state?.snapshot ?? null,
    selectedSceneId: nextSelectedSceneId,
    viewedStage: state?.viewedStage ?? null,
    historyOpen: Boolean(state?.historyOpen),
  };
  root.dataset.historyOpen = String(Boolean(state?.historyOpen));
  if (!shellZonesNeedRepaint(previousKey, state)) {
    return;
  }
  const topbarContent = root.querySelector('[data-hook="topbar-content"]');
  const main = root.querySelector("#main") || root.querySelector('[data-hook="main"]');
  const historyPanel = root.querySelector('[data-hook="history-panel"]');
  if (topbarContent) {
    paintTopbar(topbarContent, state);
  }

  // Card-control focus (repair condition 7/8): computed once, globally,
  // *before* either zone is torn down -- exactly the pre-extraction shape
  // (see `repaintZonePreservingFocus`'s own banner for why this specific
  // axis cannot be captured fresh inside each zone's own bracket call the
  // way scene/version are). Both sides are always evaluated, live-DOM
  // first, so `takePendingCardFocus` drains the global relay note
  // unconditionally and it can never leak into a later, unrelated repaint
  // regardless of which zone (if either) actually ends up using it.
  const liveCardFocus = captureLiveCardControlFocus();
  const relayedCardFocus = takePendingCardFocus();
  const cardFocusNote = liveCardFocus || relayedCardFocus;

  // ticket 14 punch-list item 1: both zones now go through the one shared
  // bracket (`repaintZonePreservingFocus`) instead of `renderShell` inlining
  // its own copy of "capture every axis -> repaint -> restore every axis"
  // twice by hand -- see that function's own banner for what each of the
  // three axes (scene, card-control, version) does inside it.
  let mainCardFocusPlaced = false;
  if (main) {
    mainCardFocusPlaced = repaintZonePreservingFocus(
      main,
      () =>
        paintMain(main, state, {
          selectionChanged,
          origin: state?.selectedSceneOrigin ?? null,
          reducedMotion: window.matchMedia("(prefers-reduced-motion: reduce)").matches,
        }),
      cardFocusNote,
    );
  }
  if (historyPanel) {
    renderHistoryPanel(historyPanel, {
      open: Boolean(state?.historyOpen),
      history: state?.snapshot?.active_project?.history ?? [],
    });
  }
  // Only reached once *neither* zone's own bracket call placed the
  // card-control note anywhere real -- an entire row retired or advanced
  // past in the very repaint that applied the decision (repair condition 7
  // itself: this ordering, only after both zones have already repainted, is
  // what makes "which zone actually has this control now" a question with
  // one honest answer).
  if (cardFocusNote && !mainCardFocusPlaced) {
    focusCardFallbackHeading(main, null);
  }
  const historyWasOpen = Boolean(previousKey?.historyOpen);
  const historyIsOpen = Boolean(state?.historyOpen);
  if (!historyWasOpen && historyIsOpen) {
    historyPanel?.querySelector('[data-hook="history-close"]')?.focus();
  } else if (historyWasOpen && !historyIsOpen) {
    topbarContent?.querySelector('[data-hook="history-toggle"]')?.focus();
  }
  updateLiveRegion(state);
}
