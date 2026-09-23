// Экран «Сборка» (спецификация §3.5, хэндофф 2026-09-23): превью 16:9
// финального ролика, карточка «Финальный ролик» (строки ключ–значение и
// «Собрать заново → чат»), раскрывающаяся «История решений» и одна
// главная кнопка внизу. После принятия сверху плашка «Ролик принят».
// Заголовок экрана рисует оболочка. Скачивания тут пока нет — оно
// отдельной работой.

import { formatHistoryEntries } from "../history-panel.js";
import { AUDIO_LAYERS } from "./audio-model.js";
import { playMark } from "./board-bits.js";
import { chatButton, clock, el, openViewer } from "./dom.js";
import { footerMode, renderFooter } from "./footer.js";
import { assembleFinal } from "./screen-prompts.js";
import { selectedResultVersion } from "./variants.js";
import { videoThumb } from "./video-thumb.js";

const MODE_WORDS = Object.freeze({ per_scene: "кадр за кадром", one_shot: "одним заходом" });

/** Длительность ролика по концу последней сцены, «00:30»; нет — «». */
function duration(project) {
  const ends = (project?.scenes || []).map((scene) => scene?.end_ms).filter(Number.isFinite);
  return ends.length ? clock(Math.max(...ends)) : "";
}

/** Строки «ключ — значение» карточки «Финальный ролик». */
export function assemblyLines(project, { ready, finished }) {
  const scenes = (project?.scenes || []).length;
  const time = duration(project);
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

/** Превью 16:9: первый кадр ролика, «▶», статус и длительность. */
function preview(project, { ready, finished }) {
  const assembly = project?.assembly && typeof project.assembly === "object" ? project.assembly : null;
  const button = el("button", "v2-final-preview");
  button.type = "button";
  button.dataset.hook = "v2-final-slot";
  button.dataset.ready = String(ready);
  button.setAttribute("aria-label", ready ? "Открыть финальный ролик" : "Финального ролика пока нет");
  button.disabled = !ready;
  button.append(videoThumb(ready ? assembly.asset_url : null, "Финальный ролик"));
  if (ready) button.append(playMark("v2-play v2-play-big"));
  const status = el("span", "v2-final-status", finished ? "принят" : ready ? "ждёт вашего решения" : "ещё не собран");
  button.append(status);
  const time = duration(project);
  if (time) button.append(el("span", "v2-final-duration", time));
  button.addEventListener("click", () => openViewer(
    { kind: "assembly", id: "final" }, { tab: "video", trigger: button },
  ));
  return button;
}

/** Карточка «Финальный ролик»: что в нём и «Собрать заново → чат». */
function summaryCard(project, revision, state) {
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
  card.append(chatButton(
    state.ready ? "Собрать заново → чат" : "Собрать → чат",
    assembleFinal(project, revision, { ready: state.ready }),
    "v2-chat-button v2-card-button",
  ));
  return card;
}

/** «История решений»: тот же разбор записей, что у панели истории v1. */
function historyBlock(project) {
  const entries = formatHistoryEntries(project?.history);
  const box = el("details", "v2-card v2-history");
  box.dataset.hook = "v2-history";
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

/**
 * @param {HTMLElement} root куда рисовать (очищается)
 * @param {{state: object, screen?: string}} context `state.snapshot` — весь snapshot
 */
export function renderAssemblyScreen(root, { state, screen = "assembly" } = {}) {
  root.textContent = "";
  const snapshot = state?.snapshot;
  const project = snapshot?.active_project;
  const surface = el("div", "v2-screen v2-screen-assembly");
  surface.dataset.hook = "v2-screen-assembly";
  if (!project) {
    surface.setAttribute("aria-busy", "true");
    surface.append(el("p", "", "Загружаем сборку…"));
    root.append(surface);
    return;
  }
  const assetUrl = project.assembly?.asset_url;
  const ready = typeof assetUrl === "string" && assetUrl.startsWith("/assets/");
  const finished = footerMode(snapshot, { screen, stage: "assembly" }) === "done";
  if (finished) {
    const done = el("div", "v2-done");
    done.dataset.hook = "v2-done";
    const mark = el("span", "v2-done-mark", "✓");
    mark.setAttribute("aria-hidden", "true");
    done.append(mark, el("span", "", "Ролик принят. Проект завершён."));
    surface.append(done);
  }
  const layout = el("div", "v2-final-layout");
  const side = el("div", "v2-final-side");
  side.append(summaryCard(project, snapshot.revision, { ready, finished }), historyBlock(project));
  layout.append(preview(project, { ready, finished }), side);
  surface.append(layout, renderFooter(snapshot, { screen }));
  root.append(surface);
}
