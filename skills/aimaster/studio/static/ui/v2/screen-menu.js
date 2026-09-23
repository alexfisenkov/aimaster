// «···» справа от заголовка экрана (хэндофф 2026-09-23, «Сценарий»):
// на десктопе — выпадающий список под кнопкой, на телефоне — шторка
// снизу. Каждый пункт открывает окно запроса агенту с готовым текстом.
// Свой, а не `more-menu.js`: тот принадлежит просмотрщику.

import { requestAgentPrompt } from "../chat-prompt-dialog.js";
import { el } from "./dom.js";
import { isPhone } from "./responsive.js";
import { openSheet } from "./sheet.js";

/**
 * @param {{label: string, request: {title: string, prompt: string}}[]} items
 * @param {{title?: string}} [options] заголовок шторки на телефоне
 * @returns {HTMLElement} `<details>` с кнопкой «···»
 */
export function screenMenu(items, { title = "" } = {}) {
  const list = (Array.isArray(items) ? items : []).filter((item) => item?.request);
  const box = el("details", "v2-screen-menu");
  box.dataset.hook = "v2-screen-menu";
  const summary = el("summary", "v2-screen-menu-button", "···");
  summary.setAttribute("aria-label", "Ещё действия");
  const menu = el("div", "v2-screen-menu-items");
  for (const item of list) {
    const button = el("button", "v2-screen-menu-item", item.label);
    button.type = "button";
    button.addEventListener("click", () => {
      box.open = false;
      requestAgentPrompt(item.request, summary);
    });
    menu.append(button);
  }
  summary.addEventListener("click", (event) => {
    if (!isPhone()) return;
    event.preventDefault();
    openSheet({
      title,
      returnFocus: summary,
      items: list.map((item) => ({
        label: item.label,
        onSelect: () => requestAgentPrompt(item.request, summary),
      })),
    });
  });
  box.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && box.open) {
      box.open = false;
      summary.focus();
    }
  });
  // Щелчок мимо закрывает список, как у любого выпадающего меню.
  const outside = (event) => {
    if (!box.isConnected || !box.contains(event.target)) {
      box.open = false;
      document.removeEventListener("click", outside, true);
    }
  };
  box.addEventListener("toggle", () => {
    if (box.open) document.addEventListener("click", outside, true);
    else document.removeEventListener("click", outside, true);
  });
  box.append(summary, menu);
  return box;
}
