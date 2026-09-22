// «···» — всё редкое с экрана (спецификация §1: «на экране не больше двух
// кнопок, всё редкое — за „···“»). Обычный `<details>`: раскрывается без
// скрипта, закрывается `Esc` и читается экранным диктором как надо.

import { chatButton, el } from "./dom.js";

/**
 * @param {{label: string, request: {title: string, prompt: string,
 *          attachmentHint?: string}}[]} items пункты меню; каждый
 *   открывает диалог с готовым запросом агенту
 * @returns {HTMLElement|null} `<details>` или `null`, если пунктов нет
 */
export function moreMenu(items) {
  const list = (Array.isArray(items) ? items : []).filter((item) => item && item.request);
  if (!list.length) return null;
  const box = el("details", "v2-more");
  box.dataset.hook = "v2-more";
  const summary = el("summary", "v2-more-summary", "···");
  summary.setAttribute("aria-label", "Ещё действия");
  const menu = el("div", "v2-more-items");
  for (const item of list) menu.append(chatButton(item.label, item.request, "v2-chat-button v2-more-item"));
  box.append(summary, menu);
  return box;
}
