// Низ каждого экрана: одна главная кнопка и строка «Осталось решить: …»
// (спецификация §3). Кнопка одобряет стадию напрямую — тем же действием
// `approve` с `target_id` стадии, каким это делает v1
// (`ui/stage-approval.js`); никаких вторых кнопок здесь нет: «вернуть на
// доработку» и прочее редкое уходит в чат.

import { buildSimpleButton, buildStatusLine } from "../card-forms.js";
import { agentControl, exactTarget } from "../agent-control.js";
import { SCREEN_LABELS, primaryAction, projectFinished, screenForStage } from "./screen-map.js";
import { el, openViewer } from "./dom.js";
import { requestScreen } from "./path-nav.js";
import { openSheet } from "./sheet.js";

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
  past: "Шаг одобрен. Вы смотрите пройденный экран.",
  done: "Проект завершён. Все шаги одобрены.",
  ready: "Всё решено — можно одобрять.",
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

function note(text, hook) {
  const line = el("p", "v2-footer-note", text);
  if (hook) line.dataset.hook = hook;
  return line;
}

/** Открыть просмотрщик на месте пункта; у причины от сервера места нет. */
function goTo(item, trigger) {
  if (!item?.target) return;
  openViewer(item.target, { tab: item.tab || undefined, slot: item.slot || undefined, trigger });
}

/** Десктоп: «Осталось решить:» и янтарные чипсы, каждый — в просмотрщик. */
function remainingChips(items) {
  const box = el("div", "v2-footer-remaining");
  box.dataset.hook = "v2-remaining";
  box.append(el("span", "v2-footer-remaining-label", "Осталось решить:"));
  const list = el("ul", "v2-footer-chips");
  for (const item of items) {
    const li = el("li");
    let chip;
    if (item.target) {
      chip = el("button", "v2-footer-chip", item.label);
      chip.type = "button";
      chip.dataset.hook = "v2-remaining-item";
      chip.title = "Открыть это место";
      chip.addEventListener("click", () => goTo(item, chip));
    } else {
      chip = el("span", "v2-footer-chip", item.label);
    }
    li.append(chip);
    list.append(li);
  }
  box.append(list);
  return box;
}

/** Телефон: одна плашка «Осталось решить: N · показать ›» → шторка. */
function remainingPlate(items) {
  const plate = el("button", "v2-footer-plate");
  plate.type = "button";
  plate.dataset.hook = "v2-remaining-plate";
  plate.append(
    el("span", "", `Осталось решить: ${items.length}`),
    el("span", "v2-footer-plate-more", "показать ›"),
  );
  plate.addEventListener("click", () => openSheet({
    title: "Осталось решить",
    returnFocus: plate,
    items: items.map((item) => ({
      label: item.label,
      hint: item.target ? "" : "подробности — у агента в чате",
      onSelect: () => goTo(item, plate),
    })),
  }));
  return plate;
}

/** «Вернуться к шагу …» с пройденного экрана на текущий шаг проекта. */
function backButton(project, finished) {
  const screen = screenForStage(project?.stage);
  if (!screen) return null;
  const label = `Вернуться к шагу «${finished ? SCREEN_LABELS.assembly : SCREEN_LABELS[screen]}»`;
  const button = el("button", "v2-primary v2-primary-back", label);
  button.type = "button";
  button.dataset.hook = "v2-back-to-stage";
  button.addEventListener("click", () => requestScreen(screen, button));
  return button;
}

/**
 * @param {object} snapshot весь snapshot (нужны `revision` и `view_stage`)
 * @param {{screen?: string}} [options] какой экран открыт: на пройденном
 *   шаге вместо одобрения — возврат к текущему шагу проекта.
 * @returns {HTMLElement} `<footer>` экрана; оболочка переносит его в
 *   липкую полосу внизу страницы (`shell.js`).
 */
export function renderFooter(snapshot, { screen } = {}) {
  const project = snapshot?.active_project;
  const action = primaryAction(project);
  const mode = footerMode(snapshot, { screen, stage: action.stage });
  const footer = el("footer", "v2-footer");
  footer.dataset.hook = "v2-footer";
  footer.dataset.mode = mode;
  const inner = el("div", "v2-footer-inner");
  const left = el("div", "v2-footer-left");
  const row = el("div", "v2-footer-buttons");
  footer.append(inner);
  inner.append(left, row);

  if (mode === "past" || mode === "done") {
    const finished = projectFinished(snapshot);
    left.append(note(finished ? FOOTER_NOTICES.done : FOOTER_NOTICES.past, "v2-footer-summary"));
    if (mode === "past") {
      const back = backButton(project, finished);
      if (back) row.append(back);
    }
    return footer;
  }

  if (action.items.length) {
    left.append(remainingChips(action.items), remainingPlate(action.items));
  } else {
    left.append(note(FOOTER_NOTICES.ready, "v2-remaining"));
  }
  const status = buildStatusLine();
  status.classList.add("v2-footer-status");

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
      className: "v2-primary",
      prompt: `Открой ${exactTarget({ projectId: project?.id, targetId: action.stage, revision: snapshot?.revision })}. `
        + `Проверь готовность этого шага и обязательные результаты. Если что-то не решено — перечисли и ничего не меняй; `
        + `иначе одобри шаг штатной командой Creator Studio и скажи, что стало дальше.`,
    }));
  }

  inner.append(status);
  return footer;
}
