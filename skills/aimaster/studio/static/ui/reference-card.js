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
import { buildAssetPlaceholder, buildMediaDimensions, markAssetError } from "./media-asset.js";

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
  const previewUrl = model.playableAssetUrl || model.assetUrl;
  if (previewUrl) {
    const media = document.createElement(model.kind === "video" ? "video" : "img");
    media.src = previewUrl;
    if (model.kind === "video") { media.controls = true; media.preload = "metadata"; }
    else media.alt = model.name ? `Референс: ${model.name}` : `Референс ${model.tag}`;
    const dimensions = buildMediaDimensions(media);
    let imageButton = null;
    if (model.kind !== "video") {
      imageButton = document.createElement("button");
      imageButton.type = "button";
      imageButton.className = "reference-card-preview-button";
      imageButton.setAttribute("aria-label", `Открыть референс: ${model.name || model.tag}`);
      imageButton.append(media);
      imageButton.addEventListener("click", () => imageButton.dispatchEvent(new CustomEvent("studio:open-viewer", {
        bubbles: true,
        detail: { kind: "image", asset: { assetUrl: previewUrl, assetId: model.assetId, caption: model.name || model.tag } },
      })));
    }
    media.addEventListener("error", () => {
      const message = model.kind === "video" ? "Видеореференс недоступен" : "Референс недоступен";
      const placeholder = buildAssetPlaceholder(message);
      media.replaceWith(placeholder);
      if (imageButton) imageButton.disabled = true;
      dimensions.remove();
      markAssetError(placeholder, model.assetId || model.referenceId);
    });
    wrap.append(imageButton || media, dimensions);
    if (model.kind === "video") {
      const open = document.createElement("button");
      open.type = "button";
      open.className = "agent-prompt-button";
      open.dataset.action = "open";
      open.textContent = "Открыть видео";
      open.addEventListener("click", () => open.dispatchEvent(new CustomEvent("studio:open-viewer", {
        bubbles: true,
        detail: { kind: "video", asset: { assetUrl: previewUrl, assetId: model.referenceId, caption: model.name || model.tag } },
      })));
      wrap.append(open);
    }
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

function agentButton(label, className, detail) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = className;
  button.textContent = label;
  button.addEventListener("click", () => requestAgentPrompt(detail(), button));
  return button;
}

function renderReadOnlySource(model, projectId) {
  const wrap = document.createElement("div");
  wrap.className = "reference-card-source-status";
  const label = document.createElement("span");
  label.textContent = "Источник";
  const value = document.createElement("strong");
  value.textContent = model.sourceLabel;
  wrap.append(label, value);

  const actions = document.createElement("div");
  actions.className = "agent-prompt-actions reference-card-agent-actions";
  const identity = `проект «${projectId}», референс «${model.referenceId}» (${model.name || model.tag})`;
  actions.append(agentButton(
    model.hasAsset ? "Заменить файл" : "Загрузить файл",
    "agent-prompt-button agent-prompt-button-primary",
    () => ({
      title: `${model.hasAsset ? "Заменить" : "Загрузить"} референс: ${model.name || model.tag}`,
      prompt: `Открой ${identity}. ${model.hasAsset ? "Замени текущий файл референса" : "Добавь файл референса"} на файл, который я прикреплю к этому сообщению. Используй существующий reference_id «${model.referenceId}», не создавай дубликат. Сначала проверь вложение, затем зарегистрируй и прикрепи его штатными командами Creator Studio. Прямое attach должно установить source=upload; после записи проверь asset_id, source и отсутствие pos:ref:${model.referenceId}. Не запускай и не предлагай генерацию этого материала без моей отдельной просьбы о варианте.`,
      attachmentHint: model.kind === "video" ? "Прикрепите видео к сообщению в чате. Вложение не входит в скопированный текст." : "Прикрепите изображение к сообщению в чате. Вложение не входит в скопированный текст.",
    }),
  ));
  if (model.kind !== "video") actions.append(agentButton(
    model.hasAsset ? "Сгенерировать замену" : "Сгенерировать",
    "agent-prompt-button",
    () => ({
      title: `Сгенерировать референс: ${model.name || model.tag}`,
      prompt: `Открой ${identity}. Подготовь ${model.hasAsset ? "замену текущего референса" : "новый референс"} через генерацию. Сначала подтверди exact target и его required stage. Если сейчас image_plan, только подготовь reference, model-specific guide и prompt; не вызывай provider, пока image_results не станет текущей стадией. На image_results заново проверь target/revision, согласуй инструмент, совместимую модель, prompt и один запуск. После результата немедленно выполни canonical collection и покажи его в дашборде.`,
    }),
  ));
  if (model.kind === "video") actions.append(agentButton("Изменить назначение", "agent-prompt-button", () => ({
    title: `Назначение видеореференса: ${model.name || model.tag}`,
    prompt: `Открой ${identity}. Текущее usage: ${model.usage}. Спроси, какое назначение выбрать: reference, motion, continue или edit, объясни разницу и после моего подтверждения измени поле usage штатной командой Creator Studio.`,
  })));
  return { wrap, actions };
}

function renderReadOnlyVoice(model, projectId) {
  const section = document.createElement("div");
  section.className = "reference-card-voice reference-card-voice-readonly";
  const label = document.createElement("span");
  label.textContent = "Голос";
  const state = document.createElement("strong");
  state.textContent = model.voice.enabled
    ? [model.voice.tag, model.voice.hasAsset ? "файл подключён" : "нужен файл"].filter(Boolean).join(" · ")
    : "не используется";
  section.append(label, state);
  const actions = document.createElement("div");
  actions.className = "agent-prompt-actions reference-card-agent-actions";
  const identity = `проект «${projectId}», референс персонажа «${model.referenceId}» (${model.name || model.tag})`;
  if (model.voice.enabled) {
    actions.append(agentButton(model.voice.hasAsset ? "Заменить голос" : "Добавить голос", "agent-prompt-button agent-prompt-button-primary", () => ({
      title: `${model.voice.hasAsset ? "Заменить" : "Добавить"} голос: ${model.name || model.tag}`,
      prompt: `Открой ${identity}. ${model.voice.hasAsset ? "Замени файл голосового референса" : "Добавь голосовой референс"} файлом, который я прикреплю. Подтверди точные project_id «${projectId}» и reference_id «${model.referenceId}», проверь формат и содержимое файла, покажи, что изменится, и только затем подключи его.`,
      attachmentHint: "Прикрепите MP3 или WAV к сообщению в чате. Вложение не входит в скопированный текст.",
    })));
    actions.append(agentButton("Не использовать голос", "agent-prompt-button", () => ({
      title: `Не использовать голос: ${model.name || model.tag}`,
      prompt: `Открой ${identity}. Отключи использование голосового референса штатной командой reference edit с voice_enabled=false. Сохрани файл и историю, не редактируй state.json вручную. Проверь актуальный этап и ревизию, затем сообщи результат.`,
    })));
  } else {
    actions.append(agentButton("Добавить голос", "agent-prompt-button agent-prompt-button-primary", () => ({
      title: `Добавить голос: ${model.name || model.tag}`,
      prompt: `Открой ${identity}. Включи голосовой референс и подключи MP3 или WAV, который я прикреплю. Сначала подтверди точные project_id «${projectId}» и reference_id «${model.referenceId}», проверь файл и покажи, что изменится.`,
      attachmentHint: "Прикрепите MP3 или WAV к сообщению в чате. Вложение не входит в скопированный текст.",
    })));
  }
  section.append(actions);
  return section;
}

export function renderReferenceCard(model, { projectId, revision }) {
  const card = document.createElement("article");
  card.className = "reference-card";
  card.dataset.referenceId = model.referenceId;
  model.projectId = projectId;
  const key = draftKey(projectId, "step-plan-reference", model.referenceId);
  const draft = resolveDraft(key, model, revision);
  card.append(mediaPreview(model));

  const name = model.readOnly ? document.createElement("h4") : document.createElement("input");
  name.className = model.readOnly ? "reference-card-title" : "reference-card-name";
  if (model.readOnly) {
    name.textContent = draft.name || model.tag;
  } else {
    name.type = "text";
    name.value = draft.name;
    name.readOnly = !model.canEditReference;
    name.disabled = draft.saving;
    name.setAttribute("aria-label", `Название референса ${model.tag}`);
    if (model.canEditReference) hook(name, model.referenceId, "edit-name");
  }
  card.append(name);

  const status = statusLine(draft.message);
  const sources = document.createElement("fieldset");
  sources.className = "reference-card-sources";
  const legend = document.createElement("legend");
  legend.className = "visually-hidden";
  legend.textContent = `Источник референса ${model.tag}`;
  sources.append(
    legend,
    sourceControl(model, "upload", card, status, revision, key, draft),
    sourceControl(model, "generate", card, status, revision, key, draft),
  );
  if (model.readOnly) {
    const readOnlySource = renderReadOnlySource(model, projectId);
    card.append(readOnlySource.wrap, readOnlySource.actions);
  } else {
    card.append(sources);
  }

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
  if (!model.readOnly) card.append(chatActions);

  if (model.voice && model.readOnly) {
    card.append(renderReadOnlyVoice(model, projectId));
  } else if (model.voice) {
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
