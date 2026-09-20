import { promptEditorModel, renderPromptEditor } from "./prompt-editor.js";
import { promptTags, oneShotTags } from "./frame-card.js";
import { extractTags } from "./tag-chips.js";
import { resolveCardActions } from "./card-model.js";
import { buildCardActionsRow } from "./card-decorate.js";
import { prunePendingRequests } from "./paid-action-state.js";
import { buildSimpleButton, buildCommentForm, buildStatusLine, markControlHooks } from "./card-forms.js";
import { draftKey } from "./card-drafts.js";
import { formatSceneRange, hasLoadableAsset, buildAssetPlaceholder, markAssetError } from "./media-asset.js";
import { requestAgentPrompt } from "./chat-prompt-dialog.js";

const STATUS_LABELS = Object.freeze({ none: "Не начат", working: "В работе", ready: "Готов, ждёт решения", accepted: "Принято" });
const KINDS = Object.freeze({
  reference: ["image_prompts", "image_results", "image_prompt_version_id", "image_result_id", "Промпт референса", "Референс"],
  image: ["image_prompts", "image_results", "image_prompt_version_id", "image_result_id", "Промпт изображения", "Изображение"],
  first_frame: ["image_prompts", "image_results", "first_frame_prompt_version_id", "first_frame_result_id", "Промпт первого кадра", "Первый кадр"],
  last_frame: ["image_prompts", "image_results", "last_frame_prompt_version_id", "last_frame_result_id", "Промпт последнего кадра", "Последний кадр"],
  video: ["motion_prompts", "video_results", "motion_prompt_version_id", "video_result_id", "Промпт движения", "Видео"],
  oneshot: ["motion_prompts", "video_results", "motion_prompt_version_id", "video_result_id", "Промпт ролика целиком", "Весь ролик одним заходом"],
});

function linkedRecord(records, id) {
  if (!id) return null;
  const matches = (records || []).filter((item) => (item.version_id || item.result_id) === id);
  return matches.length === 1 ? matches[0] : null;
}

/** Presentation of a server position, not a second planner or status machine. */
export function positionCardModel(snapshot, position, { readOnly = false } = {}) {
  const project = snapshot?.active_project;
  const spec = KINDS[position?.kind];
  if (!project || !spec) return null;
  const [promptCollection, resultCollection, promptLink, resultLink, promptLabel, kindLabel] = spec;
  const scene = (project.scenes || []).find((item) => item.scene_id === position.scene_id);
  const reference = (project.references || []).find((item) => item.reference_id === position.tag);
  const owner = position.kind === "reference" ? reference : position.kind === "oneshot" ? project.oneshot : scene;
  const result = linkedRecord(project[resultCollection], owner?.links?.[resultLink]);
  const isVideo = position.kind === "video" || position.kind === "oneshot";
  const current = !readOnly && snapshot.view_stage?.current_stage === position.stage;
  const allowed = current ? snapshot.view_stage?.allowed_actions || [] : [];
  let tagItems = position.kind === "oneshot" ? oneShotTags(project) : promptTags(project, scene, { voice: isVideo });
  if (position.kind === "reference") {
    const prompt = (project[promptCollection] || []).find((item) => item.version_id === owner?.links?.[promptLink]);
    const used = new Set(extractTags(prompt?.text || ""));
    tagItems = (project.references || []).filter((item) => item.kind === "style" && !item.local && item.reference_id !== position.tag && used.has(item.tag))
      .map((item) => ({ tag: item.tag, label: item.label || "" }));
  }
  const title = position.kind === "oneshot" ? kindLabel : reference?.label || scene?.title || kindLabel;
  const prompt = promptEditorModel({ project, collection: promptCollection,
    versionId: owner?.links?.[promptLink], positionId: position.position_id,
    label: promptLabel, ariaLabel: `${promptLabel} — ${title}`, tagItems,
    includedTags: tagItems.map((item) => item.tag), canEdit: allowed.includes("edit"),
    canRefresh: allowed.includes("prompt-refresh"), actions: snapshot.actions });
  // Include the original generate target even after a result appears. Old
  // result versions remain real HTTP targets; never rewrite ledger identities.
  const resultGroup = result?.result_id || position.result_group_id;
  const lockTargetIds = [position.position_id, ...(project[resultCollection] || [])
    .filter((item) => item.result_id === resultGroup).map((item) => item.version_id || item.result_id)];
  const actions = result ? resolveCardActions(allowed, "result", result)
    : position.status === "none" && prompt.prompt?.text?.trim() && allowed.includes("generate") ? ["generate"] : [];
  const durationMs = position.kind === "oneshot"
    ? (project.scenes || []).reduce((sum, item) => sum + (item.duration_ms || Math.max(0, (item.end_ms || 0) - (item.start_ms || 0))), 0)
    : scene?.duration_ms || Math.max(0, (scene?.end_ms || 0) - (scene?.start_ms || 0));
  return { position, projectId: project.id, revision: snapshot.revision, scene, title, kindLabel,
    status: position.status, statusLabel: STATUS_LABELS[position.status] || "", result, prompt,
    isVideo, current, actions, allowed, lockTargetIds, actionEntries: snapshot.actions || [],
    durationLabel: isVideo && durationMs > 0 ? `${durationMs / 1000} с` : "",
    rangeLabel: project.type !== "photo" && scene && Number.isFinite(scene.start_ms) && Number.isFinite(scene.end_ms)
      ? formatSceneRange(scene.start_ms, scene.end_ms) : "" };
}

function preview(model) {
  const wrap = document.createElement("div");
  wrap.className = "position-preview";
  const unavailable = model.isVideo ? "Видео недоступно" : "Изображение недоступно";
  if (!model.result) {
    wrap.append(buildAssetPlaceholder(model.isVideo ? "Видео пока нет" : model.position.kind === "reference" ? "Референса пока нет" : "Кадра пока нет"));
    return wrap;
  }
  const broken = () => {
    const placeholder = buildAssetPlaceholder(unavailable);
    wrap.replaceChildren(placeholder);
    markAssetError(placeholder, model.result.asset_id);
  };
  if (!hasLoadableAsset(model.result.asset_url)) { broken(); return wrap; }
  const button = document.createElement("button");
  button.type = "button";
  button.className = "position-preview-button";
  markControlHooks(button, model.position.position_id, "open");
  button.setAttribute("aria-label", `Открыть ${model.isVideo ? "видео" : "изображение"}: ${model.title}`);
  const media = document.createElement(model.isVideo ? "video" : "img");
  media.src = model.result.asset_url;
  if (model.isVideo) { media.preload = "metadata"; media.muted = true; }
  else { media.alt = model.title; media.loading = "lazy"; }
  media.addEventListener("error", broken);
  button.append(media);
  button.addEventListener("click", () => button.dispatchEvent(new CustomEvent("studio:open-viewer", {
    bubbles: true, detail: { kind: model.isVideo ? "video" : "image",
      asset: { assetUrl: model.result.asset_url, assetId: model.result.asset_id, caption: model.result.caption || model.title },
      scene: model.scene },
  })));
  wrap.append(button);
  if (model.durationLabel) {
    const duration = document.createElement("span"); duration.className = "position-duration";
    duration.textContent = model.durationLabel; wrap.append(duration);
  }
  return wrap;
}

export function renderPositionCard(model, { modeControl = null } = {}) {
  const card = document.createElement("article");
  card.className = model.isVideo ? "position-card position-card-video" : "position-card";
  card.dataset.hook = "position-card";
  card.dataset.positionId = model.position.position_id;
  card.dataset.status = model.status;
  const header = document.createElement("header"); header.className = "position-card-header";
  const meta = document.createElement("div"); meta.className = "position-card-meta";
  const label = document.createElement("span"); label.className = "position-kind";
  label.textContent = model.position.tag || model.kindLabel;
  const range = document.createElement("span"); range.className = "position-range"; range.textContent = model.rangeLabel;
  const chip = document.createElement("span"); chip.className = "position-status"; chip.dataset.status = model.status;
  chip.textContent = model.statusLabel;
  meta.append(range, label, chip);
  const title = document.createElement("h3"); title.textContent = model.title;
  header.append(meta, title); card.append(header);
  const body = document.createElement("div"); body.className = "position-card-body";
  if (modeControl) body.append(modeControl);
  const content = document.createElement("div"); content.className = "position-card-content";
  content.append(renderPromptEditor(model.prompt, { projectId: model.projectId, revision: model.revision }));
  if (model.result) {
    // Existing viewer restores focus by result identity after a repaint.
    content.dataset.resultId = model.result.result_id;
    content.dataset.versionId = model.result.version_id || model.result.result_id;
  }
  content.append(preview(model));
  if (model.result?.retired || model.result?.hidden) {
    const note = document.createElement("p"); note.className = "position-material-note";
    note.textContent = model.result.retired ? "Убрано из работы" : "Скрыто"; content.append(note);
  }
  const chatActions = document.createElement("div");
  chatActions.className = "agent-prompt-actions";
  const revisePrompt = document.createElement("button");
  revisePrompt.type = "button";
  revisePrompt.className = "agent-prompt-button";
  revisePrompt.textContent = model.prompt?.prompt?.text ? "Изменить промпт" : "Подготовить промпт";
  revisePrompt.addEventListener("click", () => {
    requestAgentPrompt({
      title: `${revisePrompt.textContent}: ${model.title}`,
      prompt: `Открой проект «${model.projectId}» и позицию «${model.position.position_id}» (${model.title}). ${model.prompt?.prompt?.text ? "Предложи новую версию промпта с учётом моих правок. Сначала спроси, что именно я хочу изменить, и покажи готовый промпт до генерации." : "Подготовь подходящий промпт для этой позиции. Учти утверждённый сценарий, выбранные референсы и мои сохранённые инструкции для выбранной модели. До генерации покажи промпт мне."}`,
    }, revisePrompt);
  });
  chatActions.append(revisePrompt);

  const material = document.createElement("button");
  material.type = "button";
  material.className = "agent-prompt-button agent-prompt-button-primary";
  material.textContent = model.result ? "Другой вариант" : "Создать через агента";
  material.addEventListener("click", () => {
    requestAgentPrompt({
      title: `${material.textContent}: ${model.title}`,
      prompt: `Открой проект «${model.projectId}» и позицию «${model.position.position_id}» (${model.title}). ${model.result ? "Подготовь новую вариацию текущего результата, сохранив утверждённые референсы и общий стиль." : "Подготовь создание материала для этой позиции."} Сначала проверь выбранный в чате MCP/инструмент и доступные в нём модели, покажи используемый промпт и дождись моего разрешения на один запуск.`,
    }, material);
  });
  chatActions.append(material);

  if (model.result) {
    const replace = document.createElement("button");
    replace.type = "button";
    replace.className = "agent-prompt-button";
    replace.textContent = "Заменить исходник";
    replace.addEventListener("click", () => {
      requestAgentPrompt({
        title: `Заменить исходник: ${model.title}`,
        prompt: `В проекте «${model.projectId}» замени материал позиции «${model.position.position_id}» (${model.title}) на файл, который я прикреплю к этому сообщению. Сначала проверь файл и покажи, что именно будет заменено. Не запускай генерацию без отдельного разрешения.`,
        attachmentHint: "Прикрепите новый файл к сообщению в чате, затем вставьте скопированный текст. Дашборд сам файлы не загружает.",
      }, replace);
    });
    chatActions.append(replace);
  }
  content.append(chatActions);
  if (model.current) {
    prunePendingRequests(model.projectId, model.actionEntries, model.lockTargetIds);
    const row = buildCardActionsRow({ actions: model.actions, record: model.result || {}, kind: "position-result",
      targetId: model.result?.version_id || model.result?.result_id || model.position.position_id,
      hookTargetId: model.position.position_id, lockTargetIds: model.lockTargetIds,
      working: model.status === "working", generateLabel: model.isVideo ? "Сгенерировать видео" : "Сгенерировать",
      expectedRevision: model.revision, projectId: model.projectId, actionEntries: model.actionEntries, allowedActions: model.allowed });
    if (row) content.append(row);
  }
  body.append(content); card.append(body);
  return card;
}

export function renderPositionStageApproval(root, snapshot, stage, { readOnly = false } = {}) {
  if (readOnly || snapshot.view_stage?.current_stage !== stage) return;
  const project = snapshot.active_project;
  const readiness = project.stage_readiness?.stage === stage ? project.stage_readiness : null;
  const allowed = snapshot.view_stage?.allowed_actions || [];
  const panel = document.createElement("section"); panel.className = "position-readiness";
  panel.dataset.hook = "stage-actions";
  const copy = document.createElement("div");
  const heading = document.createElement("h3");
  heading.textContent = readiness?.can_approve ? stage === "motion" ? "Движение готово" : "Всё нужное принято" : "Проверьте результаты";
  const reason = document.createElement("p");
  const reasons = { blocked: "Продолжите в чате: шаг заблокирован.", unaccepted_positions: "Примите каждую обязательную позицию.", already_approved: "Шаг уже одобрен." };
  reason.textContent = readiness?.can_approve ? stage === "motion" ? "Дальше — атмосфера, эффекты, музыка и голос." : project.type === "photo" ? "Дальше — сборка." : "Дальше — движение." : reasons[readiness?.reason] || "Дождитесь обновления состояния шага.";
  copy.append(heading, reason);
  const controls = document.createElement("div"); controls.className = "position-stage-controls";
  const status = buildStatusLine();
  const approve = buildSimpleButton({ actionType: "approve", targetId: stage, expectedRevision: snapshot.revision,
    projectId: project.id, row: controls, status, label: stage === "motion" ? "Одобрить видео" : "Одобрить шаг", hookAction: "approve-stage" });
  approve.disabled = !readiness?.can_approve || !allowed.includes("approve"); controls.append(approve);
  if (allowed.includes("reject")) controls.append(buildCommentForm({ actionType: "reject", targetId: stage,
    expectedRevision: snapshot.revision, projectId: project.id, key: draftKey(project.id, "stage", stage),
    row: controls, status, toggleLabel: "Вернуть на доработку", focusHookAction: "reject-stage" }));
  panel.append(copy, controls, status); root.append(panel);
}
