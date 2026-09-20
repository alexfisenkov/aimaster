import { resolveActionErrorMessage, submitActionsSequentially } from "./actions.js";
import { clearDraft, draftKey, getDraft, setDraft } from "./card-drafts.js";
import {
  markControlHooks,
  noteCardFocusPending,
  OUTCOME_UNCONFIRMED_TEXT,
  requestProjectRefresh,
} from "./card-forms.js";
import { promptEditorModel, renderPromptEditor, isActionWorking } from "./prompt-editor.js";
import { resolveSceneDisplayText } from "./scenario.js";
import { resolveSceneOrder, resolveSceneRange } from "./timeline.js";
import { requestAgentPrompt } from "./chat-prompt-dialog.js";
import { exactTarget } from "./agent-control.js";
import { buildAssetPlaceholder, buildMediaDimensions, hasLoadableAsset, markAssetError } from "./media-asset.js";

const FRAME_STATUS_LABELS = Object.freeze({
  waiting: "Ждёт промпта",
  writing: "Пишется",
  ready: "Промпт готов",
  stale: "Промпт устарел",
});

export function promptTags(project, scene, { voice = false } = {}) {
  const included = new Set(Array.isArray(scene?.links?.reference_ids) ? scene.links.reference_ids : []);
  const items = [];
  for (const reference of Array.isArray(project?.references) ? project.references : []) {
    if (!included.has(reference?.reference_id) || typeof reference?.tag !== "string") continue;
    if (reference.kind === "video" && !voice) continue;
    items.push({ tag: reference.tag, label: reference.label || "" });
    if (
      voice &&
      reference.kind === "character" &&
      reference.voice?.enabled === true &&
      typeof reference.voice?.tag === "string" &&
      typeof reference.voice?.asset_url === "string" &&
      reference.voice.asset_url
    ) {
      items.push({ tag: reference.voice.tag, label: `${reference.label || "Персонаж"} · голос` });
    }
  }
  return items;
}

export function oneShotTags(project) {
  const items = [];
  const seen = new Set();
  const scenes = [...(Array.isArray(project?.scenes) ? project.scenes : [])].sort(
    (left, right) => (left?.order || 0) - (right?.order || 0),
  );
  for (const scene of scenes) {
    for (const item of promptTags(project, scene, { voice: true })) {
      if (!seen.has(item.tag)) {
        seen.add(item.tag);
        items.push(item);
      }
    }
  }
  return items;
}

function promptModel(project, actions, permissions, spec) {
  return promptEditorModel({
    project,
    actions,
    canEdit: permissions.canEditPrompt,
    canRefresh: permissions.canRefreshPrompt,
    includedTags: spec.tagItems.map((item) => item.tag),
    tagItems: spec.tagItems,
    ...spec,
  });
}

function frameStatus(prompts, globalBusy) {
  if (globalBusy || prompts.some((item) => item.refreshing)) return "writing";
  if (prompts.some((item) => item.stale)) return "stale";
  if (prompts.length > 0 && prompts.every((item) => item.prompt && item.prompt.text.trim())) return "ready";
  return "waiting";
}

function permissions(snapshot, readOnly) {
  const current = !readOnly && snapshot?.view_stage?.current_stage === "image_plan";
  const allowed = new Set(Array.isArray(snapshot?.view_stage?.allowed_actions) ? snapshot.view_stage.allowed_actions : []);
  return {
    canToggleReference: current && allowed.has("scene-reference-toggle"),
    canFramePlan: current && allowed.has("scene-frame-plan"),
    canAddLocal: current && allowed.has("reference-add"),
    canEditPrompt: current && allowed.has("edit"),
    canRefreshPrompt: current && allowed.has("prompt-refresh"),
  };
}

export function frameCardsModel(snapshot, { readOnly = false } = {}) {
  const project = snapshot?.active_project;
  if (!project) return { cards: [], oneShotPrompt: null, globalBusy: false };
  const actions = Array.isArray(snapshot.actions) ? snapshot.actions : [];
  const rights = permissions(snapshot, readOnly);
  const projectReferences = (Array.isArray(project.references) ? project.references : []).filter(
    (item) => item?.local !== true,
  );
  const localReferences = (Array.isArray(project.references) ? project.references : []).filter(
    (item) => item?.local === true,
  );
  const globalBusy = isActionWorking(actions, "prompts-generate", "project");
  const isPhoto = project.type === "photo";
  const oneShot = !isPhoto && project.gen_mode === "one_shot";
  const sharedTags = oneShotTags(project);
  const oneShotPrompt = oneShot
    ? promptModel(project, actions, rights, {
        collection: "motion_prompts",
        versionId: project.oneshot?.links?.motion_prompt_version_id,
        positionId: "pos:oneshot",
        label: "Промпт ролика целиком",
        ariaLabel: "Промпт ролика целиком",
        tagItems: sharedTags,
      })
    : null;

  const cards = [...(Array.isArray(project.scenes) ? project.scenes : [])]
    .sort((left, right) => (left?.order || 0) - (right?.order || 0))
    .map((scene, position) => {
      const sceneId = scene?.scene_id || "";
      const range = resolveSceneRange(scene);
      const sceneOrder = resolveSceneOrder(scene, position);
      const staticTags = promptTags(project, scene);
      const motionTags = promptTags(project, scene, { voice: true });
      const prompts = [];
      if (isPhoto) {
        prompts.push(
          promptModel(project, actions, rights, {
            collection: "image_prompts",
            versionId: scene?.links?.image_prompt_version_id,
            positionId: `pos:scene:${sceneId}:image`,
            label: "Промпт изображения",
            ariaLabel: `Промпт изображения — Кадр ${sceneOrder}`,
            tagItems: staticTags,
          }),
        );
      } else {
        if (scene.need_first === true) {
          prompts.push(
            promptModel(project, actions, rights, {
              collection: "image_prompts",
              versionId: scene?.links?.first_frame_prompt_version_id,
              positionId: `pos:frame:${sceneId}:first`,
              label: "Промпт первого кадра",
              ariaLabel: `Промпт первого кадра — Кадр ${sceneOrder}`,
              tagItems: staticTags,
            }),
          );
        }
        if (scene.need_last === true) {
          prompts.push(
            promptModel(project, actions, rights, {
              collection: "image_prompts",
              versionId: scene?.links?.last_frame_prompt_version_id,
              positionId: `pos:frame:${sceneId}:last`,
              label: "Промпт последнего кадра",
              ariaLabel: `Промпт последнего кадра — Кадр ${sceneOrder}`,
              tagItems: staticTags,
            }),
          );
        }
        if (!oneShot) {
          prompts.push(
            promptModel(project, actions, rights, {
              collection: "motion_prompts",
              versionId: scene?.links?.motion_prompt_version_id,
              positionId: `pos:scene:${sceneId}:video`,
              label: "Промпт кадра",
              ariaLabel: `Промпт кадра — Кадр ${sceneOrder}`,
              tagItems: motionTags,
            }),
          );
        }
      }
      const includedIds = new Set(Array.isArray(scene?.links?.reference_ids) ? scene.links.reference_ids : []);
      const statusPrompts = oneShotPrompt ? [...prompts, oneShotPrompt] : prompts;
      return {
        sceneId,
        order: sceneOrder,
        rangeLabel: range.hasRange ? range.rangeLabel : "",
        title: typeof scene?.title === "string" ? scene.title : "",
        text: resolveSceneDisplayText(scene),
        referenceChoices: projectReferences.map((reference) => ({
          referenceId: reference.reference_id,
          tag: reference.tag,
          label: reference.label || "",
          included: includedIds.has(reference.reference_id),
          voiceTag:
            reference.kind === "character" &&
            reference.voice?.enabled === true &&
            typeof reference.voice?.asset_url === "string"
              ? reference.voice.tag || ""
              : "",
          canToggle: rights.canToggleReference,
        })),
        referenceCountLabel: `${projectReferences.filter((item) => includedIds.has(item.reference_id)).length} из ${projectReferences.length}`,
        localReferences: localReferences
          .filter((reference) => reference.scene_id === sceneId && includedIds.has(reference.reference_id))
          .map((reference) => ({
            referenceId: reference.reference_id,
            assetId: typeof reference.asset_id === "string" ? reference.asset_id : null,
            tag: reference.tag,
            label: reference.label || "",
            assetUrl: typeof (reference.playable_asset_url || reference.asset_url) === "string" ? (reference.playable_asset_url || reference.asset_url) : null,
            kind: reference.kind,
            mediaType: reference.media_type,
            usage: reference.usage || "reference",
          })),
        framePlan: isPhoto
          ? null
          : {
              needFirst: scene.need_first === true,
              needLast: scene.need_last === true,
              canEdit: rights.canFramePlan,
            },
        prompts,
        status: frameStatus(statusPrompts, globalBusy),
        statusLabel: FRAME_STATUS_LABELS[frameStatus(statusPrompts, globalBusy)],
        canAddLocal: rights.canAddLocal,
        readOnly,
        projectType: project.type,
        projectId: project.id,
        revision: snapshot.revision,
      };
    });
  return { cards, oneShotPrompt, globalBusy, permissions: rights };
}

function mergeDraft(key, patch) {
  setDraft(key, { ...(getDraft(key) || {}), ...patch });
}

function actionStatus(text = "") {
  const status = document.createElement("p");
  status.className = "frame-card-status";
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  status.textContent = text;
  return status;
}

async function submitFrameDecision({ card, model, key, hookTarget, hookAction, wireAction, wireTarget, payload, status }) {
  noteCardFocusPending(hookTarget, hookAction);
  status.textContent = "Сохраняется…";
  mergeDraft(key, { message: status.textContent, saving: true, lastAction: hookAction });
  const controls = [...card.querySelectorAll('[data-hook="card-control"]')];
  const result = await submitActionsSequentially({
    actions: [{ actionType: wireAction, targetId: wireTarget, payload }],
    expectedRevision: model.revision,
    controls,
  });
  if (result.ok && result.confirmed !== false && result.completed === 1) {
    status.textContent = "Сохранено";
    mergeDraft(key, {
      message: status.textContent,
      saving: false,
      savedRevision: result.confirmedRevision,
      lastAction: hookAction,
    });
    requestProjectRefresh(model.projectId);
  } else {
    status.textContent = result.ok ? OUTCOME_UNCONFIRMED_TEXT : resolveActionErrorMessage(result.code);
    mergeDraft(key, { message: status.textContent, saving: false, lastAction: hookAction });
    if (!result.ok && ["revision_conflict", "action_failed"].includes(result.code)) {
      requestProjectRefresh(model.projectId);
    }
  }
}

function choiceButton(card, model, choice, status, key) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "frame-reference-choice";
  button.dataset.selected = String(choice.included);
  button.setAttribute("aria-pressed", String(choice.included));
  const mark = document.createElement("span");
  mark.className = "frame-choice-mark";
  mark.textContent = choice.included ? "✓" : "";
  const tag = document.createElement("span");
  tag.className = "frame-choice-tag";
  tag.textContent = choice.tag;
  const label = document.createElement("span");
  label.className = "frame-choice-name";
  label.textContent = choice.label;
  button.append(mark, tag, label);
  if (choice.voiceTag && choice.included) {
    const voice = document.createElement("span");
    voice.className = "frame-choice-voice";
    voice.textContent = choice.voiceTag;
    button.append(voice);
  }
  if (choice.canToggle) {
    const hookTarget = `${model.sceneId}::${choice.referenceId}`;
    markControlHooks(button, hookTarget, "toggle-reference");
    button.addEventListener("click", () =>
      submitFrameDecision({
        card,
        model,
        key,
        hookTarget,
        hookAction: "toggle-reference",
        wireAction: "scene-reference-toggle",
        wireTarget: choice.referenceId,
        payload: { scene_id: model.sceneId, on: !choice.included },
        status,
      }),
    );
  } else {
    button.addEventListener("click", () => requestAgentPrompt({
      title: `${choice.included ? "Убрать" : "Добавить"} референс ${choice.tag}`,
      prompt: `Открой ${exactTarget({ projectId: model.projectId, targetId: model.sceneId, revision: model.revision })}. ${choice.included ? "Убери" : "Добавь"} reference_id «${choice.referenceId}» (${choice.tag}) в референсы этой сцены штатной командой Creator Studio. Покажи влияние на промпты и попроси подтверждение перед изменением.`,
    }, button));
  }
  return button;
}

function planButton(card, model, edge, selected, status, key) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "frame-plan-choice";
  button.dataset.selected = String(selected);
  button.setAttribute("aria-pressed", String(selected));
  const mark = document.createElement("span");
  mark.className = "frame-plan-choice-mark";
  mark.textContent = selected ? "✓" : "";
  const text = document.createElement("span");
  text.textContent = edge === "first" ? "Первый кадр" : "Последний кадр";
  button.append(mark, text);
  if (model.framePlan.canEdit) {
    const hookAction = edge === "first" ? "toggle-first" : "toggle-last";
    markControlHooks(button, model.sceneId, hookAction);
    button.addEventListener("click", () =>
      submitFrameDecision({
        card,
        model,
        key,
        hookTarget: model.sceneId,
        hookAction,
        wireAction: "scene-frame-plan",
        wireTarget: model.sceneId,
        payload: { [edge]: !selected },
        status,
      }),
    );
  } else {
    button.addEventListener("click", () => requestAgentPrompt({
      title: `${selected ? "Убрать" : "Добавить"} ${edge === "first" ? "первый" : "последний"} кадр`,
      prompt: `Открой ${exactTarget({ projectId: model.projectId, targetId: model.sceneId, revision: model.revision })}. Установи ${edge}=${!selected} в плане кадров штатной командой Creator Studio. Покажи, какие позиции и промпты изменятся, и попроси подтверждение; ничего не генерируй.`,
    }, button));
  }
  return button;
}

function renderLocalReferences(card, model, status, key) {
  const section = document.createElement("section");
  section.className = "frame-local-references";
  const heading = document.createElement("div");
  heading.className = "frame-subheading";
  heading.textContent = "Только этот кадр";
  const hint = document.createElement("p");
  hint.textContent = "Разовые детали. Файл передайте агенту в чате, назвав его тег.";
  const items = document.createElement("div");
  items.className = "frame-local-grid";
  for (const reference of model.localReferences) {
    const item = document.createElement("div");
    item.className = "frame-local-reference";
    const preview = document.createElement("div");
    preview.className = "frame-local-preview";
    if (hasLoadableAsset(reference.assetUrl)) {
      const isVideo = reference.kind === "video" || reference.mediaType === "video";
      const media = document.createElement(isVideo ? "video" : "img");
      media.src = reference.assetUrl;
      if (isVideo) { media.controls = true; media.preload = "metadata"; }
      else media.alt = reference.label ? `Разовый референс: ${reference.label}` : "Разовый референс";
      const dimensions = buildMediaDimensions(media);
      let imageButton = null;
      if (!isVideo) {
        imageButton = document.createElement("button");
        imageButton.type = "button";
        imageButton.className = "frame-local-preview-button";
        imageButton.setAttribute("aria-label", `Открыть локальный референс: ${reference.label || reference.tag}`);
        imageButton.append(media);
        imageButton.addEventListener("click", () => imageButton.dispatchEvent(new CustomEvent("studio:open-viewer", {
          bubbles: true,
          detail: { kind: "image", asset: { assetUrl: reference.assetUrl, assetId: reference.assetId, caption: reference.label || reference.tag } },
        })));
      }
      media.addEventListener("error", () => {
        const placeholder = buildAssetPlaceholder(isVideo ? "Видеореференс недоступен" : "Референс недоступен");
        media.replaceWith(placeholder);
        if (imageButton) imageButton.disabled = true;
        dimensions.remove();
        markAssetError(placeholder, reference.assetId || reference.referenceId);
      });
      preview.append(imageButton || media, dimensions);
    } else {
      const placeholder = buildAssetPlaceholder("Референс недоступен");
      markAssetError(placeholder, reference.assetId || reference.referenceId);
      preview.append(placeholder);
    }
    const tag = document.createElement("span");
    tag.textContent = reference.tag;
    preview.append(tag);
    const label = document.createElement("span");
    label.className = "frame-local-label";
    label.textContent = reference.label;
    const edit = document.createElement("button");
    edit.type = "button";
    edit.className = "agent-prompt-button";
    edit.textContent = "Изменить";
    edit.addEventListener("click", () => requestAgentPrompt({
      title: `Изменить локальный референс ${reference.tag}`,
      prompt: `Открой ${exactTarget({ projectId: model.projectId, targetId: reference.referenceId, revision: model.revision })}. Это локальный референс сцены «${model.sceneId}»${reference.kind === "video" ? `, kind video, текущее usage ${reference.usage}` : ""}. Спроси, нужно ли изменить название, файл${reference.kind === "video" ? " или usage (reference, motion, continue, edit)" : ""}; покажи точную правку и попроси подтверждение перед штатной командой Creator Studio.`,
      attachmentHint: "Если меняется файл, прикрепите его к сообщению в чате. Вложение не входит в скопированный текст.",
    }, edit));
    item.append(preview, label, edit);
    items.append(item);
  }
  if (model.canAddLocal || model.readOnly) {
    const add = document.createElement("button");
    add.type = "button";
    add.className = "frame-local-add";
    add.textContent = "+ Добавить";
    markControlHooks(add, model.sceneId, "add-local-reference");
    add.addEventListener("click", () => {
      if (model.readOnly) {
        requestAgentPrompt({ title: `Добавить референс только для кадра ${model.order}`,
          prompt: `Открой ${exactTarget({ projectId: model.projectId, targetId: model.sceneId, revision: model.revision })}. Добавь локальный ${model.projectType === "photo" ? "референс-изображение" : "референс"} только для этой сцены из файла, который я прикреплю. Сначала проверь файл, предложи label и тег, покажи изменение и попроси подтверждение.${model.projectType === "photo" ? " Видеореференсы для photo-проекта не поддерживаются: если приложено видео, предложи извлечь подходящий стоп-кадр только с моего разрешения, затем подключить изображение." : ""}`,
          attachmentHint: model.projectType === "photo" ? "Прикрепите изображение. Если приложено видео, агент сначала запросит разрешение на извлечение стоп-кадра." : "Прикрепите файл к сообщению в чате. Вложение не входит в скопированный текст." }, add);
        return;
      }
      submitFrameDecision({
        card,
        model,
        key,
        hookTarget: model.sceneId,
        hookAction: "add-local-reference",
        wireAction: "reference-add",
        wireTarget: "references",
        payload: {
          kind: "product",
          name: "Разовый референс",
          source: "upload",
          scene_id: model.sceneId,
        },
        status,
      });
    });
    items.append(add);
  }
  section.append(heading, hint, items);
  return section;
}

export function renderFrameCard(model) {
  const row = document.createElement("div");
  row.className = "frame-card-row";
  row.dataset.sceneId = model.sceneId;
  const rail = document.createElement("div");
  rail.className = "frame-card-rail";
  const number = document.createElement("span");
  number.className = "frame-card-number";
  number.textContent = String(model.order);
  const range = document.createElement("span");
  range.className = "frame-card-range";
  range.textContent = model.rangeLabel;
  const line = document.createElement("span");
  line.className = "frame-card-line";
  rail.append(number, range, line);

  const card = document.createElement("article");
  card.className = "frame-card";
  card.dataset.status = model.status;
  const key = draftKey(model.projectId, "step-plan-frame", model.sceneId);
  let draft = getDraft(key);
  if (Number.isFinite(draft?.savedRevision) && model.revision > draft.savedRevision) {
    clearDraft(key);
    draft = undefined;
  }
  const status = actionStatus(draft?.message || "");

  const header = document.createElement("div");
  header.className = "frame-card-header";
  const title = document.createElement("h3");
  title.textContent = model.title;
  const chip = document.createElement("span");
  chip.className = "frame-status-chip";
  chip.dataset.status = model.status;
  chip.textContent = model.statusLabel;
  header.append(title, chip);
  const description = document.createElement("p");
  description.className = "frame-card-description";
  description.textContent = model.text;
  card.append(header, description);

  const refs = document.createElement("section");
  refs.className = "frame-card-references";
  const refsHeading = document.createElement("div");
  refsHeading.className = "frame-subheading";
  refsHeading.textContent = "Референсы проекта в этом кадре";
  const count = document.createElement("span");
  count.className = "frame-reference-count";
  count.textContent = `${model.referenceCountLabel} — снятые не уйдут в генерацию этого кадра`;
  const choices = document.createElement("div");
  choices.className = "frame-reference-choices";
  for (const choice of model.referenceChoices) choices.append(choiceButton(card, model, choice, status, key));
  refs.append(refsHeading, count, choices);
  card.append(refs);

  if (model.framePlan) {
    const plan = document.createElement("section");
    plan.className = "frame-plan";
    const planHeading = document.createElement("div");
    planHeading.className = "frame-subheading";
    planHeading.textContent = "Что генерируем по этому кадру";
    const hint = document.createElement("p");
    hint.textContent = model.framePlan.needFirst || model.framePlan.needLast
      ? "Отмеченные кадры появятся на шаге «Изображения» — каждому нужен свой промпт."
      : "Ничего не отмечено: на шаге «Изображения» этот кадр не появится, движение соберётся сразу по референсам.";
    const buttons = document.createElement("div");
    buttons.className = "frame-plan-choices";
    buttons.append(
      planButton(card, model, "first", model.framePlan.needFirst, status, key),
      planButton(card, model, "last", model.framePlan.needLast, status, key),
    );
    plan.append(planHeading, hint, buttons);
    for (const prompt of model.prompts.filter((item) => item.positionId.includes(":frame:"))) {
      plan.append(renderPromptEditor(prompt, { projectId: model.projectId, revision: model.revision }));
    }
    card.append(plan);
  }

  card.append(renderLocalReferences(card, model, status, key));
  for (const prompt of model.prompts.filter((item) => !item.positionId.includes(":frame:"))) {
    card.append(renderPromptEditor(prompt, { projectId: model.projectId, revision: model.revision }));
  }
  if (status.textContent || model.referenceChoices.some((item) => item.canToggle) || model.framePlan?.canEdit || model.canAddLocal) {
    card.append(status);
  }
  if (draft?.saving) {
    for (const control of card.querySelectorAll('[data-hook="card-control"]')) control.disabled = true;
  }
  row.append(rail, card);
  return row;
}

export function renderOneShotPrompt(model, { projectId, revision }) {
  if (!model) return null;
  const section = document.createElement("section");
  section.className = "plan-section one-shot-prompt";
  const heading = document.createElement("h2");
  heading.textContent = "Весь ролик одним заходом";
  const description = document.createElement("p");
  description.className = "plan-section-description";
  description.textContent = "Один промпт с посекундной разбивкой заменяет отдельные промпты движения кадров.";
  section.append(heading, description, renderPromptEditor(model, { projectId, revision }));
  return section;
}
