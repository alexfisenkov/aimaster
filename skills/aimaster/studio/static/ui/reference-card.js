import { resolveActionErrorMessage, submitActionsSequentially } from "./actions.js";
import { draftKey, getDraft, setDraft, clearDraft } from "./card-drafts.js";
import {
  markControlHooks,
  noteCardFocusPending,
  OUTCOME_UNCONFIRMED_TEXT,
  requestProjectRefresh,
} from "./card-forms.js";
import { isActionWorking, renderPromptRefreshNotice } from "./prompt-editor.js";
import { requestAgentPrompt } from "./chat-prompt-dialog.js";

function hook(control, targetId, action) {
  markControlHooks(control, targetId, action);
  return control;
}

function statusLine(text = "") {
  const status = document.createElement("p");
  status.className = "reference-card-status";
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  status.textContent = text;
  return status;
}

function saveDraft(key, patch) {
  setDraft(key, { ...(getDraft(key) || {}), ...patch });
}

function releaseDisappearingFocus(control) {
  if (document.activeElement === control && typeof control.blur === "function") control.blur();
}

function resolveDraft(key, model, revision) {
  let draft = getDraft(key);
  if (Number.isFinite(draft?.savedRevision) && Number.isFinite(revision) && revision > draft.savedRevision) {
    clearDraft(key);
    draft = undefined;
  }
  return {
    name: typeof draft?.name === "string" ? draft.name : model.name,
    promptText: typeof draft?.promptText === "string" ? draft.promptText : model.prompt?.text || "",
    message: draft?.message || "",
    saving: draft?.saving === true,
    savedRevision: draft?.savedRevision,
    lastEditedAction: draft?.lastEditedAction,
  };
}

function mediaPreview(model) {
  const wrap = document.createElement("div");
  wrap.className = "reference-card-preview";
  if (model.assetUrl) {
    const image = document.createElement("img");
    image.src = model.assetUrl;
    image.alt = model.name ? `Референс: ${model.name}` : `Референс ${model.tag}`;
    wrap.append(image);
  }
  const tag = document.createElement("span");
  tag.className = "reference-card-tag";
  tag.textContent = model.tag;
  const caption = document.createElement("span");
  caption.className = "reference-card-asset-caption";
  caption.textContent = model.assetCaption;
  wrap.append(tag, caption);
  return wrap;
}

function sourceControl(model, value, card, status, revision, key, draft) {
  const label = document.createElement("label");
  label.className = "reference-source-option";
  label.dataset.selected = String(model.source === value);
  const input = document.createElement("input");
  input.type = "radio";
  input.name = `source-${model.referenceId}`;
  input.value = value;
  input.checked = model.source === value;
  const text = document.createElement("span");
  text.textContent = value === "upload" ? "Загружу сам" : "Сгенерировать на шаге изображений";
  if (model.canEditReference) {
    hook(input, model.referenceId, `source-${value}`);
    input.disabled = draft.saving;
    input.addEventListener("change", async () => {
      if (!input.checked || model.source === value) return;
      noteCardFocusPending(model.referenceId, `source-${value}`);
      status.textContent = "Сохраняется…";
      saveDraft(key, { message: status.textContent, saving: true, lastEditedAction: `source-${value}` });
      const result = await submitActionsSequentially({
        actions: [{ actionType: "reference-edit", targetId: model.referenceId, payload: { field: "source", value } }],
        expectedRevision: revision,
        controls: [...card.querySelectorAll('[data-hook="card-control"]')],
      });
      if (result.ok && result.confirmed !== false && result.completed === 1) {
        status.textContent = "Сохранено";
        saveDraft(key, { message: status.textContent, saving: false, savedRevision: result.confirmedRevision, lastEditedAction: `source-${value}` });
        requestProjectRefresh(model.projectId);
      } else {
        status.textContent = result.ok ? OUTCOME_UNCONFIRMED_TEXT : resolveActionErrorMessage(result.code);
        saveDraft(key, { message: status.textContent, saving: false, lastEditedAction: `source-${value}` });
        if (!result.ok && ["revision_conflict", "action_failed"].includes(result.code)) requestProjectRefresh(model.projectId);
      }
    });
  } else {
    input.disabled = true;
  }
  label.append(input, text);
  return label;
}

export function renderReferenceCard(model, { projectId, revision }) {
  const card = document.createElement("article");
  card.className = "reference-card";
  card.dataset.referenceId = model.referenceId;
  model.projectId = projectId;
  const key = draftKey(projectId, "step-plan-reference", model.referenceId);
  const draft = resolveDraft(key, model, revision);
  card.append(mediaPreview(model));

  const name = document.createElement("input");
  name.type = "text";
  name.className = "reference-card-name";
  name.value = draft.name;
  name.readOnly = !model.canEditReference;
  name.disabled = draft.saving;
  name.setAttribute("aria-label", `Название референса ${model.tag}`);
  if (model.canEditReference) hook(name, model.referenceId, "edit-name");
  card.append(name);

  const sources = document.createElement("fieldset");
  sources.className = "reference-card-sources";
  const legend = document.createElement("legend");
  legend.className = "visually-hidden";
  legend.textContent = `Источник референса ${model.tag}`;
  const status = statusLine(draft.message);
  sources.append(
    legend,
    sourceControl(model, "upload", card, status, revision, key, draft),
    sourceControl(model, "generate", card, status, revision, key, draft),
  );
  card.append(sources);

  const membership = document.createElement("p");
  membership.className = "reference-card-membership";
  membership.textContent = `включён в ${model.includedSceneCount} из ${model.sceneCount} кадров`;
  card.append(membership);

  const chatActions = document.createElement("div");
  chatActions.className = "agent-prompt-actions";
  const sourceAction = document.createElement("button");
  sourceAction.type = "button";
  sourceAction.className = "agent-prompt-button agent-prompt-button-primary";
  sourceAction.textContent = model.assetUrl ? "Заменить референс" : "Добавить референс";
  sourceAction.addEventListener("click", () => {
    requestAgentPrompt({
      title: `${sourceAction.textContent}: ${model.name || model.tag}`,
      prompt: `Открой проект «${projectId}» и референс «${model.referenceId}» (${model.name || model.tag}). Я хочу ${model.assetUrl ? "заменить текущий референс" : "добавить референс"}. Спроси, прикреплю ли я готовый файл или нужно сначала сгенерировать вариант. Если я прикреплю файл, проверь его и покажи, куда он будет подключён. Если выберу генерацию, сначала согласуй MCP/инструмент, доступную модель, промпт и один разрешённый запуск.`,
      attachmentHint: "Если у вас уже есть референс, прикрепите его к сообщению в чате. Если нет — отправьте только текст и выберите генерацию вместе с агентом.",
    }, sourceAction);
  });
  chatActions.append(sourceAction);
  card.append(chatActions);

  if (model.voice) {
    const voice = document.createElement("label");
    voice.className = "reference-card-voice";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = model.voice.enabled;
    if (model.canEditReference) {
      hook(checkbox, model.referenceId, "voice-enabled");
      checkbox.disabled = draft.saving;
      checkbox.addEventListener("click", async () => {
        const value = !model.voice.enabled;
        noteCardFocusPending(model.referenceId, "voice-enabled");
        status.textContent = "Сохраняется…";
        saveDraft(key, { message: status.textContent, saving: true, lastEditedAction: "voice-enabled" });
        const result = await submitActionsSequentially({
          actions: [{ actionType: "reference-edit", targetId: model.referenceId, payload: { field: "voice_enabled", value } }],
          expectedRevision: revision,
          controls: [...card.querySelectorAll('[data-hook="card-control"]')],
        });
        if (result.ok && result.confirmed !== false && result.completed === 1) {
          status.textContent = "Сохранено";
          saveDraft(key, { message: status.textContent, saving: false, savedRevision: result.confirmedRevision, lastEditedAction: "voice-enabled" });
          requestProjectRefresh(projectId);
        } else {
          status.textContent = result.ok ? OUTCOME_UNCONFIRMED_TEXT : resolveActionErrorMessage(result.code);
          saveDraft(key, { message: status.textContent, saving: false, lastEditedAction: "voice-enabled" });
        }
      });
    } else {
      checkbox.disabled = true;
    }
    const text = document.createElement("span");
    text.textContent = "Референс голоса";
    voice.append(checkbox, text);
    if (model.voice.enabled) {
      const voiceState = document.createElement("span");
      voiceState.className = "reference-card-voice-state";
      voiceState.textContent = [model.voice.tag, model.voice.hasAsset ? "ваш файл" : "нужен файл"].filter(Boolean).join(" · ");
      voice.append(voiceState);
    }
    card.append(voice);
  }

  let prompt = null;
  if (model.source === "generate") {
    const promptWrap = document.createElement("div");
    promptWrap.className = "reference-card-prompt";
    const label = document.createElement("span");
    label.textContent = "Промпт референса";
    promptWrap.append(label);
    if (model.prompt) {
      prompt = document.createElement("textarea");
      prompt.value = draft.promptText;
      prompt.readOnly = !model.canEditPrompt;
      prompt.disabled = draft.saving;
      prompt.setAttribute("aria-label", `Промпт референса ${model.tag}`);
      if (model.canEditPrompt) hook(prompt, model.referenceId, "edit-prompt");
      promptWrap.append(prompt);
      const positionId = `pos:ref:${model.referenceId}`;
      const stale = renderPromptRefreshNotice(
        {
          positionId,
          prompt: model.prompt,
          stale: model.prompt.stale === true,
          canRefresh: model.canRefreshPrompt && model.prompt.stale === true,
          refreshing: isActionWorking(model.actions, "prompt-refresh", positionId),
          refreshActions: (Array.isArray(model.actions) ? model.actions : []).filter(
            (item) => item?.action_type === "prompt-refresh" && item?.target_id === positionId,
          ),
        },
        { projectId, revision, compact: true },
      );
      if (stale) promptWrap.append(stale);
    } else {
      const pending = document.createElement("p");
      pending.className = "reference-card-prompt-pending";
      pending.textContent = "Промпт ещё не подготовлен. Агент добавит его после подготовки промптов.";
      promptWrap.append(pending);
    }
    card.append(promptWrap);
  }

  if (model.canEditReference || (model.canEditPrompt && prompt)) {
    const actions = document.createElement("div");
    actions.className = "reference-card-actions";
    const save = document.createElement("button");
    save.type = "button";
    save.textContent = "Сохранить";
    hook(save, model.referenceId, "save-reference");
    const reset = document.createElement("button");
    reset.type = "button";
    reset.textContent = "Сбросить";
    hook(reset, model.referenceId, "reset-reference");
    const sync = () => {
      const dirtyName = model.canEditReference && name.value !== model.name;
      const dirtyPrompt = Boolean(model.canEditPrompt && prompt && prompt.value !== model.prompt.text);
      actions.hidden = !(dirtyName || dirtyPrompt);
      save.disabled = draft.saving || (dirtyName && !name.value.trim()) || (dirtyPrompt && !prompt.value.trim());
      reset.disabled = draft.saving;
    };
    if (model.canEditReference) {
      name.addEventListener("input", () => {
        saveDraft(key, { name: name.value, promptText: prompt?.value || draft.promptText, message: "", saving: false, lastEditedAction: "edit-name" });
        status.textContent = "";
        sync();
      });
    }
    if (model.canEditPrompt) {
      prompt?.addEventListener("input", () => {
        saveDraft(key, { name: name.value, promptText: prompt.value, message: "", saving: false, lastEditedAction: "edit-prompt" });
        status.textContent = "";
        sync();
      });
    }
    reset.addEventListener("click", () => {
      name.value = model.name;
      if (prompt) prompt.value = model.prompt.text;
      clearDraft(key);
      status.textContent = "";
      sync();
      (draft.lastEditedAction === "edit-prompt" && prompt ? prompt : name).focus();
    });
    save.addEventListener("click", async () => {
      const steps = [];
      if (model.canEditReference && name.value !== model.name) steps.push({ actionType: "reference-edit", targetId: model.referenceId, payload: { field: "name", value: name.value } });
      if (model.canEditPrompt && prompt && prompt.value !== model.prompt.text) steps.push({ actionType: "edit", targetId: model.prompt.version_id, payload: { text: prompt.value, reason: "правка в дашборде" } });
      if (steps.length === 0) return;
      const lastEditedAction = getDraft(key)?.lastEditedAction || "edit-name";
      noteCardFocusPending(model.referenceId, lastEditedAction);
      status.textContent = "Сохраняется…";
      saveDraft(key, { name: name.value, promptText: prompt?.value || "", message: status.textContent, saving: true, lastEditedAction });
      const controls = [...card.querySelectorAll('[data-hook="card-control"]')];
      const result = await submitActionsSequentially({ actions: steps, expectedRevision: revision, controls });
      if (result.ok && result.confirmed !== false && result.completed === steps.length) {
        status.textContent = "Сохранено";
        saveDraft(key, { name: name.value, promptText: prompt?.value || "", message: status.textContent, saving: false, savedRevision: result.confirmedRevision, lastEditedAction });
        releaseDisappearingFocus(save);
        requestProjectRefresh(projectId);
      } else {
        status.textContent = result.ok ? OUTCOME_UNCONFIRMED_TEXT : resolveActionErrorMessage(result.code);
        saveDraft(key, { name: name.value, promptText: prompt?.value || "", message: status.textContent, saving: false, lastEditedAction });
        if (!result.ok && ["revision_conflict", "action_failed"].includes(result.code)) requestProjectRefresh(projectId);
      }
    });
    actions.append(save, reset);
    sync();
    card.append(actions, status);
  }
  return { card, draftKey: key };
}
