import { promptEditorModel, renderPromptEditor } from "./prompt-editor.js";
import { resolveCardActions } from "./card-model.js";
import { buildCardActionsRow } from "./card-decorate.js";
import { prunePendingRequests } from "./paid-action-state.js";
import { markControlHooks } from "./card-forms.js";
import { hasLoadableAsset, buildAssetPlaceholder, markAssetError, createPersistentMediaPool } from "./media-asset.js";
import { agentControl, exactTarget } from "./agent-control.js";

const LAYERS = Object.freeze({
  atmos: Object.freeze({ name: "Атмосфера", coverage: "весь ролик" }),
  fx: Object.freeze({ name: "Эффекты", coverage: "по кадрам" }),
  music: Object.freeze({ name: "Музыка", coverage: "весь ролик" }),
  voice: Object.freeze({ name: "Голос", coverage: "финальный кадр" }),
});
const STATUS_LABELS = Object.freeze({
  none: "Не начат",
  working: "В работе",
  ready: "Готов, ждёт решения",
  accepted: "Принято",
});
const WAVE_HEIGHTS = Object.freeze([3, 5, 2, 6, 4, 3, 7, 2, 4, 6, 3, 5, 7, 2, 4, 6, 2, 5, 4, 3, 7, 4, 3, 6, 2, 5, 7, 3]);

function linked(records, versionId) {
  if (!versionId) return null;
  const matches = (Array.isArray(records) ? records : []).filter(
    (item) => item && (item.version_id || item.result_id) === versionId,
  );
  return matches.length === 1 ? matches[0] : null;
}

function finalSceneVoices(project) {
  const scenes = [...(project.scenes || [])].sort((left, right) => (left.order || 0) - (right.order || 0));
  const included = new Set(scenes.at(-1)?.links?.reference_ids || []);
  return (project.references || [])
    .filter((item) => included.has(item.reference_id) && item.kind === "character" && item.voice?.enabled && item.voice?.tag)
    .map((item) => ({
      tag: item.voice.tag,
      name: item.label || "Персонаж",
      hasFile: typeof item.voice.asset_url === "string" && item.voice.asset_url.startsWith("/assets/"),
    }));
}

export function audioLayerModel(snapshot, layer, { readOnly = false } = {}) {
  const meta = LAYERS[layer];
  const project = snapshot?.active_project;
  if (!meta || !project) return null;
  const owner = (project.audio_layers || []).find((item) => item?.layer === layer) || { layer, links: {} };
  const position = (project.positions || []).find((item) => item?.position_id === `pos:audio:${layer}`);
  if (!position) return null;
  const prompt = linked(project.audio_prompts, owner.links?.audio_prompt_version_id);
  const result = linked(project.audio_results, owner.links?.audio_result_id);
  const current = !readOnly && snapshot.view_stage?.current_stage === "audio";
  const allowed = current ? snapshot.view_stage?.allowed_actions || [] : [];
  const promptModel = promptEditorModel({
    project,
    collection: "audio_prompts",
    versionId: owner.links?.audio_prompt_version_id,
    positionId: position.position_id,
    label: "Описание слоя",
    ariaLabel: `Описание слоя — ${meta.name}`,
    canEdit: allowed.includes("edit"),
    canRefresh: allowed.includes("prompt-refresh"),
    actions: snapshot.actions,
  });
  const resultGroup = result?.result_id || position.result_group_id;
  const lockTargetIds = [
    position.position_id,
    ...(project.audio_results || [])
      .filter((item) => item?.result_id === resultGroup)
      .map((item) => item.version_id || item.result_id),
  ];
  let actions = result
    ? resolveCardActions(allowed, "result", result)
    : position.status === "none" && promptModel.prompt?.text?.trim() && allowed.includes("generate")
      ? ["generate"]
      : [];
  if (position.status === "accepted") {
    actions = actions.filter((action) => action !== "approve");
  }
  const voices = layer === "voice" ? finalSceneVoices(project) : [];
  return {
    layer,
    name: meta.name,
    coverage: meta.coverage,
    status: position.status,
    statusLabel: STATUS_LABELS[position.status] || "",
    position,
    prompt: promptModel,
    result,
    voices,
    needsVoiceFile: voices.some((item) => !item.hasFile),
    current,
    actions,
    allowed,
    projectId: project.id,
    revision: snapshot.revision,
    actionEntries: snapshot.actions || [],
    lockTargetIds,
  };
}

export function createAudioPlayerPool(createElement = () => document.createElement("audio")) {
  return createPersistentMediaPool(createElement);
}

const playerPool = createAudioPlayerPool();

function buildPlayer(model) {
  const wrap = document.createElement("div");
  wrap.className = "audio-player-wrap";
  if (!model.result || !hasLoadableAsset(model.result.asset_url)) {
    if (model.result) {
      const placeholder = buildAssetPlaceholder("Аудио недоступно");
      markAssetError(placeholder, model.result.asset_id);
      wrap.append(placeholder);
    }
    return wrap;
  }
  playerPool.observe();
  const descriptor = `${model.projectId}::${model.result.asset_id}::${model.result.asset_url}`;
  const audio = playerPool.acquire(model.layer, descriptor);
  audio.className = "audio-player";
  audio.controls = true;
  audio.preload = "metadata";
  markControlHooks(audio, model.position.position_id, "audio-player");
  audio.setAttribute("aria-label", `Воспроизвести слой «${model.name}»`);
  if (audio.getAttribute("src") !== model.result.asset_url) audio.setAttribute("src", model.result.asset_url);
  if (audio.__aimasterErrorHandler) audio.removeEventListener("error", audio.__aimasterErrorHandler);
  const fail = () => {
    const placeholder = buildAssetPlaceholder("Аудио недоступно");
    markAssetError(placeholder, model.result.asset_id);
    wrap.replaceChildren(placeholder);
  };
  audio.__aimasterErrorHandler = fail;
  audio.addEventListener("error", fail);
  wrap.append(audio);

  const open = document.createElement("button");
  open.type = "button";
  open.className = "audio-open-button";
  open.textContent = "Открыть аудио";
  markControlHooks(open, model.position.position_id, "open-audio");
  open.addEventListener("click", () => open.dispatchEvent(new CustomEvent("studio:open-viewer", {
    bubbles: true,
    detail: {
      kind: "audio",
      asset: {
        assetUrl: model.result.asset_url,
        assetId: model.result.asset_id,
        caption: model.result.caption || model.name,
      },
    },
  })));
  wrap.append(open);
  return wrap;
}

export function renderAudioLayerCard(model) {
  const card = document.createElement("article");
  card.className = "audio-layer-card";
  card.dataset.hook = "position-card";
  card.dataset.positionId = model.position.position_id;
  card.dataset.projectId = model.projectId;
  card.dataset.layer = model.layer;
  card.dataset.status = model.status;
  const header = document.createElement("header");
  header.className = "audio-layer-header";
  const title = document.createElement("h3");
  title.textContent = model.name;
  const chip = document.createElement("span");
  chip.className = "audio-status-chip";
  chip.dataset.status = model.status;
  chip.textContent = model.statusLabel;
  const coverage = document.createElement("span");
  coverage.className = "audio-coverage";
  coverage.textContent = model.coverage;
  header.append(title, chip, coverage);
  card.append(header, renderPromptEditor(model.prompt, { projectId: model.projectId, revision: model.revision }));
  if (model.layer === "voice") {
    const voices = document.createElement("div");
    voices.className = "audio-voices";
    const label = document.createElement("span");
    label.textContent = "Голоса из референсов:";
    voices.append(label);
    for (const voice of model.voices) {
      const item = document.createElement("span");
      item.className = "audio-voice-chip";
      item.textContent = `${voice.tag} · ${voice.name}`;
      voices.append(item);
    }
    if (model.needsVoiceFile || model.voices.length === 0) {
      const missing = document.createElement("span");
      missing.className = "audio-voice-missing";
      missing.textContent = "нужен файл голоса";
      voices.append(missing);
    }
    card.append(voices);
  }
  const wave = document.createElement("div");
  wave.className = "audio-wave";
  wave.setAttribute("aria-hidden", "true");
  for (const height of WAVE_HEIGHTS) {
    const bar = document.createElement("span");
    bar.className = `audio-wave-bar audio-wave-bar-${height}`;
    wave.append(bar);
  }
  card.append(wave, buildPlayer(model));
  const chat = document.createElement("div");
  chat.className = "agent-prompt-actions";
  chat.append(
    agentControl({ label: model.prompt?.prompt ? "Изменить описание" : "Подготовить описание", title: `${model.name}: описание`, targetId: model.position.position_id, action: "edit-audio-prompt-chat",
      prompt: `Открой ${exactTarget({ projectId: model.projectId, targetId: model.position.position_id, versionId: model.prompt?.prompt?.version_id, revision: model.revision })}. Спроси пожелания к слою «${model.name}», подготовь новое описание и покажи его до записи штатной командой Creator Studio.` }),
    agentControl({ label: model.result ? "Другой вариант" : "Создать слой", title: `${model.name}: создать`, targetId: model.position.position_id, action: "generate-audio-chat", className: "agent-prompt-button agent-prompt-button-primary",
      prompt: `Открой ${exactTarget({ projectId: model.projectId, targetId: model.position.position_id, versionId: model.prompt?.prompt?.version_id, revision: model.revision })}. Проверь точный текущий промпт, обязательные голосовые файлы и доступный в этом чате инструмент. Покажи план и дождись моего разрешения на один запуск; не угадывай модель или доступность.` }),
    agentControl({ label: model.result ? "Заменить аудиофайл" : "Загрузить аудиофайл", title: `${model.name}: ${model.result ? "заменить" : "загрузить"} файл`, targetId: model.position.position_id, action: "upload-audio-chat",
      prompt: `Открой ${exactTarget({ projectId: model.projectId, targetId: model.position.position_id, versionId: model.result?.version_id || model.result?.result_id, revision: model.revision })}. Проверь прикреплённый аудиофайл и ${model.result ? "замени текущий результат этого слоя" : "подключи его как результат этого слоя"} штатной командой Creator Studio. Не запускай генерацию.`,
      attachmentHint: "Прикрепите аудиофайл к сообщению в чате. Вложение не входит в скопированный текст." }),
  );
  if (model.result) {
    const versionId = model.result.version_id || model.result.result_id;
    chat.append(
      agentControl({ label: "Принять слой", title: `Принять: ${model.name}`, targetId: versionId, action: "approve-audio-chat",
        prompt: `Открой ${exactTarget({ projectId: model.projectId, targetId: model.position.position_id, versionId, revision: model.revision })}. Проверь соответствие результата позиции и прими именно эту версию штатной командой Creator Studio.` }),
      agentControl({ label: "Отклонить", title: `Отклонить: ${model.name}`, targetId: versionId, action: "reject-audio-chat",
        prompt: `Открой ${exactTarget({ projectId: model.projectId, targetId: model.position.position_id, versionId, revision: model.revision })}. Спроси причину и отклони именно эту версию штатной командой Creator Studio.` }),
      agentControl({ label: model.result.hidden ? "Показать" : "Скрыть", title: `${model.result.hidden ? "Показать" : "Скрыть"}: ${model.name}`, targetId: versionId, action: "toggle-audio-hidden-chat",
        prompt: `Открой ${exactTarget({ projectId: model.projectId, targetId: model.position.position_id, versionId, revision: model.revision })}. ${model.result.hidden ? "Снова покажи" : "Скрой"} именно эту версию штатной командой Creator Studio, сохранив историю.` }),
      agentControl({ label: model.result.retired ? "Вернуть в работу" : "Убрать из работы", title: `${model.result.retired ? "Вернуть" : "Убрать"}: ${model.name}`, targetId: versionId, action: "toggle-audio-retired-chat",
        prompt: `Открой ${exactTarget({ projectId: model.projectId, targetId: model.position.position_id, versionId, revision: model.revision })}. ${model.result.retired ? "Верни" : "Убери"} именно эту версию ${model.result.retired ? "в работу" : "из работы без удаления"} штатной командой Creator Studio.` }),
    );
  }
  card.append(chat);
  if (model.current) {
    prunePendingRequests(model.projectId, model.actionEntries, model.lockTargetIds);
    const row = buildCardActionsRow({
      actions: model.actions,
      record: model.result || {},
      kind: "audio-result",
      targetId: model.result?.version_id || model.result?.result_id || model.position.position_id,
      hookTargetId: model.position.position_id,
      lockTargetIds: model.lockTargetIds,
      working: model.status === "working",
      generateLabel: "Сгенерировать слой",
      expectedRevision: model.revision,
      projectId: model.projectId,
      actionEntries: model.actionEntries,
      allowedActions: model.allowed,
    });
    if (row) card.append(row);
  }
  return card;
}
