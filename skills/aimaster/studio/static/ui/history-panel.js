// Read-only rendering of the sanitized append-only project history.
// Unknown kinds/actors are omitted; raw enum values never reach the DOM.

import {
  MODE_LABELS,
  STAGE_LABELS,
  resolveLabel,
} from "./state.js";

const ACTOR_LABELS = Object.freeze({ you: "Вы", agent: "Агент" });
const SCENE_FIELD_LABELS = Object.freeze({
  text: "Описание кадра изменено",
  title: "Название кадра изменено",
  duration: "Длительность кадра изменена",
});
const REFERENCE_FIELD_LABELS = Object.freeze({
  name: "Имя референса изменено",
  source: "Источник референса изменён",
  voice_enabled: "Настройка голоса изменена",
});
const REFERENCE_ATTACHMENT_LABELS = Object.freeze({
  asset: "Файл референса добавлен",
  voice_asset: "Файл голоса добавлен",
});

function stageFact(entry, suffix) {
  const label = resolveLabel(STAGE_LABELS, entry?.stage);
  return label ? `${label} — ${suffix}` : null;
}

export const HISTORY_KIND_TEXT = Object.freeze({
  "stage-approved": (entry) => stageFact(entry, "шаг одобрен"),
  "stage-rework": (entry) => stageFact(entry, "нужны правки"),
  "stage-ready": (entry) => stageFact(entry, "готов к проверке"),
  "stage-blocked": (entry) => stageFact(entry, "ждёт уточнений"),
  "scenario-reopened": () => "Проект возвращён к сценарию",
  "scenario-edited": () => "Сценарий изменён",
  "scene-edited": (entry) => resolveLabel(SCENE_FIELD_LABELS, entry?.params?.field) || null,
  "scene-added": () => "Кадр добавлен",
  "scenes-reordered": () => "Порядок кадров изменён",
  "image-results-reordered": () => "Порядок изображений изменён",
  "video-results-reordered": () => "Порядок видео изменён",
  "prompt-edited": () => "Промпт изменён",
  accepted: () => "Материал принят",
  rejected: () => "Материалу нужны правки",
  hidden: () => "Материал скрыт",
  unhidden: () => "Материал снова показан",
  retired: () => "Материал убран из работы",
  restored: () => "Материал возвращён в работу",
  "reference-added": (entry) => {
    const tag = entry?.params?.tag;
    return typeof tag === "string" && tag ? `Референс ${tag} добавлен` : null;
  },
  "reference-edited": (entry) => resolveLabel(REFERENCE_FIELD_LABELS, entry?.params?.field) || null,
  "reference-attached": (entry) => resolveLabel(REFERENCE_ATTACHMENT_LABELS, entry?.params?.field) || null,
  "scene-reference-enabled": () => "Референс включён в кадр",
  "scene-reference-disabled": () => "Референс выключен в кадре",
  "mode-set": (entry) => {
    const mode = resolveLabel(MODE_LABELS, entry?.params?.mode);
    return mode ? `Режим работы: ${mode}` : null;
  },
  "result-ready": () => "Результат готов",
  "prompt-ready": () => "Промпт готов",
  "script-ready": () => "Сценарий готов",
  "scenes-ready": () => "Раскадровка готова",
  "assembly-ready": () => "Финал собран",
  "frame-plan-set": () => "План кадров изменён",
  "gen-mode-set": () => "Способ генерации изменён",
  "video-mode-set": () => "Способ оживления изменён",
  "continuity-set": () => "Связь с предыдущей сценой выбрана",
});

export function formatHistoryEntries(history) {
  const list = Array.isArray(history) ? history : [];
  const formatted = [];
  for (const entry of list) {
    const actorLabel = resolveLabel(ACTOR_LABELS, entry?.actor);
    const formatter = resolveLabel(HISTORY_KIND_TEXT, entry?.kind);
    if (!actorLabel || typeof formatter !== "function") {
      continue;
    }
    const text = formatter(entry);
    if (!text) {
      continue;
    }
    formatted.push({
      seq: entry.seq,
      actor: entry.actor,
      actorLabel,
      kind: entry.kind,
      text,
    });
  }
  return formatted;
}

export function applyHistoryBackgroundInert(root, open, isMobileLayout) {
  if (!root) {
    return;
  }
  const modal = open === true && isMobileLayout === true;
  const topbar = root.querySelector('[data-hook="topbar"]');
  const main = root.querySelector('[data-hook="main"]');
  const rail = root.querySelector('[data-hook="project-rail"]');
  const panel = root.querySelector('[data-hook="history-panel"]');
  if (topbar) {
    topbar.inert = modal;
  }
  if (main) {
    main.inert = modal;
  }
  if (modal && rail) {
    rail.inert = true;
  }
  if (panel) {
    panel.inert = open !== true;
  }
}

export function trapHistoryPanelTab(panel, event, isMobileLayout) {
  if (
    !panel ||
    panel.hidden ||
    isMobileLayout !== true ||
    event?.key !== "Tab"
  ) {
    return false;
  }
  const focusables = [];
  for (const selector of ["button", "a[href]", "input", "textarea", "select", '[tabindex="0"]']) {
    for (const node of panel.querySelectorAll(selector)) {
      if (!focusables.includes(node) && !node.disabled && !node.hidden) {
        focusables.push(node);
      }
    }
  }
  if (focusables.length === 0) {
    return false;
  }
  event.preventDefault();
  const current = focusables.indexOf(document.activeElement);
  const next =
    current < 0
      ? event.shiftKey
        ? focusables.length - 1
        : 0
      : (current + (event.shiftKey ? -1 : 1) + focusables.length) % focusables.length;
  focusables[next].focus();
  return true;
}

function buildHistoryEntry(entry) {
  const row = document.createElement("li");
  row.className = "history-entry";
  row.dataset.hook = "history-entry";
  row.dataset.actor = entry.actor;

  const dot = document.createElement("span");
  dot.className = "history-entry-dot";
  dot.setAttribute("aria-hidden", "true");
  const copy = document.createElement("span");
  copy.className = "history-entry-copy";
  const text = document.createElement("span");
  text.className = "history-entry-text";
  text.textContent = entry.text;
  const actor = document.createElement("span");
  actor.className = "history-entry-actor";
  actor.textContent = entry.actorLabel;
  copy.append(text, actor);
  row.append(dot, copy);
  return row;
}

export function renderHistoryPanel(root, { open = false, history = [] } = {}) {
  if (!root) {
    return false;
  }
  root.textContent = "";
  root.hidden = !open;
  root.inert = !open;
  root.setAttribute("aria-hidden", String(!open));
  if (!open) {
    return false;
  }

  const header = document.createElement("div");
  header.className = "history-panel-header";
  const heading = document.createElement("h2");
  heading.textContent = "История решений";
  const close = document.createElement("button");
  close.type = "button";
  close.className = "history-panel-close";
  close.dataset.hook = "history-close";
  close.setAttribute("aria-label", "Скрыть историю");
  close.textContent = "×";
  close.addEventListener("click", () => {
    document.dispatchEvent(new CustomEvent("studio:history-close", { bubbles: true }));
  });
  header.append(heading, close);

  const list = document.createElement("ol");
  list.className = "history-panel-list";
  list.dataset.hook = "history-list";
  const entries = formatHistoryEntries(history);
  if (entries.length === 0) {
    const empty = document.createElement("li");
    empty.className = "history-panel-empty";
    empty.dataset.hook = "history-empty";
    empty.textContent = "Решений пока нет";
    list.append(empty);
  } else {
    for (const entry of entries) {
      list.append(buildHistoryEntry(entry));
    }
  }

  const footer = document.createElement("p");
  footer.className = "history-panel-footer";
  footer.textContent =
    "Переписки с агентом здесь нет — дашборд показывает файлы проекта и фиксирует решения.";
  root.append(header, list, footer);
  list.scrollTop = list.scrollHeight;
  return true;
}
