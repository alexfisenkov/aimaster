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
  // `kind: image|video|audio` — событие v2 (`{version: 2, target, tab}`)
  // он молча пропускает. Это и нужно: пока просмотрщика v2 нет (волна 2),
  // старые экраны продолжают открывать свой лайтбокс, а клики v2 просто
  // ничего не открывают вместо того, чтобы открыть не то.
  attachViewerOpenListener();
  attachAgentPromptListener();

  const shellRoot = document.querySelector(".app-shell");
  const railRoot = document.querySelector('[data-hook="project-rail"]');
  const store = createStore();
  const pageUrl = new URL(window.location.href);
  const controller = createAppController({
    store,
    fetchSnapshot: (id) => fetchJson(`/api/projects/${encodeURIComponent(id)}/snapshot`),
    fetchProjects: () => fetchJson("/api/projects"),
    paintShell: (state) => renderShellV2(shellRoot, state),
    paintRail: (state) => renderProjectRail(railRoot, state),
    setActiveProject,
    reportFailure: (error) => store.setError({ code: error?.code || "unexpected_error" }),
    isDocumentVisible: () => document.visibilityState === "visible",
    preferredProjectId: pageUrl.searchParams.get("project"),
  });

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
