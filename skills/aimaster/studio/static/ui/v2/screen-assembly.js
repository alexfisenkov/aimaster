// Экран «Сборка» (спецификация §3.5): плитка финального ролика, «Собрать
// → чат», «История решений» и одна главная кнопка внизу. Скачивания тут
// пока нет — оно отдельной работой после этой ветки.

import { formatHistoryEntries } from "../history-panel.js";
import { chatButton, el, openViewer } from "./dom.js";
import { renderFooter } from "./footer.js";
import { assembleFinal } from "./screen-prompts.js";

/** Плитка финального ролика: что с ним сейчас и как его открыть. */
function finalTile(project) {
  const assembly = project?.assembly && typeof project.assembly === "object" ? project.assembly : null;
  const ready = typeof assembly?.asset_url === "string" && assembly.asset_url.startsWith("/assets/");
  const box = el("section", "v2-final");
  box.dataset.hook = "v2-final";
  const button = el("button", "v2-big-slot");
  button.type = "button";
  button.dataset.hook = "v2-final-slot";
  button.dataset.ready = String(ready);
  button.setAttribute("aria-label", ready ? "Открыть финальный ролик" : "Финального ролика пока нет");
  button.append(el("span", "v2-big-slot-label", ready ? "▶ Финальный ролик" : "Ролик ещё не собран"));
  button.disabled = !ready;
  button.addEventListener("click", () => openViewer(
    { kind: "assembly", id: "final" }, { tab: "video", trigger: button },
  ));
  box.append(button);
  const summary = typeof assembly?.summary === "string" ? assembly.summary.trim() : "";
  box.append(el("p", "v2-section-hint", ready
    ? summary || "Готовый файл собран. Откройте его и проверьте."
    : "Собранного ролика пока нет — соберите его через чат."));
  return { box, ready };
}

/** «История решений»: тот же разбор записей, что у панели истории v1. */
function historyBlock(project) {
  const entries = formatHistoryEntries(project?.history);
  const box = el("details", "v2-history");
  box.dataset.hook = "v2-history";
  box.append(el("summary", "v2-history-summary", `История решений · ${entries.length}`));
  if (!entries.length) {
    box.append(el("p", "v2-section-hint", "Решений пока нет."));
    return box;
  }
  const list = el("ol", "v2-history-list");
  for (const entry of entries) {
    const row = el("li", "v2-history-row");
    row.dataset.actor = entry.actor;
    row.append(el("span", "", entry.text), el("span", "v2-history-actor", entry.actorLabel));
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
  const final = finalTile(project);
  const head = el("div", "v2-screen-head");
  head.append(el("h2", "v2-section-title", "Сборка"));
  head.append(chatButton(
    final.ready ? "Пересобрать → чат" : "Собрать → чат",
    assembleFinal(project, snapshot.revision, { ready: final.ready }),
  ));
  surface.append(head, final.box, historyBlock(project), renderFooter(snapshot, { screen }));
  root.append(surface);
}
