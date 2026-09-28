// Опрос монтажа, пока открыт экран «Сборка» — вход для экрана: дешёвое
// состояние раз в 5 с (только когда вкладка видна), схема слоёв — когда
// сменился её ключ. Каждый опрос — ещё и знак серверу «экран смотрят»: стол,
// открытый дашбордом, не остановится по простою (studio/desk_keeper.py).
// Ядро без DOM — montage-feed-core.js; здесь только таймер опроса и событие
// `studio:montage-updated`. Опрос страницы заводится при первом показе, не
// при импорте — тесты импортируют этот модуль без побочных эффектов.

import { getMontage } from "./montage-api.js";
import { POLL_MS, createMontageFeed } from "./montage-feed-core.js";

export { POLL_MS, createMontageFeed };

let feed = null;
let timer = null;

function pageFeed() {
  if (!feed) {
    feed = createMontageFeed({
      load: (id, part, signal) => getMontage(id, part, undefined, signal),
      notify: (id) => document.dispatchEvent(new CustomEvent("studio:montage-updated", {
        bubbles: true, detail: { projectId: id },
      })),
    });
  }
  return feed;
}

function visible() {
  return typeof document === "undefined" || document.visibilityState === "visible";
}

/** Экран «Сборка» проекта на экране: начать (или продолжить) опрос. */
export function showMontage(projectId) {
  const current = pageFeed();
  const fresh = current.active() !== projectId;
  current.show(projectId);
  if (!timer) timer = setInterval(() => { if (visible()) current.tick(); }, POLL_MS);
  if (fresh) current.tick();
}

/** Другой экран или фото-проект — опрос не нужен. */
export function hideMontage() {
  feed?.hide();
  if (timer) {
    clearInterval(timer);
    timer = null;
  }
}

/** Что известно о монтаже проекта: `{status, model, error, modelFresh,
 * modelLagging}` или `null` (montage-entry.js). `modelFresh: false` —
 * показанная схема отстала от статуса: плашки и длина её не читают;
 * `modelLagging` — отстала дольше одного опроса: схема помечена
 * «обновляется…». */
export function montageState(projectId) {
  return feed ? feed.current(projectId) : null;
}

/** Спросить сейчас: после «Сделать текущей», открытия стола, возврата на
 * вкладку. Резолвится по своему статусу — вызывающий код не ждёт схему;
 * экран также слушает `studio:montage-updated` отдельно. */
export function refreshMontage() {
  return feed ? feed.refresh() : Promise.resolve();
}
