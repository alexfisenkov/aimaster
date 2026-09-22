// Низ каждого экрана: одна главная кнопка и строка «Осталось решить: …»
// (спецификация §3). Кнопка одобряет стадию напрямую — тем же действием
// `approve` с `target_id` стадии, каким это делает v1
// (`ui/stage-approval.js`); никаких вторых кнопок здесь нет: «вернуть на
// доработку» и прочее редкое уходит в чат.

import { buildSimpleButton, buildStatusLine } from "../card-forms.js";
import { agentControl, exactTarget } from "../agent-control.js";
import { primaryAction, screenForStage } from "./screen-map.js";
import { el } from "./dom.js";

/**
 * Чем одобряется каждая стадия. Пять стадий-вех сервер принимает общим
 * `approve` с именем стадии в `target_id` (`MILESTONE_TARGETS`), а у
 * сценария свой тип действия `approve-scenario` — вехой он не считается
 * (`decision_stages.MILESTONE_TARGETS` вычитает `scenario`).
 */
const DIRECT_STAGES = Object.freeze({
  scenario: "approve-scenario",
  image_plan: "approve",
  image_results: "approve",
  motion: "approve",
  audio: "approve",
  assembly: "approve",
});

/** Готовые тексты подвала, когда решать здесь нечего. */
export const FOOTER_NOTICES = Object.freeze({
  past: "Этот шаг уже пройден — здесь он открыт только на просмотр.",
  done: "Ролик принят — проект завершён.",
});

/**
 * Что подвал вообще делает на этом экране. Чистая функция — её и
 * проверяют тесты; сам `renderFooter` только рисует.
 *
 * `done` — про `assembly`: это единственная стадия, с которой
 * `derive_view_stage` уже никуда не уходит. После «Принять ролик» она
 * остаётся текущей и по-прежнему числится в `allowed_actions`, хотя
 * второе одобрение сервер отвергнет (`decision_stages.plan_milestone`).
 * Та же отсечка, что у v1 в `stage-approval.approveStageVisible`; без
 * неё подвал рисовал неактивную кнопку и «Осталось решить: шаг уже
 * одобрен» на законченном проекте.
 *
 * @param {object} snapshot весь snapshot
 * @param {{screen?: string, stage?: string}} context экран и стадия шага
 * @returns {"past"|"done"|"decide"|"chat"}
 */
export function footerMode(snapshot, { screen, stage } = {}) {
  const project = snapshot?.active_project;
  if (screen && screen !== screenForStage(project?.stage)) return "past";
  const viewStage = snapshot?.view_stage || {};
  if (viewStage.gate_status === "approved") return "done";
  const allowed = Array.isArray(viewStage.allowed_actions) ? viewStage.allowed_actions : [];
  const actionType = DIRECT_STAGES[stage];
  const direct = viewStage.current_stage === stage && Boolean(actionType) && allowed.includes(actionType);
  return direct ? "decide" : "chat";
}

/**
 * @param {object} snapshot весь snapshot (нужны `revision` и `view_stage`)
 * @param {{screen?: string}} [options] какой экран открыт: на пройденном
 *   шаге кнопки нет вовсе — путь открывает его только на просмотр.
 * @returns {HTMLElement} `<footer>` экрана
 */
export function renderFooter(snapshot, { screen } = {}) {
  const project = snapshot?.active_project;
  const action = primaryAction(project);
  const mode = footerMode(snapshot, { screen, stage: action.stage });
  if (mode === "past" || mode === "done") {
    const notice = el("footer", "v2-footer");
    notice.dataset.hook = "v2-footer";
    notice.append(el("p", "v2-footer-summary", FOOTER_NOTICES[mode]));
    return notice;
  }

  const footer = el("footer", "v2-footer");
  footer.dataset.hook = "v2-footer";
  const summary = el("p", "v2-footer-summary");
  summary.dataset.hook = "v2-remaining";
  summary.textContent = action.remaining.length
    ? `Осталось решить: ${action.remaining.join("; ")}.`
    : "Всё решено — можно одобрять.";
  const status = buildStatusLine();
  const row = el("div", "v2-footer-buttons");

  const actionType = DIRECT_STAGES[action.stage];
  if (mode === "decide") {
    const button = buildSimpleButton({
      actionType,
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
