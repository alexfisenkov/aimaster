import { postAction } from "../actions.js";
import { requestAgentPrompt } from "../chat-prompt-dialog.js";
import { el, chatButton } from "./dom.js";
import { familyData } from "./family-data.js";
import { familyLabel } from "./family.js";
import { projectRef } from "./chat-prompts.js";
import { t } from "./locale.js";

const RUNNING = new Set(["queued", "running"]);
export function selectedSpending(route) {
  return route?.status === "selected" && route.route_id && route.provider && route.model
    ? { confirmed: true, route_id: route.route_id, provider: route.provider, model: route.model } : null;
}
export function canDirectAction(operator, allowed, type, spending) {
  return operator?.available === true && allowed.includes(type) && (!["generate", "vary", "regenerate"].includes(type) || Boolean(spending));
}
function routeLabel(project, positionId) {
  const position = (project.positions || []).find((item) => item.position_id === positionId);
  if (!position) return t("Создать вариант");
  let name = "";
  if (position.kind === "reference") name = (project.references || []).find((item) => item.tag === position.tag)?.label || t("Референсы");
  else if (position.kind === "audio") name = t({ voice: "Голос", music: "Музыка", fx: "Эффекты", atmos: "Атмосфера" }[position.layer] || "Звук");
  else name = (project.scenes || []).find((item) => item.scene_id === position.scene_id)?.title || t("Сцены");
  return t("Создать вариант · {name}", { name });
}
function actionStatus(snapshot, actionId) {
  return (snapshot?.actions || []).find((item) => item.action_id === actionId) || null;
}
function copyFallback(project, revision, target, title, trigger, receipt) {
  const line = receipt?.copy_request || `Открой ${projectRef(project, revision)}. ${title}${target ? ` Позиция ${target}.` : ""}`;
  requestAgentPrompt({ title: t("Продолжить в чате"), prompt: line }, trigger);
}
function control({ project, snapshot, type, target, label, spending = null, operator, title, fallback, className }) {
  const row = el("div", "am-family-action");
  const button = el("button", "v2-chat-button", label); button.type = "button";
  if (className) button.className = className;
  const status = el("p", "am-family-action-status"); status.setAttribute("role", "status");
  const prior = (snapshot.actions || []).find((item) => item.action_type === type && item.target_id === target);
  if (prior) status.textContent = `${prior.status} · ${prior.action_id}`;
  const collection = familyData(project.id)?.routes?.collections?.find((item) => item.action_id === prior?.action_id);
  if (collection) status.textContent = t(collection.phase === "conflict"
    ? "Оригинал сохранён; текущее задание изменилось. Продолжите в чате."
    : "Провайдер создал оригинал; локальная выдача не завершена. Повторять генерацию нельзя.");
  const blocked = prior && ["queued", "running", "outcome_unknown"].includes(prior.status);
  const direct = !blocked && canDirectAction(operator, snapshot.view_stage?.allowed_actions || [], type, spending);
  if (prior && RUNNING.has(prior.status)) button.disabled = true;
  if (!direct) button.textContent = t("{label} → чат", { label });
  button.addEventListener("click", async () => {
    if (!direct && type === "continue-in-chat" && (snapshot.view_stage?.allowed_actions || []).includes(type)) {
      button.disabled = true;
      const receipt = await postAction(type, target, {}, snapshot.revision, crypto.randomUUID());
      button.disabled = false;
      if (receipt.ok) {
        status.textContent = `${receipt.status} · ${receipt.actionId}`;
        copyFallback(project, snapshot.revision, target, title, button, { copy_request: receipt.copyRequest });
      } else copyFallback(project, snapshot.revision, target, title, button, prior);
      return;
    }
    if (!direct) {
      if (fallback) requestAgentPrompt(fallback, button);
      else copyFallback(project, snapshot.revision, target, title, button, prior);
      return;
    }
    button.disabled = true; status.textContent = t("Отправляю действие…");
    const result = await postAction(type, target, spending ? { spending } : {}, snapshot.revision, crypto.randomUUID());
    if (!result.ok) { status.textContent = result.code; button.disabled = false; return; }
    status.textContent = `${result.status} · ${result.actionId}`;
    if (!RUNNING.has(result.status)) {
      if (result.copyRequest) copyFallback(project, snapshot.revision, target, title, button, { copy_request: result.copyRequest });
      button.disabled = false; return;
    }
    let attempts = 0;
    const poll = async () => {
      if (++attempts > 60 || !button.isConnected) { button.disabled = false; return; }
      try {
        const response = await fetch(`/api/projects/${encodeURIComponent(project.id)}/snapshot`, { headers: { Accept: "application/json" } });
        if (response.ok) {
          const latest = actionStatus(await response.json(), result.actionId);
          if (latest) { status.textContent = `${latest.status} · ${result.actionId}${latest.message ? ` · ${latest.message}` : ""}`;
            if (!RUNNING.has(latest.status)) { button.disabled = false; document.dispatchEvent(new CustomEvent("studio:refresh-snapshot", { detail: { projectId: project.id } })); return; } }
        }
      } catch { status.textContent = `Связь прервана · ${result.actionId}`; }
      setTimeout(poll, 2000);
    };
    setTimeout(poll, 2000);
  });
  row.append(button, status); return row;
}

export function generationControl({ project, snapshot, positionId, promptVersion, version, type }, label, request, className) {
  if (!project || !snapshot || !positionId) return chatButton(label, request, className);
  const { operator, routes } = familyData(project.id);
  const route = routes?.routes?.find((item) => item.position_id === positionId);
  const currentPrompt = !promptVersion || promptVersion.version_id === route?.prompt_version_id;
  const action = type || (version?.version_id ? "vary" : "generate");
  return control({ project, snapshot, type: action, target: action === "generate" ? positionId : version?.version_id,
    label, spending: currentPrompt ? selectedSpending(route) : null, operator,
    title: request?.title, fallback: request, className });
}
export function renderFamilyActions(snapshot, language) {
  const project = snapshot.active_project;
  const { operator, routes } = familyData(project.id);
  const box = el("section", "v2-card am-family-actions");
  box.append(el("h2", "v2-card-title", familyLabel("operator", language)));
  box.append(el("p", "v2-section-hint", operator?.available ? t("Работает: {agent} · {status}", { agent: operator.agent, status: operator.status }) : familyLabel("unavailable", language)));
  box.append(control({ project, snapshot, type: "continue-in-chat", target: project.stage || "scenario", label: language === "en" ? "Continue" : "Продолжить", operator, title: "Покажи следующий шаг по текущему проекту." }));
  for (const route of (routes?.routes || []).filter(selectedSpending)) {
    const spending = selectedSpending(route);
    box.append(control({ project, snapshot, type: "generate", target: route.position_id,
      label: routeLabel(project, route.position_id),
      spending, operator, title: "Подготовь и запусти генерацию только для выбранной позиции, после моего подтверждения расхода." }));
  }
  return box;
}
