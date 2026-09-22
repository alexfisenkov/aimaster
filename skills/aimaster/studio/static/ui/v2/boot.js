// Запуск оболочки v2: тот же стор, тот же контроллер и тот же реальный
// loopback-API, что у v1 (`ui/state.js`, `ui/app-controller.js`,
// `ui/actions.js`) — меняется только то, чем рисуется главная область.
// Ничего из v1 не удалено: старый вход живёт в `static/app-v1.js` и
// открывается по `?ui=v1`.

import { createStore } from "../state.js";
import { renderProjectRail } from "../rail.js";
import { setActiveProject } from "../actions.js";
import { createAppController } from "../app-controller.js";
import { attachViewerOpenListener } from "../viewer.js";
import { attachAgentPromptListener } from "../chat-prompt-dialog.js";
import { renderShellV2, setViewedScreen } from "./shell.js";
import { attachViewerV2, repaintViewer } from "./viewer.js";

/**
 * Подключить таблицу стилей, если её ещё нет. `index.html` принадлежит
 * оболочке целиком, поэтому свои стили волна 2 добавляет отсюда — тегом
 * `<link>`, а не inline-правилами: CSP страницы их запрещает.
 * @param {string} href абсолютный путь вида `/static/styles/v2/viewer.css`
 */
export function ensureStylesheet(href) {
  if (document.querySelector(`link[rel="stylesheet"][href="${href}"]`)) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = href;
  document.head.append(link);
}

class StudioFetchError extends Error {
  constructor(code) {
    super(code);
    this.name = "StudioFetchError";
    this.code = code;
  }
}

async function fetchJson(path) {
  let response;
  try {
    response = await fetch(path, { headers: { Accept: "application/json" } });
  } catch {
    throw new StudioFetchError("network_error");
  }
  let body = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok) {
    throw new StudioFetchError(
      typeof body?.error?.code === "string" ? body.error.code : `http_${response.status}`,
    );
  }
  return body;
}

export function bootV2() {
  // Просмотрщик v1 слушает `studio:open-viewer` со строгим списком
  // `kind: image|video|audio` и событие v2 (`{version: 2, target, tab}`)
  // молча пропускает; просмотрщик v2 наоборот берёт только `version: 2`.
  // Поэтому оба слушателя висят рядом и не спорят за одно событие.
  attachViewerOpenListener();
  attachAgentPromptListener();
  ensureStylesheet("/static/styles/v2/viewer.css");

  const shellRoot = document.querySelector(".app-shell");
  const railRoot = document.querySelector('[data-hook="project-rail"]');
  const store = createStore();
  const pageUrl = new URL(window.location.href);
  const controller = createAppController({
    store,
    fetchSnapshot: (id) => fetchJson(`/api/projects/${encodeURIComponent(id)}/snapshot`),
    fetchProjects: () => fetchJson("/api/projects"),
    // Открытый просмотрщик перерисовывается тем же обновлением snapshot,
    // что и доска: после прямого решения он остаётся на месте и
    // показывает уже новое состояние, а не закрывается.
    //
    // Порядок важен: просмотрщик первый. Пока он открыт, доска под ним
    // закрыта модальным окном и нажать там нечего, значит листок
    // `studio:card-focus-pending` принадлежит ему — а спросивший первым
    // забрал бы его себе. Закрытый просмотрщик не спрашивает вовсе.
    paintShell: (state) => {
      repaintViewer();
      renderShellV2(shellRoot, state);
    },
    paintRail: (state) => renderProjectRail(railRoot, state),
    setActiveProject,
    reportFailure: (error) => store.setError({ code: error?.code || "unexpected_error" }),
    isDocumentVisible: () => document.visibilityState === "visible",
    preferredProjectId: pageUrl.searchParams.get("project"),
  });

  attachViewerV2(() => store.getState()?.snapshot || null);
  renderShellV2(shellRoot, store.getState());
  document.body.dataset.ui = "v2";

  document.addEventListener("studio:screen-viewed", (event) => {
    setViewedScreen(event?.detail?.screen);
    renderShellV2(shellRoot, store.getState());
  });
  document.addEventListener("studio:refresh-snapshot", (event) => {
    controller.requestRefresh(event?.detail?.projectId);
  });
  document.addEventListener("studio:project-selected", (event) => {
    const projectId = event?.detail?.projectId;
    if (typeof projectId !== "string" || !projectId) return;
    const nextUrl = new URL(window.location.href);
    nextUrl.searchParams.set("project", projectId);
    window.history.pushState({ projectId }, "", nextUrl);
    setViewedScreen(null);
    controller.openProject(projectId);
  });
  document.addEventListener("studio:retry-snapshot", () => {
    const { selectedProjectId } = store.getState();
    if (selectedProjectId) controller.openProject(selectedProjectId);
    else controller.loadProjectIndex();
  });
  document.addEventListener("visibilitychange", controller.refreshOnReturn);
  window.addEventListener("focus", controller.refreshOnReturn);
  setInterval(controller.pollLiveness, controller.liveness.periodMs);

  controller.loadProjectIndex();
}
