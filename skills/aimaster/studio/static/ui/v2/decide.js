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
  restore: "Вернуть",
});

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
    label: chosen ? (mark === "принят" ? "Принят" : "Выбран") : label,
    successText: "Решение отправлено.",
  });
  button.classList.add("v2-viewer-primary");
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
 * Ряд под холстом: «Оставить этот …», «＋ Ещё вариант» и «···».
 *
 * @param {{project: object, revision: number, allowedActions: string[],
 *          currentStage: string, collection: string, version: object|null,
 *          keepLabel?: string, mark?: string, sceneId?: string, slot?: string,
 *          layer?: string, referenceId?: string, promptVersion?: object,
 *          editWhat?: string, secondary?: {label: string, request: object},
 *          chatMenu?: boolean, statusText?: string,
 *          onStatus?: (text: string) => void}} context
 *   `secondary` заменяет «＋ Ещё вариант» (сборке нужен «Пересобрать»),
 *   `chatMenu: false` убирает из «···» пункты про файл и промпт,
 *   `statusText`/`onStatus` — текст исхода, переживающий перерисовку.
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
  buttons.append(context.secondary
    ? chatButton(context.secondary.label, context.secondary.request, "v2-viewer-secondary")
    : chatButton(
      "＋ Ещё вариант",
      moreVariants({ ...chat, promptVersion: context.promptVersion, selectedVariant: version }),
      "v2-viewer-secondary",
    ));

  const items = [];
  for (const actionType of MENU_ORDER) {
    if (!actions.includes(actionType)) continue;
    const wrap = document.createElement("div");
    wrap.className = "more-menu-control";
    wrap.append(actionType === "reject"
      ? buildCommentForm({
        actionType: "reject",
        targetId: resultTargetId(version),
        expectedRevision: revision,
        projectId,
        key: draftKey(projectId, "v2-viewer", resultTargetId(version)),
        row: buttons,
        status,
        toggleLabel: MENU_LABELS.reject,
      })
      : buildSimpleButton({
        actionType,
        targetId: resultTargetId(version),
        expectedRevision: revision,
        projectId,
        row: buttons,
        status,
        label: MENU_LABELS[actionType],
      }));
    items.push({ id: actionType, content: wrap });
  }
  if (context.chatMenu !== false) {
    items.push({
      id: "upload",
      content: chatButton("Загрузить свой файл → чат", uploadFrame(chat), "more-menu-item"),
    });
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
    buttons.append(buildMoreMenu({
      projectId: projectId || "project",
      targetId: `v2-viewer:${resultTargetId(version) || "none"}`,
      items,
    }));
  }

  // Текст исхода ставится последним: `buildCommentForm` при сборке
  // затирает строку исхода своим черновиком (у него она общая с кнопками),
  // и восстановленный текст пропал бы под ним. Живёт он в состоянии
  // просмотрщика, а не в узле, — узел отвалится на первой же перерисовке,
  // а фоновый опрос приходит каждые 8 секунд.
  status.textContent = typeof context.statusText === "string" ? context.statusText : "";
  if (typeof context.onStatus === "function") {
    new MutationObserver(() => context.onStatus(status.textContent)).observe(status, {
      childList: true,
      characterData: true,
      subtree: true,
    });
  }

  row.append(buttons, status);
  return row;
}
