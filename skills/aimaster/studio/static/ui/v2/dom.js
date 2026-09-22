// Мелочи для сборки DOM в v2. Ни одного знания о проекте — только руки.
// CSP страницы запрещает inline-стили и скрипты, поэтому всё оформление
// живёт в `styles/v2/*.css`, а здесь расставляются только классы.

import { requestAgentPrompt } from "../chat-prompt-dialog.js";

// --- Фокус после перерисовки -------------------------------------------
//
// Любая зона v2 рисуется заново целиком, а `submitAction` (`ui/actions.js`)
// гасит нажатую кнопку синхронно, ещё до первого `await`, — браузер тут же
// уводит фокус на `<body>`. Поэтому `ui/card-forms.js` шлёт
// `studio:card-focus-pending` **до** отправки, а мы этот листок забираем
// после перерисовки. Ровно тот же приём, что у v1 (`ui/shell.js`,
// `takePendingCardFocus`), только своя копия: та не экспортирована, а
// `createPendingFocusRegistry` из `shell-runtime.js` умеет отдавать листок
// лишь вычёркивая его — здесь же его сперва показывают обеим зонам.

let pendingCardFocus = null;
let focusRelayAttached = false;

function ensureFocusRelay() {
  if (focusRelayAttached) return;
  focusRelayAttached = true;
  document.addEventListener("studio:card-focus-pending", (event) => {
    const { targetId, action } = event?.detail || {};
    if (typeof targetId === "string" && targetId && typeof action === "string" && action) {
      pendingCardFocus = { targetId, action };
    }
  });
}

/**
 * Какой контрол держал фокус перед перерисовкой: живой, если он ещё в
 * фокусе, иначе — листок от `noteCardFocusPending`.
 *
 * Листок здесь **не** вычёркивается: зон две — область экрана
 * (`renderShellV2`) и оверлей просмотрщика, они перерисовываются по
 * очереди одним и тем же обновлением, и та, что спросила первой, забрала
 * бы чужой листок себе. Вычёркивает его `restoreCardFocus`, и только
 * когда фокус действительно поставлен.
 *
 * @returns {{targetId: string, action: string}|null}
 */
export function cardFocusNote() {
  ensureFocusRelay();
  const active = document.activeElement;
  if (active instanceof HTMLElement && active.dataset.hook === "card-control") {
    const { targetId, action } = active.dataset;
    if (targetId && action) return { targetId, action };
  }
  return pendingCardFocus;
}

/**
 * Вернуть фокус тому же контролу внутри `zone`: сначала точное совпадение
 * пары `data-target-id`/`data-action`, потом любой живой контрол того же
 * элемента (решение убирает часть кнопок — «Скрыть» после решения может
 * исчезнуть, а плитка остаться).
 *
 * @returns {boolean} удалось ли поставить фокус
 */
export function restoreCardFocus(zone, note) {
  if (!zone || !note?.targetId) return false;
  const id = CSS.escape(note.targetId);
  const exact = note.action
    ? zone.querySelector(`[data-hook="card-control"][data-target-id="${id}"][data-action="${CSS.escape(note.action)}"]`)
    : null;
  const target = exact && !exact.disabled
    ? exact
    : [...zone.querySelectorAll(`[data-hook="card-control"][data-target-id="${id}"]`)].find((node) => !node.disabled);
  if (!target) return false;
  target.focus();
  if (document.activeElement !== target) return false;
  pendingCardFocus = null;
  return true;
}

/**
 * @param {string} tag имя тега
 * @param {string} [className]
 * @param {string} [text] текстовое содержимое (никогда не HTML)
 * @returns {HTMLElement}
 */
export function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

/**
 * Кнопка, открывающая диалог с готовым запросом агенту.
 * @param {string} label надпись
 * @param {{title: string, prompt: string, attachmentHint?: string}} request текст из `chat-prompts.js`
 * @param {string} [className]
 */
export function chatButton(label, request, className = "v2-chat-button") {
  const button = el("button", className, label);
  button.type = "button";
  button.addEventListener("click", () => requestAgentPrompt(request, button));
  return button;
}

/**
 * Картинка результата или заглушка, если файла нет. Ошибку загрузки
 * показываем на месте, а не молча пустым прямоугольником.
 * @param {string|null} assetUrl `/assets/…`
 * @param {string} alt
 */
export function thumb(assetUrl, alt) {
  if (typeof assetUrl !== "string" || !assetUrl.startsWith("/assets/")) {
    return el("span", "v2-thumb v2-thumb-empty");
  }
  const wrap = el("span", "v2-thumb");
  const image = document.createElement("img");
  image.src = assetUrl;
  image.alt = alt || "";
  image.loading = "lazy";
  image.addEventListener("error", () => {
    wrap.classList.add("v2-thumb-broken");
    image.remove();
  });
  wrap.append(image);
  return wrap;
}

/** 5000 → «00:05»; не число → пустая строка. */
export function clock(ms) {
  if (!Number.isFinite(ms)) return "";
  const total = Math.max(0, Math.round(ms / 1000));
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

/**
 * Попросить открыть просмотрщик (его пишет волна 2).
 * @param {{kind: "scene"|"reference"|"layer"|"assembly", id: string}} target
 * @param {{tab?: "frames"|"video"|"history", slot?: string, trigger?: HTMLElement}} [options]
 */
export function openViewer(target, { tab = "frames", slot, trigger } = {}) {
  document.dispatchEvent(new CustomEvent("studio:open-viewer", {
    bubbles: true,
    detail: { version: 2, target, tab, slot, trigger },
  }));
}
