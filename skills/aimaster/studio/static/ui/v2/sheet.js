// Нижняя шторка (хэндофф 2026-09-23, «Шторки»): радиус 20 20 0 0, хэндл
// 40×4, пункты по 50px, затемнение. `Esc` и клик по фону закрывают, Tab
// не выходит из шторки, фокус возвращается туда, откуда её открыли. На
// десктопе — та же шторка по центру снизу, не шире 480px (это CSS).

const FOCUSABLE = 'button:not([disabled]), a[href], input:not([disabled]), textarea, [tabindex="0"]';

let current = null;

function trapTab(event, panel) {
  const nodes = [...panel.querySelectorAll(FOCUSABLE)].filter((item) => !item.hidden);
  if (!nodes.length) {
    event.preventDefault();
    return;
  }
  const first = nodes[0];
  const last = nodes.at(-1);
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  } else if (!panel.contains(document.activeElement)) {
    event.preventDefault();
    first.focus();
  }
}

function itemButton(item, close) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "v2-sheet-item";
  if (item.tone === "danger") button.dataset.tone = "danger";
  const label = document.createElement("span");
  label.className = "v2-sheet-item-label";
  label.textContent = String(item.label ?? "");
  button.append(label);
  if (item.hint) {
    const hint = document.createElement("span");
    hint.className = "v2-sheet-item-hint";
    hint.textContent = String(item.hint);
    label.append(hint);
  }
  const arrow = document.createElement("span");
  arrow.className = "v2-sheet-item-arrow";
  arrow.setAttribute("aria-hidden", "true");
  arrow.textContent = "›";
  button.append(arrow);
  button.addEventListener("click", () => {
    // Сначала закрыть и вернуть фокус, потом действие: оно может открыть
    // просмотрщик или окно агента, и фокус должен уйти уже туда.
    close({ restoreFocus: false });
    if (typeof item.onSelect === "function") item.onSelect(button);
  });
  return button;
}

/**
 * @param {{title?: string, items?: {label: string, hint?: string,
 *   tone?: "danger", onSelect?: (button: HTMLElement) => void}[],
 *   returnFocus?: HTMLElement|null}} options
 * @returns {() => void} закрыть шторку
 */
export function openSheet({ title = "", items = [], returnFocus = null } = {}) {
  if (current) current({ restoreFocus: false });
  const back = returnFocus instanceof HTMLElement ? returnFocus : document.activeElement;

  const root = document.createElement("div");
  root.className = "v2-sheet";
  root.dataset.hook = "v2-sheet";
  const panel = document.createElement("div");
  panel.className = "v2-sheet-panel";
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-modal", "true");
  panel.tabIndex = -1;
  const handle = document.createElement("span");
  handle.className = "v2-sheet-handle";
  handle.setAttribute("aria-hidden", "true");
  panel.append(handle);
  if (title) {
    const heading = document.createElement("h2");
    heading.className = "v2-sheet-title";
    heading.id = `v2-sheet-title-${Date.now()}`;
    heading.textContent = title;
    panel.setAttribute("aria-labelledby", heading.id);
    panel.append(heading);
  } else {
    panel.setAttribute("aria-label", "Действия");
  }
  const list = document.createElement("div");
  list.className = "v2-sheet-items";

  let closed = false;
  function close({ restoreFocus = true } = {}) {
    if (closed) return;
    closed = true;
    window.removeEventListener("keydown", onKeyDown, true);
    root.remove();
    document.body.classList.remove("v2-sheet-open");
    if (current === close) current = null;
    if (restoreFocus && back instanceof HTMLElement && back.isConnected) back.focus();
  }
  function onKeyDown(event) {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      close();
    } else if (event.key === "Tab") {
      trapTab(event, panel);
    }
  }

  for (const item of items) list.append(itemButton(item, close));
  panel.append(list);
  root.append(panel);
  root.addEventListener("click", (event) => { if (event.target === root) close(); });
  // На `window`, а не на `document`: шторка может лежать поверх
  // просмотрщика, а он слушает `document` в фазе захвата — `Esc` должен
  // сперва закрыть шторку и дальше не идти.
  window.addEventListener("keydown", onKeyDown, true);
  document.body.append(root);
  document.body.classList.add("v2-sheet-open");
  current = close;
  (list.querySelector("button") || panel).focus();
  return () => close();
}
