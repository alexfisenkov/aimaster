import { resolveActionErrorMessage, submitAction, submitActionsSequentially } from "./actions.js";
import { agentControl, exactTarget } from "./agent-control.js";
import { clearDraft, draftKey, getDraft, setDraft } from "./card-drafts.js";
import {
  markControlHooks,
  noteCardFocusPending,
  OUTCOME_UNCONFIRMED_TEXT,
  requestProjectRefresh,
} from "./card-forms.js";
import { appendMissingTags, missingTags, renderTagChips } from "./tag-chips.js";

const WORKING_STATUSES = new Set(["queued", "running"]);
const FAILED_STATUSES = new Set(["failed", "outcome_unknown", "needs_chat_setup"]);

function matchingAction(actions, actionType, targetId) {
  return (Array.isArray(actions) ? actions : []).find(
    (item) => item?.action_type === actionType && item?.target_id === targetId,
  );
}

export function isActionWorking(actions, actionType, targetId) {
  return WORKING_STATUSES.has(matchingAction(actions, actionType, targetId)?.status);
}

export function isActionFailed(actions, actionType, targetId) {
  return FAILED_STATUSES.has(matchingAction(actions, actionType, targetId)?.status);
}

export function exactDraftActionTerminalStatus(draft, actions) {
  if (!draft?.saving || !draft.actionId) return null;
  const exact = (Array.isArray(actions) ? actions : []).find(
    (item) => item?.action_id === draft.actionId,
  );
  if (!exact || WORKING_STATUSES.has(exact.status)) return null;
  return exact.status;
}

export function resolveLinkedPrompt(project, collection, versionId) {
  if (typeof versionId !== "string" || !versionId) return null;
  const matches = (Array.isArray(project?.[collection]) ? project[collection] : []).filter(
    (item) => item?.version_id === versionId,
  );
  return matches.length === 1 ? matches[0] : null;
}

function promptOrdinal(project, collection, prompt) {
  if (!prompt) return null;
  const siblings = (Array.isArray(project?.[collection]) ? project[collection] : []).filter(
    (item) => item?.prompt_id === prompt.prompt_id,
  );
  const index = siblings.findIndex((item) => item?.version_id === prompt.version_id);
  return index >= 0 ? index + 1 : null;
}

export function promptEditorModel({
  project,
  collection,
  versionId,
  positionId,
  label,
  ariaLabel,
  includedTags = [],
  tagItems = [],
  canEdit = false,
  canRefresh = false,
  actions = [],
}) {
  const prompt = resolveLinkedPrompt(project, collection, versionId);
  const refreshActions = (Array.isArray(actions) ? actions : []).filter(
    (item) => item?.action_type === "prompt-refresh" && item?.target_id === positionId,
  );
  return {
    positionId,
    label,
    ariaLabel: ariaLabel || label,
    collection,
    prompt,
    ordinal: promptOrdinal(project, collection, prompt),
    stale: prompt?.stale === true,
    includedTags,
    tagItems,
    canEdit: Boolean(canEdit && prompt),
    canRefresh: Boolean(canRefresh && prompt?.stale === true),
    refreshing: isActionWorking(actions, "prompt-refresh", positionId),
    refreshActions,
  };
}

function mergeDraft(key, patch) {
  setDraft(key, { ...(getDraft(key) || {}), ...patch });
}

function resolveEditorDraft(key, model, revision) {
  let draft = getDraft(key);
  if (
    draft?.requestedVersionId &&
    model.prompt?.version_id &&
    draft.requestedVersionId !== model.prompt.version_id
  ) {
    clearDraft(key);
    draft = undefined;
  } else if (
    Number.isFinite(draft?.savedRevision) &&
    Number.isFinite(revision) &&
    revision > draft.savedRevision
  ) {
    clearDraft(key);
    draft = undefined;
  }
  return {
    text: typeof draft?.text === "string" ? draft.text : model.prompt?.text || "",
    message: typeof draft?.message === "string" ? draft.message : "",
    saving: draft?.saving === true,
    savedRevision: draft?.savedRevision,
    requestedVersionId: draft?.requestedVersionId,
    lastAction: draft?.lastAction,
  };
}

function makeStatus(text = "") {
  const status = document.createElement("p");
  status.className = "prompt-editor-status";
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  status.textContent = text;
  return status;
}

export function renderPromptRefreshNotice(model, { projectId, revision, compact = false } = {}) {
  const key = draftKey(projectId, "step-plan-prompt-refresh", model?.positionId);
  let draft = getDraft(key);
  const requestedVersionChanged = Boolean(
    draft?.requestedVersionId &&
    model?.prompt?.version_id &&
    draft.requestedVersionId !== model.prompt.version_id,
  );
  if (draft && (!model?.stale || requestedVersionChanged)) {
    clearDraft(key);
    draft = undefined;
  }
  if (!model?.stale) return null;

  if (draft?.saving) {
    const terminalStatus = exactDraftActionTerminalStatus(draft, model.refreshActions);
    if (terminalStatus) {
      draft = {
        ...draft,
        saving: false,
        message: terminalStatus === "succeeded"
          ? "Промпт пока не изменился. Можно обновить ещё раз."
          : "Не удалось обновить промпт. Попробуйте ещё раз.",
      };
      setDraft(key, draft);
    }
  }

  const wrap = document.createElement("div");
  wrap.className = compact ? "prompt-stale-notice prompt-stale-notice-compact" : "prompt-stale-notice";
  const copy = document.createElement("span");
  copy.textContent = compact
    ? "Промпт устарел"
    : "Кадр, его референсы или план кадров изменились — промпт собран по прежнему набору.";
  wrap.append(copy);

  const status = makeStatus(draft?.message || "");
  if (model.canRefresh) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = model.refreshing || draft?.saving ? "Обновляется…" : "Обновить промпт";
    markControlHooks(button, model.positionId, "prompt-refresh");
    button.disabled = model.refreshing || draft?.saving === true;
    button.addEventListener("click", async () => {
      noteCardFocusPending(model.positionId, "prompt-refresh");
      status.textContent = "Агент обновляет промпт…";
      mergeDraft(key, {
        message: status.textContent,
        saving: true,
        requestedVersionId: model.prompt?.version_id,
        actionId: null,
      });
      const result = await submitAction({
        actionType: "prompt-refresh",
        targetId: model.positionId,
        payload: {},
        expectedRevision: revision,
        controls: [button],
        awaitUpdate: false,
      });
      if (result.ok) {
        status.textContent = "Запрос отправлен. Агент обновляет промпт.";
        mergeDraft(key, { message: status.textContent, saving: true, actionId: result.actionId });
        requestProjectRefresh(projectId);
      } else {
        status.textContent = resolveActionErrorMessage(result.code);
        mergeDraft(key, { message: status.textContent, saving: false, actionId: null });
        if (result.code === "revision_conflict") requestProjectRefresh(projectId);
      }
    });
    wrap.append(button);
  }
  if (model.canRefresh || status.textContent) wrap.append(status);
  return wrap;
}

export function renderPromptEditor(model, { projectId, revision }) {
  const section = document.createElement("section");
  section.className = "prompt-editor";
  section.dataset.positionId = model.positionId;

  const header = document.createElement("div");
  header.className = "prompt-editor-header";
  const title = document.createElement("span");
  title.textContent = model.label;
  header.append(title);

  if (!model.prompt) {
    const pending = document.createElement("p");
    pending.className = "prompt-editor-pending";
    pending.textContent = model.refreshing ? "Промпт пишется…" : "Промпт ещё не подготовлен.";
    section.append(header, pending);
    return section;
  }

  const key = draftKey(projectId, "step-plan-prompt", model.positionId);
  const draft = resolveEditorDraft(key, model, revision);
  const version = document.createElement("span");
  version.className = "prompt-editor-version";
  version.textContent = model.ordinal ? `v${model.ordinal}` : "";
  header.append(version);

  const textarea = document.createElement("textarea");
  textarea.className = "prompt-editor-text";
  textarea.value = draft.text;
  textarea.readOnly = !model.canEdit;
  textarea.disabled = draft.saving;
  textarea.setAttribute("aria-label", model.ariaLabel);
  if (model.canEdit) markControlHooks(textarea, model.positionId, "edit-prompt");

  const tagsSlot = document.createElement("div");
  const repaintTags = () => tagsSlot.replaceChildren(renderTagChips(textarea.value, model.tagItems));
  repaintTags();
  const status = makeStatus(draft.message);

  if (model.canEdit) {
    const append = document.createElement("button");
    append.type = "button";
    append.className = "prompt-editor-append";
    append.textContent = "Дописать пропущенные теги";
    markControlHooks(append, model.positionId, "append-missing-tags");
    append.disabled = missingTags(textarea.value, model.includedTags).length === 0 || draft.saving;
    header.append(append);

    const actions = document.createElement("div");
    actions.className = "prompt-editor-actions";
    const save = document.createElement("button");
    save.type = "button";
    save.textContent = "Сохранить";
    markControlHooks(save, model.positionId, "save-prompt");
    const reset = document.createElement("button");
    reset.type = "button";
    reset.textContent = "Сбросить";
    markControlHooks(reset, model.positionId, "reset-prompt");
    actions.append(save, reset);

    const sync = () => {
      const dirty = textarea.value !== model.prompt.text;
      actions.hidden = !dirty;
      save.disabled = draft.saving || !textarea.value.trim();
      reset.disabled = draft.saving;
      append.disabled = draft.saving || missingTags(textarea.value, model.includedTags).length === 0;
    };
    const persist = (lastAction) => {
      mergeDraft(key, { text: textarea.value, message: "", saving: false, lastAction });
      status.textContent = "";
      repaintTags();
      sync();
    };
    textarea.addEventListener("input", () => persist("edit-prompt"));
    append.addEventListener("click", () => {
      textarea.value = appendMissingTags(textarea.value, model.includedTags);
      persist("append-missing-tags");
      textarea.focus();
    });
    reset.addEventListener("click", () => {
      textarea.value = model.prompt.text;
      clearDraft(key);
      status.textContent = "";
      repaintTags();
      sync();
      textarea.focus();
    });
    save.addEventListener("click", async () => {
      if (!textarea.value.trim() || textarea.value === model.prompt.text) return;
      noteCardFocusPending(model.positionId, "edit-prompt");
      status.textContent = "Сохраняется…";
      mergeDraft(key, { text: textarea.value, message: status.textContent, saving: true, lastAction: "edit-prompt" });
      const result = await submitActionsSequentially({
        actions: [{
          actionType: "edit",
          targetId: model.prompt.version_id,
          payload: { text: textarea.value, reason: "правка в дашборде" },
        }],
        expectedRevision: revision,
        controls: [textarea, append, save, reset],
      });
      if (result.ok && result.confirmed !== false && result.completed === 1) {
        status.textContent = "Сохранено";
        mergeDraft(key, {
          text: textarea.value,
          message: status.textContent,
          saving: false,
          savedRevision: result.confirmedRevision,
          lastAction: "edit-prompt",
        });
        requestProjectRefresh(projectId);
      } else {
        status.textContent = result.ok ? OUTCOME_UNCONFIRMED_TEXT : resolveActionErrorMessage(result.code);
        mergeDraft(key, { text: textarea.value, message: status.textContent, saving: false });
        if (!result.ok && ["revision_conflict", "action_failed"].includes(result.code)) {
          requestProjectRefresh(projectId);
        }
      }
    });
    sync();
    section.append(header, textarea, tagsSlot, actions, status);
  } else {
    const actions = document.createElement("div");
    actions.className = "agent-prompt-actions";
    actions.append(
      agentControl({ label: "Изменить промпт", title: `Изменить: ${model.label}`, targetId: model.positionId, action: "edit-prompt-chat",
        prompt: `Открой ${exactTarget({ projectId, targetId: model.positionId, versionId: model.prompt.version_id, revision })}. Спроси, что изменить, сохрани обязательные теги, покажи новую версию целиком и после моего подтверждения запиши её штатной командой Creator Studio.` }),
      agentControl({ label: "Обновить по проекту", title: `Обновить: ${model.label}`, targetId: model.positionId, action: "prompt-refresh-chat",
        prompt: `Открой ${exactTarget({ projectId, targetId: model.positionId, versionId: model.prompt.version_id, revision })}. Проверь актуальные сцену, план кадров и включённые референсы, затем подготовь prompt-refresh через рабочий чат. Покажи причину обновления и новый промпт; генерацию не запускай.` }),
    );
    section.append(header, textarea, tagsSlot, actions);
  }

  const stale = renderPromptRefreshNotice(model, { projectId, revision });
  if (stale) section.append(stale);
  return section;
}
