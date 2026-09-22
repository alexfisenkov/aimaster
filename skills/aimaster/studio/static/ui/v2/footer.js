// Низ каждого экрана: одна главная кнопка и строка «Осталось решить: …»
// (спецификация §3). Кнопка одобряет стадию напрямую — тем же действием
// `approve` с `target_id` стадии, каким это делает v1
// (`ui/stage-approval.js`); никаких вторых кнопок здесь нет: «вернуть на
// доработку» и прочее редкое уходит в чат.

import { buildSimpleButton, buildStatusLine } from "../card-forms.js";
import { agentControl, exactTarget } from "../agent-control.js";
import { primaryAction, screenForStage } from "./screen-map.js";
import { el } from "./dom.js";

/** Стадии, которые сервер разрешает одобрять кнопкой (`MILESTONE_TARGETS`). */
const DIRECT_STAGES = Object.freeze(["image_plan", "image_results", "motion", "audio", "assembly"]);

/**
 * @param {object} snapshot весь snapshot (нужны `revision` и `view_stage`)
 * @param {{screen?: string}} [options] какой экран открыт: на пройденном
 *   шаге кнопки нет вовсе — путь открывает его только на просмотр.
 * @returns {HTMLElement} `<footer>` экрана
 */
export function renderFooter(snapshot, { screen } = {}) {
  const project = snapshot?.active_project;
  const action = primaryAction(project);
  if (screen && screen !== screenForStage(project?.stage)) {
    const past = el("footer", "v2-footer");
    past.dataset.hook = "v2-footer";
    past.append(el("p", "v2-footer-summary", "Этот шаг уже пройден — здесь он открыт только на просмотр."));
    return past;
  }
  const viewStage = snapshot?.view_stage || {};
  const allowed = Array.isArray(viewStage.allowed_actions) ? viewStage.allowed_actions : [];
  const onCurrentStage = viewStage.current_stage === action.stage;

  const footer = el("footer", "v2-footer");
  footer.dataset.hook = "v2-footer";
  const summary = el("p", "v2-footer-summary");
  summary.dataset.hook = "v2-remaining";
  summary.textContent = action.remaining.length
    ? `Осталось решить: ${action.remaining.join("; ")}.`
    : "Всё решено — можно одобрять.";
  const status = buildStatusLine();
  const row = el("div", "v2-footer-buttons");

  const canDecideHere = onCurrentStage && allowed.includes("approve") && DIRECT_STAGES.includes(action.stage);
  if (canDecideHere) {
    const button = buildSimpleButton({
      actionType: "approve",
      targetId: action.stage,
      expectedRevision: snapshot.revision,
      projectId: project?.id,
      row,
      status,
      label: action.label,
      hookAction: "approve-stage",
    });
    button.classList.add("v2-primary");
    button.disabled = !action.enabled;
    row.append(button);
  } else if (action.stage) {
    row.append(agentControl({
      label: action.label,
      title: action.label,
      targetId: action.stage,
      action: "approve-stage-chat",
      className: "v2-chat-button v2-primary",
      prompt: `Открой ${exactTarget({ projectId: project?.id, targetId: action.stage, revision: snapshot?.revision })}. `
        + `Проверь готовность этого шага и обязательные результаты. Если что-то не решено — перечисли и ничего не меняй; `
        + `иначе одобри шаг штатной командой Creator Studio и скажи, что стало дальше.`,
    }));
  }

  footer.append(summary, row, status);
  return footer;
}
