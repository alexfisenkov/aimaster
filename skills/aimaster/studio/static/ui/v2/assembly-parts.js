// Части экрана «Сборка», общие для фото и монтажа (хэндофф 2026-09-23):
// плашка «Ролик принят», превью ролика, карточка «Финальный ролик»,
// «История решений». Вынесены из screen-assembly.js без изменения вида;
// превью знает сторону кадра (`data-orientation`) — вертикальный ролик
// монтажа не сжимается в полосу 16:9. Экран монтажа перерисовывается по
// каждому ответу опроса — раскрытая «История решений» при этом не
// сворачивается (`historyOpen`).

import { formatHistoryEntries } from "../history-panel.js";
import { AUDIO_LAYERS } from "./audio-model.js";
import { playMark } from "./board-bits.js";
import { chatButton, clock, el, openViewer } from "./dom.js";
import { renderPreview } from "./preview.js";
import { assembleFinal, assembleLabel } from "./screen-prompts.js";
import { selectedResultVersion } from "./variants.js";

const MODE_WORDS = Object.freeze({ per_scene: "кадр за кадром", one_shot: "одним заходом" });

let historyOpen = false;

/** Длительность ролика по концу последней сцены, «00:30»; нет — «». */
export function sceneDuration(project) {
  const ends = (project?.scenes || []).map((scene) => scene?.end_ms).filter(Number.isFinite);
  return ends.length ? clock(Math.max(...ends)) : "";
}

/** Строки «ключ — значение» карточки «Финальный ролик». */
export function assemblyLines(project, { ready, finished }) {
  const scenes = (project?.scenes || []).length;
  const time = sceneDuration(project);
  const layers = AUDIO_LAYERS
    .filter((meta) => selectedResultVersion(project, { layer: meta.layer }))
    .map((meta) => meta.name.toLowerCase());
  return [
    { key: "Сцены", value: time ? `${scenes} · ${time}` : String(scenes) },
    { key: "Режим", value: MODE_WORDS[project?.gen_mode] || "кадр за кадром" },
    { key: "Звук", value: layers.length ? layers.join(", ") : "без звука" },
    { key: "Статус", value: finished ? "принят" : ready ? "ждёт вашего решения" : "ещё не собран" },
  ];
}

/** «Ролик принят. Проект завершён.» */
export function doneBanner() {
  const done = el("div", "v2-done");
  done.dataset.hook = "v2-done";
  const mark = el("span", "v2-done-mark", "✓");
  mark.setAttribute("aria-hidden", "true");
  done.append(mark, el("span", "", "Ролик принят. Проект завершён."));
  return done;
}

/** Превью ролика: первый кадр, «▶», статус и длительность; нажатие — просмотрщик. */
export function finalPreview(project, { ready, statusText, durationText = "", orientation = "landscape" }) {
  const assembly = project?.assembly && typeof project.assembly === "object" ? project.assembly : null;
  const button = el("button", "v2-final-preview");
  button.type = "button";
  button.dataset.hook = "v2-final-slot";
  button.dataset.ready = String(ready);
  button.dataset.orientation = orientation;
  button.setAttribute("aria-label", ready ? "Открыть финальный ролик" : "Финального ролика пока нет");
  button.disabled = !ready;
  button.append(renderPreview(ready ? assembly : null,
    { kind: ready ? "video" : "none", label: "Финальный ролик", emptyText: "ролик ещё не собран" }));
  if (ready) button.append(playMark("v2-play v2-play-big"));
  button.append(el("span", "v2-final-status", statusText));
  if (durationText) button.append(el("span", "v2-final-duration", durationText));
  button.addEventListener("click", () => openViewer(
    { kind: "assembly", id: "final" }, { tab: "video", trigger: button },
  ));
  return button;
}

/** Карточка «Финальный ролик»: что в нём и кнопка сборки в чат. */
export function summaryCard(project, revision, state) {
  const card = el("section", "v2-card v2-final");
  card.dataset.hook = "v2-final";
  card.append(el("h2", "v2-card-title", "Финальный ролик"));
  const list = el("dl", "v2-kv");
  for (const line of assemblyLines(project, state)) {
    const row = el("div", "v2-kv-row");
    row.append(el("dt", "", line.key), el("dd", "", line.value));
    list.append(row);
  }
  card.append(list);
  const summary = typeof project?.assembly?.summary === "string" ? project.assembly.summary.trim() : "";
  if (summary) card.append(el("p", "v2-final-summary", summary));
  card.append(chatButton(assembleLabel(project), assembleFinal(project, revision),
    "v2-chat-button v2-card-button"));
  return card;
}

/** «История решений»: тот же разбор записей, что у панели истории v1. */
export function historyBlock(project) {
  const entries = formatHistoryEntries(project?.history);
  const box = el("details", "v2-card v2-history");
  box.dataset.hook = "v2-history";
  box.open = historyOpen;
  box.addEventListener("toggle", () => { historyOpen = box.open; });
  const summary = el("summary", "v2-history-summary");
  summary.append(
    el("span", "v2-history-title", `История решений · ${entries.length}`),
    el("span", "v2-history-toggle v2-when-closed", "показать"),
    el("span", "v2-history-toggle v2-when-open", "скрыть"),
  );
  box.append(summary);
  if (!entries.length) {
    box.append(el("p", "v2-section-hint", "Решений пока нет."));
    return box;
  }
  const list = el("ol", "v2-history-list");
  for (const entry of entries) {
    const row = el("li", "v2-history-row");
    row.dataset.actor = entry.actor;
    row.append(el("span", "v2-history-actor", entry.actorLabel), el("span", "v2-history-text", entry.text));
    list.append(row);
  }
  box.append(list);
  return box;
}
