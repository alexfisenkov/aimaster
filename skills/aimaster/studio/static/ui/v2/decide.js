// Прямые решения по одному варианту (спецификация §6): `approve`,
// `reject`, `hide`, `unhide`, `retire`, `restore` — через существующий
// `ui/actions.js`. `vary`/`regenerate` дашборд не показывает вовсе: всё
// платное уходит в чат промптом из `chat-prompts.js`.
//
// Здесь же собран ряд «две кнопки и «···»» просмотрщика: каждый его
// пункт — либо прямое действие отсюда, либо чат-промпт, так что
// разводить это по двум модулям было бы разрывом одной ответственности.
//
// Чистые функции (`resultTargetId`, `directActionsFor`,
// `directActionRequest`) DOM не трогают — их и покрывают тесты.

import { buildCommentForm, buildSimpleButton, buildStatusLine } from "../card-forms.js";
import { draftKey } from "../card-drafts.js";
import { resolveCardActions } from "../card-model.js";
import { buildMoreMenu } from "../more-menu.js";
import { chatButton } from "./dom.js";
import { editPrompt, moreVariants, uploadFrame } from "./chat-prompts.js";

/** Какая стадия владеет решениями по этой коллекции результатов
 * (`studio/decision_cards.py`, `STAGE_COLLECTIONS`). Решение по карточке
 * чужой стадии сервер не примет, поэтому кнопок там нет вовсе. */
export const RESULT_STAGE_BY_COLLECTION = Object.freeze({
  image_results: "image_results",
  video_results: "motion",
  audio_results: "audio",
});

/** Подписи пунктов «···» — ровно те, что в спецификации §4. */
export const MENU_LABELS = Object.freeze({
  reject: "Отклонить с комментарием…",
  hide: "Скрыть",
  unhide: "Показать",
  retire: "Убрать из работы",
  restore: "Вернуть в работу",
});

/** Что пишет строка исхода при подтверждённом успехе (`card-forms.js`):
 * `approve` — свой текст, остальные кнопки — общий, отказ — пусто. */
const SUCCESS_TEXTS = new Set(["", "Отправлено.", "Решение отправлено."]);

/** Тост после подтверждённого прямого решения — по действию и по тому,
 * что это за материал (кадр, клип, картинка, звук). */
export const OUTCOME_TOASTS = Object.freeze({
  approve: (noun) => `${noun.charAt(0).toUpperCase()}${noun.slice(1)} выбран${noun.endsWith("а") ? "а" : ""}`,
  reject: () => "Вариант отклонён",
  hide: () => "Вариант скрыт",
  unhide: () => "Вариант снова виден",
  retire: () => "Вариант убран из работы",
  restore: () => "Вариант возвращён в работу",
});

/**
 * Текст тоста после успешного прямого действия, или `""`, если тост не
 * нужен (исход не подтверждён, ошибка, неизвестное действие).
 *
 * @param {string} actionType какое действие ушло
 * @param {string} previous текст строки исхода до смены
 * @param {string} next текст после смены
 * @param {string} [noun] «кадр», «клип», «картинка», «звук»
 */
export function outcomeToast(actionType, previous, next, noun = "вариант") {
  if (previous !== SUBMITTING_TEXT || !SUCCESS_TEXTS.has(next)) return "";
  const make = OUTCOME_TOASTS[actionType];
  return make ? make(noun) : "";
}

const MENU_ORDER = Object.freeze(["reject", "hide", "unhide", "retire", "restore"]);

/** Что `ui/card-forms.js` пишет в строку исхода, пока запрос в полёте. */
export const SUBMITTING_TEXT = "Отправляется…";

/**
 * Идёт ли прямо сейчас запрос — по тексту строки исхода. Пока идёт,
 * просмотрщик не перерисовывается: иначе ряд кнопок пересоберётся уже
 * включённым и второй клик уйдёт с тем же `expected_revision`, а текст
 * исхода отвалится вместе со старым узлом.
 *
 * @param {string} statusText текущее содержимое строки исхода
 */
export function isSubmitting(statusText) {
  return statusText === SUBMITTING_TEXT;
}

/** Чем адресуется вариант в `POST /api/actions` — как в v1
 * (`ui/card-decorate.js`): своя версия, а группа только при её отсутствии. */
export function resultTargetId(version) {
  if (!version || typeof version !== "object") return null;
  return version.version_id || version.result_id || null;
}

/**
 * Какие прямые действия можно предложить по этому варианту сейчас.
 *
 * @param {{allowedActions?: string[], currentStage?: string,
 *          collection?: string, version?: object}} context
 * @returns {string[]} подмножество шести допустимых, в фиксированном порядке
 */
export function directActionsFor({ allowedActions, currentStage, collection, version } = {}) {
  // Нечем адресовать — решать нечего: так отсеивается и плитка «ваш
  // файл» загруженного референса, у которой версии результата нет вовсе.
  if (!resultTargetId(version)) return [];
  if (RESULT_STAGE_BY_COLLECTION[collection] !== currentStage) return [];
  return resolveCardActions(allowedActions, "result", version).filter(
    (action) => action === "approve" || MENU_ORDER.includes(action),
  );
}

/**
 * Тело запроса прямого действия — ровно то, что уйдёт в `postAction`.
 *
 * @param {string} actionType approve|reject|hide|unhide|retire|restore
 * @param {object} version запись версии результата
 * @param {number} revision `snapshot.revision`
 * @param {{comment?: string}} [options] комментарий нужен только `reject`
 * @returns {{actionType: string, targetId: string|null, payload: object,
 *            expectedRevision: number}}
 */
export function directActionRequest(actionType, version, revision, { comment } = {}) {
  const payload = actionType === "reject" ? { comment: typeof comment === "string" ? comment.trim() : "" } : {};
  return { actionType, targetId: resultTargetId(version), payload, expectedRevision: revision };
}

function mainButton({ actions, version, revision, projectId, label, row, status, mark }) {
  if (!actions.includes("approve")) return null;
  // Решение уже принято — кнопке нечего делать. Подпись повторяет
  // пометку той же версии на плёнке, чтобы «выбран» на плитке и
  // «Выбран» на кнопке не расходились.
  const chosen = version?.decision === "approved";
  const button = buildSimpleButton({
    actionType: "approve",
    targetId: resultTargetId(version),
    expectedRevision: revision,
    projectId,
    row,
    status,
    label: chosen ? (mark === "принят" ? "✓ Принят" : "✓ Выбран") : label,
    successText: "Решение отправлено.",
  });
  button.classList.add("v2-viewer-primary");
  button.dataset.chosen = String(chosen);
  button.disabled = chosen;
  return button;
}

/** Ключи черновиков, которые заводит один ряд решений по этому варианту. */
export function decideDraftKeys(projectId, version) {
  const id = resultTargetId(version);
  if (!projectId || !id) return [];
  return [draftKey(projectId, "v2-viewer", id), draftKey(projectId, "more-menu", `v2-viewer:${id}`)];
}

/**
 * Форма отказа из общего `buildCommentForm`, разнесённая на два места:
 * пункт «Отклонить с комментарием…» живёт в «···», а сама форма — под
 * рядом кнопок (хэндофф: textarea и красная «Отклонить вариант»). Узлы
 * те же, поэтому черновик, фокус после перерисовки и один запрос в
 * полёте работают как в v1.
 */
function splitRejectForm(wrap) {
  const toggle = wrap.querySelector(":scope > button");
  const form = wrap.querySelector(":scope > form");
  if (!toggle || !form) return { toggle: wrap, form: null };
  form.classList.add("v2-viewer-reject");
  form.dataset.hook = "v2-viewer-reject";
  const caption = form.querySelector(".card-comment-label > span");
  if (caption) caption.textContent = "Что не так с этим вариантом? Комментарий увидит агент.";
  const actions = form.querySelector(".card-comment-actions");
  const submit = actions?.querySelector('button[type="submit"]');
  const cancel = actions?.querySelector('button[type="button"]');
  if (submit) {
    submit.textContent = "Отклонить вариант";
    submit.classList.add("v2-viewer-danger");
  }
  // Сначала «Отмена», потом необратимое — как в макете.
  if (actions && submit && cancel) actions.append(cancel, submit);
  toggle.classList.add("v2-viewer-menu-danger");
  return { toggle, form };
}

/**
 * Ряд под холстом: «Оставить этот …», «＋ Ещё вариант» и «···».
 *
 * @param {{project: object, revision: number, allowedActions: string[],
 *          currentStage: string, collection: string, version: object|null,
 *          keepLabel?: string, mark?: string, sceneId?: string, slot?: string,
 *          layer?: string, referenceId?: string, promptVersion?: object,
 *          editWhat?: string, secondary?: {label: string, request: object},
 *          chatMenu?: boolean, statusText?: string, noun?: string,
 *          onStatus?: (text: string) => void,
 *          onOutcome?: (toast: string) => void}} context
 *   `secondary` заменяет «＋ Ещё вариант» (сборке нужен «Пересобрать»),
 *   `chatMenu: false` убирает из «···» пункты про файл и промпт,
 *   `statusText`/`onStatus` — текст исхода, переживающий перерисовку,
 *   `onOutcome` — текст тоста после подтверждённого решения,
 *   `noun` — «кадр», «клип», «картинка», «звук» для этого тоста.
 *   Без `version` и `secondary` кнопки «＋ Ещё вариант» нет: просьба о
 *   первом варианте — на пустой сцене (`viewer-canvas.renderCanvas`).
 * @returns {HTMLElement} `<div class="v2-viewer-actions">`
 */
export function renderDecideRow(context) {
  const { project, revision, version, keepLabel, collection, currentStage, allowedActions } = context;
  const projectId = project?.id || "";
  const row = document.createElement("div");
  row.className = "v2-viewer-actions";
  row.dataset.hook = "v2-viewer-actions";
  const status = buildStatusLine();
  status.dataset.hook = "v2-viewer-status";
  const buttons = document.createElement("div");
  buttons.className = "v2-viewer-buttons";
  const actions = directActionsFor({ allowedActions, currentStage, collection, version });

  const main = mainButton({
    actions, version, revision, projectId, label: keepLabel, row: buttons, status, mark: context.mark,
  });
  if (main) buttons.append(main);

  const chat = {
    project,
    revision,
    sceneId: context.sceneId,
    referenceId: context.referenceId,
    slot: context.slot,
    layer: context.layer,
  };
  // Вариантов нет — просьба о первом стоит на самой сцене, второй такой
  // же кнопки в ряду не нужно.
  if (context.secondary || version) buttons.append(context.secondary
    ? chatButton(context.secondary.label, context.secondary.request, "v2-viewer-secondary")
    : chatButton(
      "＋ Ещё вариант",
      moreVariants({ ...chat, promptVersion: context.promptVersion, selectedVariant: version }),
      "v2-viewer-secondary",
    ));

  const items = [];
  let rejectForm = null;
  for (const actionType of MENU_ORDER) {
    if (!actions.includes(actionType)) continue;
    const wrap = document.createElement("div");
    wrap.className = "more-menu-control";
    if (actionType === "reject") {
      const { toggle, form } = splitRejectForm(buildCommentForm({
        actionType: "reject",
        targetId: resultTargetId(version),
        expectedRevision: revision,
        projectId,
        key: draftKey(projectId, "v2-viewer", resultTargetId(version)),
        row: buttons,
        status,
        toggleLabel: MENU_LABELS.reject,
      }));
      rejectForm = form;
      wrap.append(toggle);
    } else {
      wrap.append(buildSimpleButton({
        actionType,
        targetId: resultTargetId(version),
        expectedRevision: revision,
        projectId,
        row: buttons,
        status,
        label: MENU_LABELS[actionType],
      }));
    }
    items.push({ id: actionType, content: wrap });
  }
  if (context.chatMenu !== false) {
    const upload = chatButton("Загрузить свой файл → чат", uploadFrame(chat), "more-menu-item");
    if (items.length) upload.classList.add("v2-viewer-menu-split");
    items.push({ id: "upload", content: upload });
    items.push({
      id: "edit-prompt",
      content: chatButton(
        "Изменить промпт → чат",
        editPrompt({ ...chat, promptVersion: context.promptVersion, what: context.editWhat }),
        "more-menu-item",
      ),
    });
  }
  // Пустое «···» не рисуем вовсе: `buildMoreMenu` на пустом списке кидает.
  if (items.length) {
    const menu = buildMoreMenu({
      projectId: projectId || "project",
      targetId: `v2-viewer:${resultTargetId(version) || "none"}`,
      items,
    });
    const trigger = menu.querySelector('[data-more-hook="trigger"]');
    if (trigger) {
      trigger.textContent = "···";
      trigger.setAttribute("aria-label", "Ещё действия");
      trigger.title = "Ещё действия";
    }
    // Пункт отказа открывает форму под рядом — меню при этом закрывается,
    // иначе на телефоне шторка закрывала бы саму форму.
    const rejectToggle = menu.querySelector(".v2-viewer-menu-danger");
    rejectToggle?.addEventListener("click", () => {
      if (menu.dataset.open === "true") trigger?.click();
    });
    buttons.append(menu);
  }

  // Какое действие ушло — чтобы после подтверждения сказать тостом, что
  // именно произошло. Отказ уходит `submit` формы, остальные — кликом.
  let sent = "";
  buttons.addEventListener("click", (event) => {
    const control = event.target instanceof Element ? event.target.closest("[data-action]") : null;
    if (control && MENU_ORDER.concat("approve").includes(control.dataset.action)) sent = control.dataset.action;
  }, true);
  // Форма стоит вне `buttons`, и `submitAction` её кнопки не гасит: второй
  // «Отклонить вариант» посреди запроса ушёл бы с тем же
  // `expected_revision`. Поэтому пока запрос в полёте, отправка глушится
  // здесь, раньше обработчика самой формы.
  rejectForm?.addEventListener("submit", (event) => {
    if (isSubmitting(status.textContent)) {
      event.preventDefault();
      event.stopImmediatePropagation();
      return;
    }
    sent = "reject";
  }, true);

  // Текст исхода ставится последним: `buildCommentForm` при сборке
  // затирает строку исхода своим черновиком (у него она общая с кнопками),
  // и восстановленный текст пропал бы под ним. Живёт он в состоянии
  // просмотрщика, а не в узле, — узел отвалится на первой же перерисовке,
  // а фоновый опрос приходит каждые 8 секунд.
  status.textContent = typeof context.statusText === "string" ? context.statusText : "";
  let previous = status.textContent;
  new MutationObserver(() => {
    const next = status.textContent;
    if (typeof context.onStatus === "function") context.onStatus(next);
    for (const control of rejectForm?.querySelectorAll("button") || []) control.disabled = isSubmitting(next);
    const toast = outcomeToast(sent, previous, next, context.noun);
    previous = next;
    if (toast && typeof context.onOutcome === "function") context.onOutcome(toast);
  }).observe(status, { childList: true, characterData: true, subtree: true });

  if (rejectForm) row.append(buttons, rejectForm, status);
  else row.append(buttons, status);
  return row;
}
