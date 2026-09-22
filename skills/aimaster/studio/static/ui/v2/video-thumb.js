// Миниатюра клипа. Картинкой её не сделать: результат движения — это
// mp4, и `<img>` на него отдаёт битый файл. Берём `<video>` с
// `preload="metadata"` и якорем `#t=0.1`: браузер докачивает начало и
// показывает первый кадр, не включая проигрывание. CSP страницы это
// разрешает (`media-src 'self'`), а звук выключен и элемент не
// фокусируется — щёлкает по нему всегда кнопка-обёртка.

import { el } from "./dom.js";

/**
 * @param {string|null} assetUrl `/assets/…`
 * @param {string} label для экранного диктора у пустой заглушки
 * @returns {HTMLElement} `<span class="v2-thumb">` с видео или заглушка
 */
export function videoThumb(assetUrl, label) {
  if (typeof assetUrl !== "string" || !assetUrl.startsWith("/assets/")) {
    return el("span", "v2-thumb v2-thumb-empty");
  }
  const wrap = el("span", "v2-thumb");
  const video = document.createElement("video");
  video.src = `${assetUrl}#t=0.1`;
  video.muted = true;
  video.playsInline = true;
  video.preload = "metadata";
  video.tabIndex = -1;
  video.setAttribute("aria-label", label || "");
  video.addEventListener("error", () => {
    wrap.classList.add("v2-thumb-empty");
    video.remove();
  });
  wrap.append(video);
  return wrap;
}
