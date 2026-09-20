// Task 35: the dedicated step-1 surface from the Claude Design flow.
// The legacy scenario/timeline renderer remains intact in scenario.js as the
// owner-gated rollback path; shell.js registers this renderer over it.

import {
  resolveActionErrorMessage,
  resolveActionFailureText,
  submitAction,
  submitActionsSequentially,
} from "./actions.js";
import { draftKey, getDraft, setDraft, clearDraft, pruneDrafts } from "./card-drafts.js";
import {
  markControlHooks,
  noteCardFocusPending,
  OUTCOME_UNCONFIRMED_TEXT,
  requestProjectRefresh,
} from "./card-forms.js";
import { buildReorderOrder } from "./card-reorder.js";
import { storyboardModel } from "./scenario.js";
import { agentControl, exactTarget } from "./agent-control.js";

const REVISION_SENT_TEXT = "Отправлено, ждём ответа в чате";
const SCENE_SAVE_FAILURE_TEXT = "Не удалось сохранить правку. Проверьте актуальность сценария в чате.";

function statusLine(className = "step-scenario-status") {
  const status = document.createElement("p");
  status.className = className;
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  return status;
}

function headingWithChips(titleText, chips) {
  const row = document.createElement("div");
  row.className = "step-scenario-heading-row";
  const heading = document.createElement("h2");
  heading.textContent = titleText;
  row.append(heading);
  for (const chip of chips) {
    const badge = document.createElement("span");
    badge.className = "step-scenario-chip";
    badge.dataset.tone = chip.tone || "neutral";
    badge.textContent = chip.text;
    row.append(badge);
  }
  return row;
}

function saveDraftValue(key, value) {
  setDraft(key, { ...(getDraft(key) || {}), ...value });
}

function releaseDisappearingFocus(control) {
  if (document.activeElement === control && typeof control.blur === "function") {
    control.blur();
  }
}

function makeHookedButton({ text, targetId, action, className = "step-scenario-button", disabled = false }) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = className;
  button.textContent = text;
  button.disabled = disabled;
  markControlHooks(button, targetId, action);
  return button;
}

function buildScriptSection(model, readOnly = false) {
  const section = document.createElement("section");
  section.className = "step-scenario-section step-scenario-script";
  section.append(
    headingWithChips("Сценарий", [
      { text: model.scriptApproved ? "Одобрен" : "Ждёт решения", tone: model.scriptApproved ? "success" : "neutral" },
      ...(model.activeScriptVersion ? [{ text: `v${model.activeScriptVersion}`, tone: "outline" }] : []),
    ]),
  );

  const key = draftKey(model.projectId, "step-scenario", "script");
  let draft = getDraft(key);
  if (Number.isFinite(draft?.savedRevision) && Number.isFinite(model.revision) && model.revision > draft.savedRevision) {
    clearDraft(key);
    draft = undefined;
  }
  const textarea = document.createElement("textarea");
  textarea.className = "step-scenario-script-text";
  textarea.value = typeof draft?.value === "string" ? draft.value : model.activeScriptText;
  textarea.readOnly = !model.canEdit;
  textarea.disabled = Boolean(draft?.saving);
  textarea.setAttribute("aria-label", "Текст сценария");
  if (model.canEdit) {
    markControlHooks(textarea, "scenario", "edit-script");
  }

  const controls = document.createElement("div");
  controls.className = "step-scenario-inline-actions";
  const save = makeHookedButton({ text: "Сохранить", targetId: "scenario", action: "edit-script-save" });
  save.classList.add("step-scenario-button-primary");
  const reset = makeHookedButton({ text: "Сбросить", targetId: "scenario", action: "edit-script-reset" });
  const status = statusLine();
  status.textContent = draft?.message || "";

  function syncDraftUi() {
    const dirty = textarea.value !== model.activeScriptText;
    controls.replaceChildren(...(dirty ? [save, reset] : []));
    save.disabled = !textarea.value.trim() || Boolean(getDraft(key)?.saving);
    reset.disabled = Boolean(getDraft(key)?.saving);
  }
  textarea.addEventListener("input", () => {
    saveDraftValue(key, { value: textarea.value, message: "", saving: false });
    status.textContent = "";
    syncDraftUi();
  });
  reset.addEventListener("click", () => {
    textarea.value = model.activeScriptText;
    clearDraft(key);
    status.textContent = "";
    syncDraftUi();
    textarea.focus();
  });
  save.addEventListener("click", async () => {
    if (!textarea.value.trim()) {
      status.textContent = "Введите текст сценария.";
      return;
    }
    noteCardFocusPending("scenario", "edit-script-save");
    status.textContent = "Сохраняется…";
    saveDraftValue(key, { value: textarea.value, message: status.textContent, saving: true });
    const result = await submitActionsSequentially({
      actions: [{ actionType: "edit", targetId: "scenario", payload: { text: textarea.value } }],
      expectedRevision: model.revision,
      controls: [textarea, save, reset],
    });
    if (result.ok && result.confirmed !== false && result.completed === 1) {
      status.textContent = "Сохранено";
      saveDraftValue(key, {
        value: textarea.value,
        message: status.textContent,
        saving: false,
        savedRevision: result.confirmedRevision,
      });
      releaseDisappearingFocus(save);
      requestProjectRefresh(model.projectId);
      return;
    }
    status.textContent = result.ok
      ? OUTCOME_UNCONFIRMED_TEXT
      : result.code === "action_failed"
        ? SCENE_SAVE_FAILURE_TEXT
        : resolveActionErrorMessage(result.code);
    saveDraftValue(key, { value: textarea.value, message: status.textContent, saving: false });
    if (!result.ok && ["revision_conflict", "action_failed"].includes(result.code)) {
      requestProjectRefresh(model.projectId);
    }
  });
  syncDraftUi();
  section.append(textarea);
  if (model.canEdit) {
    section.append(controls, status);
  } else if (readOnly) {
    section.append(agentControl({ label: "Изменить сценарий", title: "Изменить сценарий", targetId: "scenario", action: "edit-script-chat",
      prompt: `Открой проект: ${exactTarget({ projectId: model.projectId, targetId: "scenario", versionId: model.activeScriptVersionId, revision: model.revision })}. Спроси, что изменить, подготовь новую версию сценария, покажи её целиком и только после моего подтверждения запиши через штатную команду Creator Studio.` }));
  }
  return section;
}

function sceneValues(scene, draft) {
  return {
    title: typeof draft?.title === "string" ? draft.title : scene.title,
    text: typeof draft?.text === "string" ? draft.text : scene.text,
    durationSeconds: draft?.durationSeconds ?? scene.durationSeconds,
  };
}

function validateSceneValues(values, isPhoto) {
  return {
    title: values.title.trim() ? "" : "Введите название кадра.",
    text: values.text.trim() ? "" : "Введите описание кадра.",
    duration:
      isPhoto || (Number.isInteger(Number(values.durationSeconds)) && Number(values.durationSeconds) >= 1)
        ? ""
        : "Длительность должна быть не меньше 1 секунды.",
  };
}

function buildSceneRow(model, scene, sceneIds, readOnly = false) {
  const isPhoto = model.projectType === "photo";
  const key = draftKey(model.projectId, "step-scenario", scene.sceneId);
  let draft = getDraft(key);
  if (Number.isFinite(draft?.savedRevision) && Number.isFinite(model.revision) && model.revision > draft.savedRevision) {
    clearDraft(key);
    draft = undefined;
  }
  const saving = Boolean(draft?.saving);
  const values = sceneValues(scene, draft);
  const row = document.createElement("li");
  row.className = "step-storyboard-row";
  row.dataset.hook = "storyboard-row";
  row.dataset.sceneId = scene.sceneId;
  row.dataset.changedByYou = String(scene.changedByYou);
  row.dataset.projectType = model.projectType;

  const time = isPhoto ? null : document.createElement("div");
  let duration = null;
  if (!isPhoto) {
    time.className = "step-storyboard-time";
    const range = document.createElement("span");
    range.dataset.hook = "storyboard-range";
    range.textContent = scene.rangeLabel;
    const durationWrap = document.createElement("label");
    durationWrap.className = "step-storyboard-duration";
    duration = document.createElement("input");
    duration.type = "number";
    duration.min = "1";
    duration.step = "1";
    duration.value = String(values.durationSeconds ?? "");
    duration.readOnly = !model.canEdit;
    duration.disabled = saving;
    duration.setAttribute("aria-label", `Длительность кадра ${scene.order}, секунд`);
    if (model.canEdit) {
      markControlHooks(duration, scene.sceneId, "edit-duration");
    }
    const suffix = document.createElement("span");
    suffix.textContent = "сек";
    durationWrap.append(duration, suffix);
    time.append(range, durationWrap);
  }

  const fields = document.createElement("div");
  fields.className = "step-storyboard-fields";
  const title = document.createElement("input");
  title.type = "text";
  title.maxLength = 200;
  title.value = values.title;
  title.readOnly = !model.canEdit;
  title.disabled = saving;
  title.setAttribute("aria-label", `Название кадра ${scene.order}`);
  const text = document.createElement("textarea");
  text.value = values.text;
  text.readOnly = !model.canEdit;
  text.disabled = saving;
  text.setAttribute("aria-label", `Описание кадра ${scene.order}`);
  if (model.canEdit) {
    markControlHooks(title, scene.sceneId, "edit-title");
    markControlHooks(text, scene.sceneId, "edit-text");
  }
  fields.append(title, text);
  if (scene.changedByYou) {
    const changed = document.createElement("span");
    changed.className = "step-scenario-chip step-storyboard-changed";
    changed.dataset.tone = "info";
    changed.textContent = "Изменено вами";
    fields.append(changed);
  }

  const reorder = document.createElement("div");
  reorder.className = "step-storyboard-reorder";
  const up = model.canReorder
    ? makeHookedButton({ text: "↑", targetId: scene.sceneId, action: "reorder-up", disabled: saving || scene.order <= 1 })
    : null;
  const down = model.canReorder
    ? makeHookedButton({ text: "↓", targetId: scene.sceneId, action: "reorder-down", disabled: saving || scene.order >= sceneIds.length })
    : null;
  if (up && down) {
    up.setAttribute("aria-label", "Переместить выше");
    down.setAttribute("aria-label", "Переместить ниже");
    reorder.append(up, down);
  }

  const editor = document.createElement("div");
  editor.className = "step-storyboard-editor";
  const error = document.createElement("p");
  error.className = "step-storyboard-error";
  const saveRow = document.createElement("div");
  saveRow.className = "step-scenario-inline-actions";
  const save = makeHookedButton({ text: "Сохранить", targetId: scene.sceneId, action: "edit-scene-save" });
  save.classList.add("step-scenario-button-primary");
  const reset = makeHookedButton({ text: "Сбросить", targetId: scene.sceneId, action: "edit-scene-reset" });
  const status = statusLine();
  status.textContent = resolveActionFailureText(model.actions, "edit", scene.sceneId, SCENE_SAVE_FAILURE_TEXT) || draft?.message || "";
  editor.append(error, saveRow, status);

  function currentValues() {
    return {
      title: title.value,
      text: text.value,
      durationSeconds: isPhoto ? null : duration?.value,
    };
  }
  function changedFields(current) {
    const changes = [];
    if (current.title !== scene.title) changes.push({ field: "title", value: current.title });
    if (current.text !== scene.text) changes.push({ field: "text", value: current.text });
    if (!isPhoto && Number(current.durationSeconds) !== scene.durationSeconds) {
      changes.push({ field: "duration_ms", value: Number(current.durationSeconds) * 1000 });
    }
    return changes;
  }
  function syncEditor() {
    const current = currentValues();
    const errors = validateSceneValues(current, isPhoto);
    const firstError = errors.title || errors.text || errors.duration;
    error.textContent = firstError;
    const dirty = changedFields(current).length > 0;
    saveRow.replaceChildren(...(dirty ? [save, reset] : []));
    save.disabled = Boolean(firstError) || Boolean(getDraft(key)?.saving);
    reset.disabled = Boolean(getDraft(key)?.saving);
  }
  function persist(message = status.textContent, saving = false, extra = {}) {
    saveDraftValue(key, { ...currentValues(), message, saving, ...extra });
  }
  const editableFields = [
    { field: title, action: "edit-title" },
    { field: text, action: "edit-text" },
    ...(isPhoto ? [] : [{ field: duration, action: "edit-duration" }]),
  ];
  for (const { field, action } of editableFields) {
    field.addEventListener("input", () => {
      status.textContent = "";
      persist("", false, { lastEditedAction: action });
      syncEditor();
    });
  }
  reset.addEventListener("click", () => {
    title.value = scene.title;
    text.value = scene.text;
    if (!isPhoto) duration.value = String(scene.durationSeconds);
    clearDraft(key);
    status.textContent = "";
    syncEditor();
    title.focus();
  });
  save.addEventListener("click", async () => {
    const current = currentValues();
    const errors = validateSceneValues(current, isPhoto);
    const firstError = errors.title || errors.text || errors.duration;
    if (firstError) {
      error.textContent = firstError;
      return;
    }
    const actions = changedFields(current).map((change) => ({
      actionType: "edit",
      targetId: scene.sceneId,
      payload: change,
    }));
    if (actions.length === 0) return;
    const focusAction = getDraft(key)?.lastEditedAction || "edit-title";
    noteCardFocusPending(scene.sceneId, focusAction);
    status.textContent = "Сохраняется…";
    persist(status.textContent, true);
    const controls = [title, text, save, reset, ...(isPhoto ? [] : [duration])];
    const result = await submitActionsSequentially({ actions, expectedRevision: model.revision, controls });
    if (result.ok && result.confirmed !== false && result.completed === actions.length) {
      status.textContent = "Сохранено";
      saveDraftValue(key, {
        ...current,
        message: status.textContent,
        saving: false,
        savedRevision: result.confirmedRevision,
        lastEditedAction: focusAction,
      });
      releaseDisappearingFocus(save);
      requestProjectRefresh(model.projectId);
      return;
    }
    status.textContent = result.ok
      ? OUTCOME_UNCONFIRMED_TEXT
      : result.code === "action_failed"
        ? SCENE_SAVE_FAILURE_TEXT
        : resolveActionErrorMessage(result.code);
    persist(status.textContent, false);
    if (result.completed > 0 || (!result.ok && ["revision_conflict", "action_failed"].includes(result.code))) {
      requestProjectRefresh(model.projectId);
    }
  });

  async function move(direction, button) {
    const order = buildReorderOrder(sceneIds, scene.sceneId, direction);
    if (!order) return;
    noteCardFocusPending(scene.sceneId, direction < 0 ? "reorder-up" : "reorder-down");
    status.textContent = "Отправляется…";
    const result = await submitAction({
      actionType: "reorder",
      targetId: "scenes",
      payload: { order },
      expectedRevision: model.revision,
      controls: [up, down, button],
    });
    if (result.ok && result.confirmed !== false) {
      requestProjectRefresh(model.projectId);
    } else {
      status.textContent = result.ok ? OUTCOME_UNCONFIRMED_TEXT : resolveActionErrorMessage(result.code);
      if (!result.ok && result.code === "revision_conflict") requestProjectRefresh(model.projectId);
    }
  }
  up?.addEventListener("click", () => move(-1, up));
  down?.addEventListener("click", () => move(1, down));
  syncEditor();
  if (time) row.append(time);
  row.append(fields);
  if (model.canReorder) row.append(reorder);
  if (model.canEdit) row.append(editor);
  if (readOnly) {
    const chat = document.createElement("div");
    chat.className = "agent-prompt-actions";
    chat.append(
      agentControl({ label: "Изменить кадр", title: `Изменить кадр ${scene.order}`, targetId: scene.sceneId, action: "edit-scene-chat",
        prompt: `Открой ${exactTarget({ projectId: model.projectId, targetId: scene.sceneId, revision: model.revision })}. Спроси, какие поля кадра изменить (название, описание${isPhoto ? "" : ", длительность"}), покажи точную правку и после моего подтверждения примени её штатной командой Creator Studio.` }),
      agentControl({ label: "Переставить", title: `Переставить кадр ${scene.order}`, targetId: scene.sceneId, action: "reorder-scene-chat",
        prompt: `Открой ${exactTarget({ projectId: model.projectId, targetId: scene.sceneId, revision: model.revision })}. Спроси, на какую позицию переместить этот кадр, покажи новый полный порядок scene_id и после моего подтверждения примени reorder штатной командой Creator Studio.` }),
    );
    row.append(chat);
  }
  return row;
}

function buildStoryboardSection(model, readOnly = false) {
  const section = document.createElement("section");
  section.className = "step-scenario-section step-storyboard";
  const heading = headingWithChips("Раскадровка по секундам", []);
  if (model.projectType === "photo") heading.querySelector("h2").textContent = "Раскадровка";
  section.append(heading);
  const description = document.createElement("p");
  description.className = "step-scenario-description";
  description.textContent = model.scriptApproved
    ? "Одобренная раскадровка. Для правок вернитесь к сценарию."
    : model.projectType === "photo"
      ? "Название и описание каждого кадра меняются прямо здесь."
      : "Название, описание и длительность каждого кадра меняются прямо здесь.";
  section.append(description);

  const list = document.createElement("ol");
  list.className = "step-storyboard-list";
  const sceneIds = model.scenes.map((scene) => scene.sceneId);
  for (const scene of model.scenes) list.append(buildSceneRow(model, scene, sceneIds, readOnly));
  section.append(list);
  if (model.scenes.length === 0) {
    const empty = document.createElement("p");
    empty.className = "step-storyboard-empty";
    empty.textContent = "Кадров пока нет. Агент создаст раскадровку, или добавьте кадр сами";
    section.append(empty);
  }

  const footer = document.createElement("div");
  footer.className = "step-storyboard-footer";
  if (model.canAdd) {
    const add = makeHookedButton({ text: "+ Добавить кадр", targetId: "scenes", action: "scene-add" });
    add.classList.add("step-storyboard-add");
    const addStatus = statusLine();
    add.addEventListener("click", async () => {
      noteCardFocusPending("scenes", "scene-add");
      addStatus.textContent = "Добавляется…";
      const result = await submitAction({
        actionType: "scene-add",
        targetId: "scenes",
        payload: {},
        expectedRevision: model.revision,
        controls: [add],
      });
      if (result.ok && result.confirmed !== false) {
        requestProjectRefresh(model.projectId);
      } else {
        addStatus.textContent = result.ok ? OUTCOME_UNCONFIRMED_TEXT : resolveActionErrorMessage(result.code);
        if (!result.ok && result.code === "revision_conflict") requestProjectRefresh(model.projectId);
      }
    });
    footer.append(add, addStatus);
  } else if (readOnly) {
    footer.append(agentControl({ label: "+ Добавить кадр", title: "Добавить кадр", targetId: "scenes", action: "scene-add-chat",
      prompt: `Открой ${exactTarget({ projectId: model.projectId, targetId: "scenes", revision: model.revision })}. Спроси содержание нового кадра${model.projectType === "photo" ? "" : " и длительность"}, предложи его место в раскадровке и после моего подтверждения добавь штатной командой Creator Studio.` }));
  }
  if (model.totalDurationLabel) {
    const total = document.createElement("p");
    total.dataset.hook = "storyboard-total";
    total.textContent = `Итого ${model.totalDurationLabel} · длительность считается из кадров`;
    footer.append(total);
  }
  section.append(footer);
  return section;
}

function buildStepActions(model) {
  const wrap = document.createElement("div");
  wrap.className = "step-scenario-actions";
  const approve = makeHookedButton({
    text: "Одобрить сценарий",
    targetId: "scenario",
    action: "approve-scenario",
    disabled: !model.canApprove,
  });
  approve.classList.add("step-scenario-button-primary");
  if (model.approveHint) approve.setAttribute("title", model.approveHint);
  const revise = makeHookedButton({
    text: "Отправить на доработку",
    targetId: "scenario",
    action: "revise-scenario",
    disabled: !model.canRevise,
  });
  const status = statusLine();
  const pendingRevision = model.actions.some(
    (action) =>
      action?.action_type === "revise-scenario" &&
      action.target_id === "scenario" &&
      (action.status === "queued" || action.status === "running"),
  );
  status.textContent = pendingRevision ? REVISION_SENT_TEXT : "";
  approve.addEventListener("click", async () => {
    noteCardFocusPending("scenario", "approve-scenario");
    status.textContent = "Отправляется…";
    const result = await submitAction({
      actionType: "approve-scenario",
      targetId: "scenario",
      payload: {},
      expectedRevision: model.revision,
      controls: [approve, revise],
    });
    if (result.ok && result.confirmed !== false) {
      requestProjectRefresh(model.projectId);
    } else {
      status.textContent = result.ok ? OUTCOME_UNCONFIRMED_TEXT : resolveActionErrorMessage(result.code);
      if (!result.ok && result.code === "revision_conflict") requestProjectRefresh(model.projectId);
    }
  });
  revise.addEventListener("click", async () => {
    noteCardFocusPending("scenario", "revise-scenario");
    status.textContent = "Отправляется…";
    const result = await submitAction({
      actionType: "revise-scenario",
      targetId: "scenario",
      payload: {},
      expectedRevision: model.revision,
      controls: [approve, revise],
      awaitUpdate: false,
      reenableOnSuccess: true,
    });
    status.textContent = result.ok ? REVISION_SENT_TEXT : resolveActionErrorMessage(result.code);
    if (!result.ok && result.code === "revision_conflict") requestProjectRefresh(model.projectId);
  });
  wrap.append(approve, revise, status);
  return wrap;
}

export function renderScenarioStep(root, { state, readOnly }) {
  root.textContent = "";
  const model = storyboardModel(state?.snapshot, { readOnly });
  const surface = document.createElement("div");
  surface.className = "step-scenario";
  surface.dataset.hook = "step-scenario";
  if (model.kind === "empty") {
    surface.setAttribute("aria-busy", "true");
    const skeleton = document.createElement("div");
    skeleton.className = "step-scenario-skeleton";
    skeleton.textContent = "Загружаем сценарий…";
    surface.append(skeleton);
    root.append(surface);
    return;
  }

  const prefix = `${model.projectId}::step-scenario::`;
  const knownDrafts = new Set([
    draftKey(model.projectId, "step-scenario", "script"),
    ...model.scenes.map((scene) => draftKey(model.projectId, "step-scenario", scene.sceneId)),
  ]);
  pruneDrafts(prefix, knownDrafts);
  surface.append(buildScriptSection(model, readOnly), buildStoryboardSection(model, readOnly));
  if (!readOnly && state?.snapshot?.view_stage?.current_stage === "scenario") {
    surface.append(buildStepActions(model));
  } else if (readOnly) {
    const decisions = document.createElement("div");
    decisions.className = "step-scenario-actions";
    decisions.append(
      agentControl({ label: "Одобрить сценарий", title: "Одобрить сценарий", targetId: "scenario", action: "approve-scenario-chat", className: "agent-prompt-button agent-prompt-button-primary",
        prompt: `Открой ${exactTarget({ projectId: model.projectId, targetId: "scenario", versionId: model.activeScriptVersionId, revision: model.revision })}. Проверь, что сценарий и раскадровка полны. Если есть блокеры, перечисли их и не меняй состояние; иначе одобри сценарий штатной командой Creator Studio и сообщи результат.` }),
      agentControl({ label: "Отправить на доработку", title: "Доработать сценарий", targetId: "scenario", action: "revise-scenario-chat",
        prompt: `Открой ${exactTarget({ projectId: model.projectId, targetId: "scenario", versionId: model.activeScriptVersionId, revision: model.revision })}. Спроси замечания, предложи план доработки и после моего подтверждения запусти revise-scenario в рабочем чате.` }),
    );
    surface.append(decisions);
  }
  root.append(surface);
}

export { REVISION_SENT_TEXT };
