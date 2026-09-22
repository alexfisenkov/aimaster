// Мелочи для сборки DOM в v2. Ни одного знания о проекте — только руки.
// CSP страницы запрещает inline-стили и скрипты, поэтому всё оформление
// живёт в `styles/v2/*.css`, а здесь расставляются только классы.

import { requestAgentPrompt } from "../chat-prompt-dialog.js";

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
