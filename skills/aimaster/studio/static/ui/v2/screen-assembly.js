// Экран «Сборка» (спецификация §3.5; спецификация монтажа 2026-09-25,
// «Дашборд: экран «Сборка»»; хэндофф 2026-09-23 — вид). Фото-проект и
// старый итог без монтажа — как раньше: превью, карточка «Финальный ролик»,
// история решений. Видео и смешанный с монтажом — плашки, превью текущей
// версии, файл («Скачать», «Показать в папке», путь), главные кнопки
// («Открыть монтажный стол», «Собрать ролик → чат»), версии, схема слоёв,
// история. Живое состояние монтажа опрашивает montage-feed.js, пока этот
// экран открыт; как его читать — montage-entry.readEntry. Заголовок экрана
// рисует оболочка, подвал — renderFooter.

import { requestProjectRefresh } from "../card-forms.js";
import { doneBanner, finalPreview, historyBlock, sceneDuration, summaryCard } from "./assembly-parts.js";
import { el } from "./dom.js";
import { footerMode, renderFooter } from "./footer.js";
import { refusalText } from "./montage-api.js";
import { renderMainActions } from "./montage-desk.js";
import { readEntry } from "./montage-entry.js";
import { hideMontage, montageState, refreshMontage, showMontage } from "./montage-feed.js";
import { renderFileCard } from "./montage-file.js";
import { renderLayers } from "./montage-layers.js";
import {
  durationText, montageScreen, notices, orientation, screenFlags, versionLabel,
} from "./montage-model.js";
import { renderNotices } from "./montage-notices.js";
import { renderVersions } from "./montage-versions.js";
import { inTelegram, isPhone } from "./responsive.js";

function isReady(project) {
  const url = project?.assembly?.asset_url;
  return typeof url === "string" && url.startsWith("/assets/");
}

function onChanged(projectId) {
  requestProjectRefresh(projectId);
  refreshMontage();
}

function plainLayout(surface, snapshot, project, finished) {
  hideMontage();
  const ready = isReady(project);
  const layout = el("div", "v2-final-layout");
  const side = el("div", "v2-final-side");
  side.append(summaryCard(project, snapshot.revision, { ready, finished }), historyBlock(project));
  const statusText = finished ? "принят" : ready ? "ждёт вашего решения" : "ещё не собран";
  layout.append(finalPreview(project, { ready, statusText, durationText: sceneDuration(project) }), side);
  surface.append(layout);
}

function montageLayout(surface, snapshot, project, finished) {
  showMontage(project.id);
  // model — только свежая (плашки, длина); schema — и отставшая (рисунок слоёв).
  const { status, model, schema, lagging, error } = readEntry(montageState(project.id));
  const revision = snapshot.revision;
  const flags = screenFlags({ status, finished, phone: isPhone(), telegram: inTelegram() });
  const list = notices({ status, model, feedError: error ? refusalText(error) : null });
  // После «Принять ролик» монтаж не меняют: плашки остаются, кнопок в чат нет.
  if (list.length) surface.append(renderNotices(list, { project, revision, actions: flags.build }));
  const ready = isReady(project);
  const current = project?.montage?.current_version;
  const statusText = finished ? "принят" : ready && current ? `текущая ${versionLabel(current)}` : "ещё не собран";
  const top = el("div", "am-top");
  const side = el("div", "am-side");
  const actions = renderMainActions({ project, revision, status, flags });
  side.append(renderFileCard({ project, status, flags }));
  if (actions.childElementCount) side.append(actions); // после принятия кнопок нет — и пустого места тоже
  top.append(finalPreview(project, {
    ready, statusText,
    durationText: durationText({ status, model, project }),
    orientation: orientation(status?.canvas || project?.montage?.canvas),
  }), side);
  surface.append(top,
    renderVersions({ project, revision, flags, onChanged }),
    renderLayers({
      project, model: schema, engine: flags.engine, exists: status ? status.exists : null, lagging, error,
    }),
    historyBlock(project));
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
  const finished = footerMode(snapshot, { screen, stage: "assembly" }) === "done";
  if (finished) surface.append(doneBanner());
  const montage = montageScreen(project);
  surface.dataset.montage = String(montage);
  if (montage) montageLayout(surface, snapshot, project, finished);
  else plainLayout(surface, snapshot, project, finished);
  surface.append(renderFooter(snapshot, { screen }));
  root.append(surface);
}
