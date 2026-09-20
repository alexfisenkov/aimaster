import { resolveActionErrorMessage, submitAction, submitActionsSequentially } from "./actions.js";
import { clearDraft, draftKey, getDraft, pruneDrafts, setDraft } from "./card-drafts.js";
import { markControlHooks, noteCardFocusPending, OUTCOME_UNCONFIRMED_TEXT, requestProjectRefresh } from "./card-forms.js";
import { renderGenMode } from "./gen-mode.js";
import { frameCardsModel, renderFrameCard, renderOneShotPrompt } from "./frame-card.js";
import { exactDraftActionTerminalStatus, isActionWorking } from "./prompt-editor.js";
import { referenceGroups } from "./reference-library.js";
import { renderReferenceCard } from "./reference-card.js";
import { requestAgentPrompt } from "./chat-prompt-dialog.js";

function requestReferenceControl(group, model) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "reference-add agent-prompt-button";
  button.textContent = group.addLabel;
  button.addEventListener("click", () => {
    requestAgentPrompt({
      title: `Добавить ${group.requestLabel}`,
      prompt: `Открой проект «${model.projectId}». Я хочу добавить ${group.requestLabel} в референсы проекта. Спроси, прикреплю ли я готовый файл или нужно сгенерировать референс. Для файла сначала проверь вложение и предложи понятное внутреннее название и служебный тег. Для генерации сначала согласуй инструмент, доступную модель, промпт и один разрешённый запуск. После моего выбора создай референс и сообщи его точный reference_id.`,
      attachmentHint: "Если у вас есть готовый референс, прикрепите изображение к сообщению в чате. Вложение не входит в скопированный текст.",
    }, button);
  });
  return button;
}

function addReferenceControl(group, model, status) {
  const key = draftKey(model.projectId, "step-plan-add", group.kind);
  let draft = getDraft(key);
  if (Number.isFinite(draft?.savedRevision) && model.revision > draft.savedRevision) {
    clearDraft(key);
    draft = undefined;
  }
  const button = document.createElement("button");
  button.type = "button";
  button.className = "reference-add";
  button.textContent = group.addLabel;
  markControlHooks(button, `references-${group.kind}`, `reference-add:${group.kind}`);
  button.disabled = draft?.saving === true;
  status.textContent = draft?.message || "";
  button.addEventListener("click", async () => {
    noteCardFocusPending(`references-${group.kind}`, `reference-add:${group.kind}`);
    status.textContent = "Добавляется…";
    setDraft(key, { message: status.textContent, saving: true });
    const result = await submitActionsSequentially({
      actions: [{ actionType: "reference-add", targetId: "references", payload: { kind: group.kind } }],
      expectedRevision: model.revision,
      controls: [button],
    });
    if (result.ok && result.confirmed !== false && result.completed === 1) {
      status.textContent = "Добавлено";
      setDraft(key, { message: status.textContent, saving: false, savedRevision: result.confirmedRevision });
      requestProjectRefresh(model.projectId);
    } else {
      status.textContent = result.ok ? OUTCOME_UNCONFIRMED_TEXT : resolveActionErrorMessage(result.code);
      setDraft(key, { message: status.textContent, saving: false });
      if (!result.ok && ["revision_conflict", "action_failed"].includes(result.code)) requestProjectRefresh(model.projectId);
    }
  });
  return button;
}

export function planStepModel(snapshot, { readOnly = false } = {}) {
  const project = snapshot?.active_project;
  if (!project) return { kind: "empty" };
  const current = !readOnly && snapshot?.view_stage?.current_stage === "image_plan";
  const allowed = new Set(Array.isArray(snapshot?.view_stage?.allowed_actions) ? snapshot.view_stage.allowed_actions : []);
  const canEditReference = current && allowed.has("reference-edit");
  const canEditPrompt = current && allowed.has("edit");
  const canRefreshPrompt = current && allowed.has("prompt-refresh");
  const canGeneratePrompts = current && allowed.has("prompts-generate");
  const canApprove = current && allowed.has("approve");
  return {
    kind: "ready",
    projectId: project.id,
    projectType: project.type,
    revision: snapshot.revision,
    canAdd: current && allowed.has("reference-add"),
    canEditReference,
    canEditPrompt,
    canRefreshPrompt,
    canGeneratePrompts,
    canApprove,
    readiness: project.stage_readiness || null,
    pastImagePositionCount: readOnly
      ? (Array.isArray(project.positions) ? project.positions : []).filter((item) => item?.stage === "image_results").length
      : null,
    frames: frameCardsModel(snapshot, { readOnly }),
    actions: Array.isArray(snapshot.actions) ? snapshot.actions : [],
    groups: referenceGroups(snapshot, {
      readOnly,
      canEditReference,
      canEditPrompt,
      canRefreshPrompt,
      actions: Array.isArray(snapshot.actions) ? snapshot.actions : [],
    }),
  };
}

function mergeDraft(key, patch) {
  setDraft(key, { ...(getDraft(key) || {}), ...patch });
}

function generationHeader(model) {
  const header = document.createElement("div");
  header.className = "plan-frames-header";
  const title = document.createElement("h2");
  title.textContent = "Кадры и промпты";
  const subtitle = document.createElement("span");
  subtitle.textContent = model.readiness?.can_approve ? "Теги стоят внутри текста промпта" : "Промпты ещё не написаны";
  header.append(title, subtitle);
  const spacer = document.createElement("span");
  spacer.className = "plan-header-spacer";
  header.append(spacer);

  const busy = model.frames.globalBusy || isActionWorking(model.actions, "prompts-generate", "project");
  const key = draftKey(model.projectId, "step-plan-prompts", "project");
  let draft = getDraft(key);
  if (
    draft?.baselineRevision < model.revision &&
    !busy &&
    model.readiness?.can_approve
  ) {
    clearDraft(key);
    draft = undefined;
  }
  const terminalStatus = exactDraftActionTerminalStatus(draft, model.actions);
  if (terminalStatus) {
    const hardFailure = ["failed", "outcome_unknown", "needs_chat_setup"].includes(terminalStatus);
    draft = {
      ...draft,
      saving: false,
      message: hardFailure
        ? "Не удалось подготовить промпты. Запустите ещё раз."
        : "Промпты пока не готовы. Можно запустить ещё раз.",
    };
    setDraft(key, draft);
  }
  const button = document.createElement("button");
  button.type = "button";
  button.className = "plan-prompts-generate";
  button.textContent = model.readiness?.can_approve
    ? "Промпты написаны"
    : busy || draft?.saving
      ? "Пишутся…"
      : "Написать промпты";
  const status = document.createElement("p");
  status.className = "plan-status";
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  status.textContent = draft?.message || "";
  if (model.canGeneratePrompts && !model.readiness?.can_approve) {
    markControlHooks(button, "project", "prompts-generate");
    button.disabled = busy || draft?.saving === true;
    button.addEventListener("click", async () => {
      noteCardFocusPending("project", "prompts-generate");
      status.textContent = "Промпты пишутся…";
      mergeDraft(key, { message: status.textContent, saving: true, baselineRevision: model.revision, actionId: null });
      const result = await submitAction({
        actionType: "prompts-generate",
        targetId: "project",
        payload: {},
        expectedRevision: model.revision,
        controls: [button],
        awaitUpdate: false,
      });
      if (result.ok) {
        status.textContent = "Пишутся… Агент получил запрос.";
        mergeDraft(key, { message: status.textContent, saving: true, actionId: result.actionId });
        requestProjectRefresh(model.projectId);
      } else {
        status.textContent = resolveActionErrorMessage(result.code);
        mergeDraft(key, { message: status.textContent, saving: false, actionId: null });
        if (result.code === "revision_conflict") requestProjectRefresh(model.projectId);
      }
    });
  } else {
    button.disabled = true;
  }
  header.append(button, status);
  return header;
}

const READINESS_REASON_LABELS = Object.freeze({
  blocked: "Сначала ответьте агенту в чате.",
  already_approved: "Этот шаг уже одобрен.",
  incomplete_storyboard: "Сначала завершите раскадровку.",
  missing_prompts: "Не у всех обязательных позиций есть промпт.",
  unaccepted_positions: "Сначала примите обязательные результаты.",
});

function positionWord(count) {
  const remainder100 = count % 100;
  const remainder10 = count % 10;
  if (remainder100 >= 11 && remainder100 <= 14) return "позиций";
  if (remainder10 === 1) return "позиция";
  if (remainder10 >= 2 && remainder10 <= 4) return "позиции";
  return "позиций";
}

function readinessPanel(model) {
  const readiness = model.readiness;
  const currentReadiness = readiness?.stage === "image_plan" ? readiness : null;
  if (!currentReadiness && !Number.isInteger(model.pastImagePositionCount)) return null;
  const panel = document.createElement("section");
  panel.className = "plan-readiness";
  const copy = document.createElement("div");
  const title = document.createElement("h2");
  title.textContent = currentReadiness
    ? currentReadiness.can_approve ? "Промпты готовы" : "Промпты пока не готовы"
    : "Промпты одобрены";
  const hint = document.createElement("p");
  const count = currentReadiness?.image_position_count ?? model.pastImagePositionCount;
  const countHint = Number.isInteger(count)
    ? count === 0
      ? "На шаге «Изображения» по плану ничего генерировать не нужно."
      : `На шаге «Изображения» появится ровно то, что вы отметили: ${count} ${positionWord(count)}.`
    : "";
  if (currentReadiness?.can_approve || !currentReadiness) {
    hint.textContent = countHint;
  } else {
    const reason = READINESS_REASON_LABELS[currentReadiness.reason] || "Проверьте обязательные материалы этого шага.";
    hint.textContent = [reason, countHint].filter(Boolean).join(" ");
  }
  copy.append(title, hint);
  panel.append(copy);

  if (!currentReadiness) return panel;
  const status = document.createElement("p");
  status.className = "plan-status";
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  const approve = document.createElement("button");
  approve.type = "button";
  approve.dataset.targetId = "image_plan";
  approve.dataset.action = "approve-prompts";
  approve.textContent = "Одобрить промпты";
  approve.disabled = !currentReadiness.can_approve || !model.canApprove;
  if (currentReadiness.can_approve && model.canApprove) {
    markControlHooks(approve, "image_plan", "approve-prompts");
    approve.addEventListener("click", async () => {
      noteCardFocusPending("image_plan", "approve-prompts");
      status.textContent = "Одобряем…";
      const result = await submitAction({
        actionType: "approve",
        targetId: "image_plan",
        payload: {},
        expectedRevision: model.revision,
        controls: [approve],
      });
      if (result.ok && result.confirmed !== false) {
        requestProjectRefresh(model.projectId);
      } else {
        status.textContent = result.ok ? OUTCOME_UNCONFIRMED_TEXT : resolveActionErrorMessage(result.code);
        if (!result.ok && ["revision_conflict", "action_failed"].includes(result.code)) {
          requestProjectRefresh(model.projectId);
        }
      }
    });
  }
  panel.append(approve, status);
  return panel;
}

export function renderPlanStep(root, { state, readOnly }) {
  root.textContent = "";
  const snapshot = state?.snapshot;
  const model = planStepModel(snapshot, { readOnly });
  model.readOnly = Boolean(readOnly);
  const surface = document.createElement("div");
  surface.className = "step-plan";
  surface.dataset.hook = "step-plan";
  if (model.kind === "empty") {
    surface.setAttribute("aria-busy", "true");
    surface.textContent = "Загружаем кадры и промпты…";
    root.append(surface);
    return;
  }

  const library = document.createElement("section");
  library.className = "plan-section reference-library";
  const heading = document.createElement("h2");
  heading.textContent = "Референсы проекта";
  const intro = document.createElement("p");
  intro.className = "plan-section-description";
  intro.textContent = "Названия здесь помогают ориентироваться внутри проекта. Служебные теги для промптов назначает и проверяет агент. Файлы передаются агенту в чате; загрузки из браузера здесь нет.";
  library.append(heading, intro);

  const knownDrafts = new Set();
  for (const group of model.groups) {
    const block = document.createElement("section");
    block.className = "reference-group";
    block.dataset.kind = group.kind;
    const groupHeading = document.createElement("h3");
    groupHeading.textContent = group.title;
    const subtitle = document.createElement("p");
    subtitle.className = "reference-group-subtitle";
    subtitle.textContent = group.subtitle;
    const grid = document.createElement("div");
    grid.className = "reference-grid";
    for (const item of group.items) {
      const rendered = renderReferenceCard(item, { projectId: model.projectId, revision: model.revision });
      knownDrafts.add(rendered.draftKey);
      grid.append(rendered.card);
    }
    if (model.readOnly) {
      grid.append(requestReferenceControl(group, model));
    } else if (model.canAdd) {
      const status = document.createElement("p");
      status.className = "plan-status";
      status.setAttribute("role", "status");
      status.setAttribute("aria-live", "polite");
      grid.append(addReferenceControl(group, model, status), status);
    }
    block.append(groupHeading, subtitle, grid);
    library.append(block);
  }
  pruneDrafts(`${model.projectId}::step-plan-reference::`, knownDrafts);
  surface.append(library);
  const genMode = renderGenMode(snapshot, { readOnly });
  if (genMode) surface.append(genMode);

  const frames = document.createElement("section");
  frames.className = "plan-frames";
  frames.dataset.hook = "plan-frames";
  frames.append(generationHeader(model));
  for (const card of model.frames.cards) frames.append(renderFrameCard(card));
  surface.append(frames);
  const oneShot = renderOneShotPrompt(model.frames.oneShotPrompt, {
    projectId: model.projectId,
    revision: model.revision,
  });
  if (oneShot) surface.append(oneShot);
  const readiness = readinessPanel(model);
  if (readiness) surface.append(readiness);
  root.append(surface);
}
