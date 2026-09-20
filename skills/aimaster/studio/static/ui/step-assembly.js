import { assemblyStripModel, formatAssemblyTime } from "./assembly-strip.js";
import { buildSimpleButton, buildStatusLine, markControlHooks } from "./card-forms.js";
import { renderStageActions, renderChatStageActions } from "./stage-approval.js";
import { agentControl, exactTarget } from "./agent-control.js";
import { hasLoadableAsset, buildAssetPlaceholder, markAssetError, createPersistentMediaPool } from "./media-asset.js";

const finalVideoPool = createPersistentMediaPool(() => document.createElement("video"));
const SVG_NS = "http://www.w3.org/2000/svg";
const XHTML_NS = "http://www.w3.org/1999/xhtml";

function svgElement(name, className = "") {
  const node = document.createElementNS(SVG_NS, name);
  if (className) node.setAttribute("class", className);
  return node;
}

function percentWidth(durationMs, totalMs, blockCount) {
  const value = totalMs > 0 ? (durationMs / totalMs) * 100 : 100 / Math.max(1, blockCount);
  const compact = Number.isInteger(value) ? String(value) : value.toFixed(6).replace(/0+$/, "").replace(/\.$/, "");
  return `${compact}%`;
}

const ASSEMBLY_ACTION_LABELS = Object.freeze({
  queued: "Отправлено, ждём ответа в чате",
  running: "Собираем финал в чате",
  failed: "Не удалось собрать финал",
  needs_chat: "Продолжите сборку в чате",
  needs_chat_setup: "Нужна настройка в чате",
  outcome_unknown: "Исход нужно проверить в чате",
  succeeded: "Ответ получен",
});

function actionFor(snapshot) {
  return (snapshot?.actions || []).find(
    (item) => item?.action_type === "assemble" && item?.target_id === "final",
  ) || null;
}

function acceptedPhotoImages(project) {
  const positions = (project.positions || []).filter(
    (item) => item.kind === "image" && item.stage === "image_results" && item.status === "accepted",
  );
  return positions.map((position) => {
    const scene = (project.scenes || []).find((item) => item.scene_id === position.scene_id);
    const versionId = scene?.links?.image_result_id;
    const matches = (project.image_results || []).filter(
      (item) => item && (item.version_id || item.result_id) === versionId,
    );
    const result = matches.length === 1 ? matches[0] : null;
    return result ? {
      sceneId: scene.scene_id,
      title: scene.title || "Изображение",
      assetId: result.asset_id,
      assetUrl: result.asset_url,
      caption: result.caption || scene.title || "Изображение",
    } : null;
  }).filter(Boolean);
}

export function assemblyStepModel(snapshot) {
  const project = snapshot?.active_project;
  if (!project) return null;
  const strip = assemblyStripModel(project);
  const acceptedImages = project.type === "photo" ? acceptedPhotoImages(project) : [];
  const totalMs = strip?.totalMs || 0;
  const assembly = project.assembly && typeof project.assembly === "object" ? project.assembly : null;
  const action = actionFor(snapshot);
  return {
    project,
    strip,
    acceptedImages,
    assembly,
    finalReady: project.type === "photo" ? acceptedImages.length > 0 : Boolean(assembly?.asset_id),
    action,
    actionLabel: ASSEMBLY_ACTION_LABELS[action?.status] || "",
    actionWorking: ["queued", "running"].includes(action?.status),
    facts: [
      { label: "Длительность", value: project.type === "photo" ? "—" : formatAssemblyTime(totalMs) },
      { label: "Кадров", value: String((project.scenes || []).length) },
      { label: "Способ генерации", value: project.type === "photo" ? "изображения" : project.gen_mode === "one_shot" ? "один заход" : "кадр за кадром" },
      { label: "Референсов проекта", value: String((project.references || []).filter((item) => !item.local).length) },
    ],
  };
}

function renderStrip(model) {
  const section = document.createElement("section");
  section.className = "assembly-strip-card";
  const heading = document.createElement("h3");
  heading.textContent = "Весь проект на одной полосе";
  const scroll = document.createElement("div");
  scroll.className = "assembly-strip-scroll";
  const strip = document.createElement("div");
  strip.className = "assembly-strip";
  for (const track of model.tracks) {
    const row = document.createElement("div");
    row.className = "assembly-track";
    const label = document.createElement("span");
    label.className = "assembly-track-label";
    label.textContent = track.label;
    const lanes = document.createElement("div");
    lanes.className = "assembly-track-lanes";
    for (const lane of track.lanes) {
      const laneNode = document.createElement("div");
      laneNode.className = "assembly-lane";
      laneNode.dataset.lane = lane.id;
      for (const item of lane.blocks) {
        const block = svgElement("svg", "assembly-block-svg");
        block.dataset.tone = item.tone;
        block.dataset.durationMs = String(item.durationMs);
        block.setAttribute("width", percentWidth(item.durationMs, model.totalMs, lane.blocks.length));
        block.setAttribute("height", "34");
        block.setAttribute("role", "img");
        block.setAttribute("aria-label", item.label || `${track.label}: пустой интервал`);
        const shape = svgElement("rect", "assembly-block-shape");
        shape.dataset.tone = item.tone;
        shape.setAttribute("x", "0");
        shape.setAttribute("y", "0");
        shape.setAttribute("width", "100%");
        shape.setAttribute("height", "34");
        shape.setAttribute("rx", "6");
        const foreign = svgElement("foreignObject");
        foreign.setAttribute("x", "0");
        foreign.setAttribute("y", "0");
        foreign.setAttribute("width", "100%");
        foreign.setAttribute("height", "34");
        const label = document.createElementNS(XHTML_NS, "div");
        label.setAttribute("class", "assembly-block-label");
        label.dataset.tone = item.tone;
        label.textContent = item.label;
        foreign.append(label);
        block.append(shape, foreign);
        laneNode.append(block);
      }
      lanes.append(laneNode);
    }
    row.append(label, lanes);
    strip.append(row);
  }
  const scale = document.createElement("div");
  scale.className = "assembly-scale";
  for (const value of model.scaleLabels) {
    const label = document.createElement("span");
    label.textContent = value;
    scale.append(label);
  }
  strip.append(scale);
  scroll.append(strip);
  section.append(heading, scroll);
  return section;
}

function renderPhotoFinal(model) {
  const section = document.createElement("section");
  section.className = "assembly-photo-list";
  const heading = document.createElement("h3");
  heading.textContent = "Принятые изображения";
  section.append(heading);
  for (const image of model.acceptedImages) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "assembly-photo-item";
    button.textContent = image.title;
    markControlHooks(button, image.sceneId, "open-final-image");
    button.addEventListener("click", () => button.dispatchEvent(new CustomEvent("studio:open-viewer", {
      bubbles: true,
      detail: { kind: "image", asset: { assetUrl: image.assetUrl, assetId: image.assetId, caption: image.caption } },
    })));
    section.append(button);
  }
  return section;
}

function renderFinalMedia(model) {
  if (model.project.type === "photo" && !model.assembly?.asset_id) return null;
  const wrap = document.createElement("div");
  wrap.className = "assembly-final-media";
  const assembly = model.assembly;
  if (!assembly || !hasLoadableAsset(assembly.asset_url)) {
    wrap.append(buildAssetPlaceholder(model.project.type === "photo" ? "Изображение недоступно" : "Финал ещё не собран"));
    return wrap;
  }
  const media = model.project.type === "photo"
    ? document.createElement("img")
    : finalVideoPool.acquire(
      "assembly-final",
      `${model.project.id}::${assembly.asset_id}::${assembly.asset_url}`,
    );
  if (model.project.type === "photo") {
    media.alt = assembly.summary || "Финальное изображение";
  } else {
    finalVideoPool.observe();
    media.controls = true;
    media.preload = "metadata";
    markControlHooks(media, "assembly-final", "final-video-player");
  }
  if (media.getAttribute("src") !== assembly.asset_url) media.setAttribute("src", assembly.asset_url);
  if (media.__aimasterFinalErrorHandler) {
    media.removeEventListener("error", media.__aimasterFinalErrorHandler);
  }
  const fail = () => {
    const placeholder = buildAssetPlaceholder(model.project.type === "photo" ? "Изображение недоступно" : "Видео недоступно");
    markAssetError(placeholder, assembly.asset_id);
    wrap.replaceChildren(placeholder);
  };
  media.__aimasterFinalErrorHandler = fail;
  media.addEventListener("error", fail);
  wrap.append(media);
  return wrap;
}

export function renderAssemblyStep(root, { state, readOnly = false }) {
  root.textContent = "";
  const snapshot = state.snapshot;
  const model = assemblyStepModel(snapshot);
  const surface = document.createElement("section");
  surface.className = "step-assembly";
  const heading = document.createElement("h2");
  heading.textContent = "Сборка";
  surface.append(heading, model.strip ? renderStrip(model.strip) : renderPhotoFinal(model));

  const summary = document.createElement("section");
  summary.className = "assembly-summary-card";
  const finalMedia = renderFinalMedia(model);
  if (finalMedia) summary.append(finalMedia);
  const details = document.createElement("div");
  details.className = "assembly-summary-details";
  const title = document.createElement("h3");
  title.textContent = model.finalReady ? "Финал собран" : "Осталась сборка";
  const copy = document.createElement("p");
  copy.textContent = model.project.type === "photo" ? "Финал фото-проекта — принятые изображения сцен." : "Соберём принятое движение и звук в один файл.";
  const facts = document.createElement("dl");
  for (const fact of model.facts) {
    const term = document.createElement("dt"); term.textContent = fact.label;
    const value = document.createElement("dd"); value.textContent = fact.value;
    facts.append(term, value);
  }
  details.append(title, copy, facts);
  const controls = document.createElement("div");
  controls.className = "assembly-controls";
  const status = buildStatusLine();
  if (!readOnly && snapshot.view_stage?.current_stage === "assembly" && snapshot.view_stage.allowed_actions?.includes("assemble")) {
    const assemble = buildSimpleButton({
      actionType: "assemble",
      targetId: "final",
      expectedRevision: snapshot.revision,
      projectId: model.project.id,
      row: controls,
      status,
      label: "Собрать финал",
      awaitUpdate: false,
      successText: "Отправлено, ждём ответа в чате",
    });
    assemble.disabled = model.actionWorking;
    controls.append(assemble);
  } else if (readOnly) {
    controls.append(agentControl({ label: model.finalReady ? "Пересобрать финал" : "Собрать финал", title: model.finalReady ? "Пересобрать финал" : "Собрать финал", targetId: "final", action: "assemble-chat", className: "agent-prompt-button agent-prompt-button-primary",
      prompt: `Открой ${exactTarget({ projectId: model.project.id, targetId: "final", revision: snapshot.revision })}. Проверь принятые материалы, длительность, дорожки и readiness. Покажи план сборки и после моего подтверждения запусти assemble через рабочий чат; не подменяй отсутствующие материалы.` }));
    if (model.project.type === "photo" && model.acceptedImages.length > 1) {
      controls.append(agentControl({ label: "Изменить порядок", title: "Порядок финальных изображений", targetId: "final", action: "reorder-photo-final-chat",
        prompt: `Открой ${exactTarget({ projectId: model.project.id, targetId: "final", revision: snapshot.revision })}. Покажи текущий порядок принятых изображений по scene_id, спроси желаемый порядок и после моего ответа примени его штатной командой Creator Studio без замены файлов.` }));
    }
  }
  if (model.actionLabel) status.textContent = model.actionLabel;
  details.append(controls, status);
  summary.append(details);
  surface.append(summary);
  if (!readOnly && snapshot.view_stage?.current_stage === "assembly") {
    const readiness = model.project.stage_readiness;
    const completed = snapshot.view_stage?.gate_status === "approved" || model.project.status === "done";
    renderStageActions(surface, snapshot, {
      approveLabel: "Принять финал",
      heading: completed ? "Проект завершён" : model.finalReady ? "Финал готов" : "Финальный материал ещё не готов",
      description: completed
        ? "Финальный материал принят."
        : model.finalReady
          ? "Принятие завершит проект."
        : model.project.type === "photo" ? "Примите хотя бы одно текущее изображение сцены." : "Сначала соберите и запишите финальный файл.",
      canApprove: readiness?.can_approve === true,
    });
  } else if (readOnly) {
    renderChatStageActions(surface, snapshot, "assembly", { approveLabel: "Принять финал" });
  }
  root.append(surface);
}
