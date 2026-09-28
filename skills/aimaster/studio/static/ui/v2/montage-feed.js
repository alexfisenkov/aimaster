// Опрос монтажа, пока открыт экран «Сборка»: дешёвое состояние раз в 5 с
// (только когда вкладка видна), схема слоёв — когда сменился index_key.
// Каждый опрос — ещё и знак серверу «экран смотрят»: стол, открытый
// дашбордом, не остановится по простою (studio/desk_keeper.py).
// Ядро `createMontageFeed` — без DOM и таймеров, его проверяют тесты;
// обёртка ниже вешает таймер и шлёт `studio:montage-updated`.

import { getMontage } from "./montage-api.js";

export const POLL_MS = 5000;

export function createMontageFeed({ load, notify }) {
  let projectId = null;
  let entry = null;
  let inFlight = null;

  function needsModel(body, known) {
    return Boolean(body) && body.applicable !== false && body.exists === true
      && body.engine?.state === "installed" && known?.index_key !== body.index_key;
  }

  async function tick() {
    if (!projectId || inFlight === projectId) return;
    const id = projectId;
    inFlight = id;
    try {
      const status = await load(id, "");
      if (projectId !== id) return;
      const next = { status: status.ok ? status.body : entry?.status || null,
        model: entry?.model || null, error: status.ok ? null : status };
      if (status.ok && needsModel(status.body, next.model)) {
        const model = await load(id, "model");
        if (projectId !== id) return;
        if (model.ok) next.model = model.body;
        else next.error = model;
      }
      const changed = JSON.stringify(next) !== JSON.stringify(entry);
      entry = next;
      if (changed) notify(id);
    } finally {
      if (inFlight === id) inFlight = null;
    }
  }

  return {
    show(id) {
      if (id !== projectId) {
        projectId = id;
        entry = null;
      }
    },
    hide() {
      projectId = null;
      entry = null;
    },
    tick,
    current(id) {
      return id && id === projectId ? entry : null;
    },
    active() {
      return projectId;
    },
  };
}

// --- Обёртка страницы -------------------------------------------------

const feed = createMontageFeed({
  load: (id, part) => getMontage(id, part),
  notify: (id) => document.dispatchEvent(new CustomEvent("studio:montage-updated", {
    bubbles: true, detail: { projectId: id },
  })),
});
let timer = null;

function visible() {
  return typeof document === "undefined" || document.visibilityState === "visible";
}

/** Экран «Сборка» проекта на экране: начать (или продолжить) опрос. */
export function showMontage(projectId) {
  const fresh = feed.active() !== projectId;
  feed.show(projectId);
  if (!timer) timer = setInterval(() => { if (visible()) feed.tick(); }, POLL_MS);
  if (fresh) feed.tick();
}

/** Другой экран или фото-проект — опрос не нужен. */
export function hideMontage() {
  feed.hide();
  if (timer) {
    clearInterval(timer);
    timer = null;
  }
}

/** Что известно о монтаже проекта: `{status, model, error}` или `null`. */
export function montageState(projectId) {
  return feed.current(projectId);
}

/** Спросить сейчас: после «Сделать текущей», открытия стола, возврата на вкладку. */
export function refreshMontage() {
  return feed.tick();
}
