// Pure, DOM-free client state for the AI Мастерская shell.
//
// Nothing here talks to the network or the document. `app.js` owns fetching
// snapshots and wiring DOM events; this module only holds the derived view
// model and the two allowlist rules that later tasks depend on:
//   1. stage tabs are exactly `completed_stages + current_stage`, in the
//      canonical stage order of the project's own type — never a future
//      stage, and never a stage the type does not have;
//   2. the project rail filter matches only the four documented values.

/**
 * Canonical workflow stage order, one list per project type (spec §18.2,
 * G12/G13): a video walks six steps, a photo four (no `motion`, no `audio`),
 * and there is no `qa` step in either. The server derives the stages
 * (`domain.VIDEO_STAGES`/`PHOTO_STAGES`); these lists only put a derived
 * set in display order and keep a photo from ever showing a video-only tab.
 * A `mixed` project walks the video stages (see `stageOrderFor`).
 */
export const STAGE_ORDER = Object.freeze({
  video: Object.freeze([
    "scenario",
    "image_plan",
    "image_results",
    "motion",
    "audio",
    "assembly",
  ]),
  photo: Object.freeze(["scenario", "image_plan", "image_results", "assembly"]),
});

/**
 * The stage order for a project type: `photo` gets the photo order,
 * everything else (`video`, `mixed`, or a type this build does not know) the
 * video one -- the longer list is the safe superset, since a tab still only
 * ever appears for a stage the server named.
 */
export function stageOrderFor(projectType) {
  return projectType === "photo" ? STAGE_ORDER.photo : STAGE_ORDER.video;
}

/** Exact stage copy from the design mockup (spec §18.2) — never invent a new label here. */
export const STAGE_LABELS = Object.freeze({
  scenario: "Сценарий",
  image_plan: "Кадры и промпты",
  image_results: "Изображения",
  motion: "Видео",
  audio: "Звук",
  assembly: "Сборка",
});

/** The only four rail filters the spec names. */
export const PROJECT_FILTERS = Object.freeze(["all", "active", "review", "done"]);

/**
 * Every `data-hook` name that identifies a scene-linked, focus-preservable
 * control -- the one shared definition ui/shell.js's focus capture/restore
 * and ui/timeline.js's auto-scroll both read (repair 2026-09-17, ticket 06
 * condition 10: "Список фокус-хуков... по одному общему определению" --
 * before this, shell.js and timeline.js each kept their own, silently
 * divergible copy). `pane` is `"scenario"|"timeline"` for the two
 * selection triggers `shouldAutoScroll` reasons about; `null` for the two
 * scene-edit-form fields (ui/scenario.js's `buildEditControl`'s textarea/
 * reason input), which never themselves originate a scene selection and so
 * never participate in auto-scroll -- only in focus restoration across a
 * repaint (ticket 06 condition 4: a commit that repaints `main` while an
 * edit form is focused must not strand focus on `<body>`).
 */
// `media-scene-tag` (second repair, 2026-09-17, ticket 06 condition 5): a
// scene tag button can live in the inspector (a prompt/reference item,
// ui/media.js's `buildSceneTag`) rather than in `main` -- `pane: null`
// because, like the two edit-form fields below, it never itself
// originates the kind of selection `shouldAutoScroll` reasons about via
// `pane` (it dispatches `origin: "media"`, not "scenario"/"timeline"); it
// only needs to survive `ui/shell.js`'s focus capture/restore.
// `scenario-edit-save`/`scenario-edit-cancel` (second repair, 2026-09-17,
// ticket 06 condition 4): the edit form's own two buttons, alongside its
// textarea/reason fields -- a keyboard user who tabs to "Сохранить" and
// activates it with Enter/Space holds focus there through the submit, not
// necessarily in the textarea.
// `scenario-edit-toggle` (repair 1, 2026-09-17, ticket 14: review's own
// "«Править»" among the six control types a background poll dropped focus
// from): the collapsed edit form's own "Править" button -- an operator who
// has not yet opened the form at all was still focused on this exact
// button when an unrelated repaint tore it down and rebuilt it fresh.
export const SCENE_FOCUS_HOOKS = Object.freeze([
  Object.freeze({ hook: "scenario-block-select", pane: "scenario" }),
  Object.freeze({ hook: "timeline-entry", pane: "timeline" }),
  Object.freeze({ hook: "scenario-edit-toggle", pane: null }),
  Object.freeze({ hook: "scenario-edit-textarea", pane: null }),
  Object.freeze({ hook: "scenario-edit-reason", pane: null }),
  Object.freeze({ hook: "scenario-edit-save", pane: null }),
  Object.freeze({ hook: "scenario-edit-cancel", pane: null }),
  Object.freeze({ hook: "media-scene-tag", pane: null }),
]);

/**
 * One shared status dictionary reused by the rail's per-project status and
 * the top bar's status pill, so the two surfaces never diverge on wording
 * and a raw token never reaches the screen. Keyed on `project.status` --
 * the project-level field `/api/projects` and `active_project` actually
 * carry (see tests/creator_studio/test_http_api.py's fixture) -- which is
 * a wholly different vocabulary from the per-stage `view_stage.gate_status`
 * (draft/ready/approved/blocked). `gate_status` never reaches this
 * dictionary: it is surfaced by the stage area and the "Нужен ответ"
 * notice instead (see ui/shell.js), never as a second, competing status
 * label. An unrecognized `project.status` resolves to `undefined` here and
 * is therefore only reachable through the "all" filter, with no label.
 */
export const STATUS_LABELS = Object.freeze({
  active: "Активный",
  review: "На проверке",
  done: "Завершён",
});

/**
 * Creative mode is display-only and comes from chat, never chosen here.
 * Only these two raw tokens are known; anything else must not render —
 * not the raw token, not a generic fallback.
 */
export const MODE_LABELS = Object.freeze({
  guided: "С уточнениями",
  autopilot: "Автоматически",
});

/** Project result type — the only three the domain allows. */
export const TYPE_LABELS = Object.freeze({
  photo: "Фото",
  video: "Видео",
  mixed: "Фото и видео",
});

/**
 * Look up `key` in an allowlist dictionary, returning `undefined` for
 * anything that is not the dictionary's own enumerable property — including
 * names every plain object inherits from `Object.prototype`
 * (`constructor`, `__proto__`, `toString`, `hasOwnProperty`, …). Without
 * this guard, `SOME_DICT["constructor"]` resolves to the built-in `Object`
 * function rather than `undefined`, so a raw value that happens to equal
 * one of those names would render a function instead of nothing. Every
 * resolve*Label function below — and `ui/media.js`'s
 * `resolveMediaStatusLabel`, which imports this instead of keeping its own
 * copy — goes through this one function, so the safety property only has
 * to be proven once.
 */
export function resolveLabel(dict, key) {
  if (typeof key !== "string" || !Object.prototype.hasOwnProperty.call(dict, key)) {
    return undefined;
  }
  return dict[key];
}

/**
 * Resolve one allowlisted label, or `undefined` for anything unrecognized.
 * Callers must treat `undefined` as "render nothing" — never fall back to
 * the raw input.
 */
export function resolveStatusLabel(status) {
  return resolveLabel(STATUS_LABELS, status);
}

export function resolveModeLabel(mode) {
  return resolveLabel(MODE_LABELS, mode);
}

export function resolveTypeLabel(type) {
  return resolveLabel(TYPE_LABELS, type);
}

/**
 * A project's display title, or a neutral placeholder when it is missing —
 * never the technical id, which is not a human title.
 */
export function displayProjectTitle(project) {
  const title = project && typeof project.title === "string" ? project.title.trim() : "";
  return title || "Без названия";
}

/**
 * Turn a server-derived `view_stage` into the ordered tab list the shell may
 * render. Only stages present in `completed_stages` or equal to
 * `current_stage` ever appear — any other stage is a future stage and is
 * never fabricated here, independent of what the caller passes in — and only
 * stages of the project's own type (`projectType`, see `stageOrderFor`): a
 * photo never gets a `motion` or `audio` tab, whatever `view_stage` says.
 */
export function deriveStageTabs(viewStage, projectType) {
  if (!viewStage || typeof viewStage !== "object") {
    return [];
  }
  const completed = Array.isArray(viewStage.completed_stages)
    ? viewStage.completed_stages
    : [];
  const current = viewStage.current_stage;
  const allowed = new Set(completed);
  if (typeof current === "string") {
    allowed.add(current);
  }
  return stageOrderFor(projectType).filter((stage) => allowed.has(stage)).map((stage) => ({
    stage,
    label: STAGE_LABELS[stage],
    completed: completed.includes(stage),
    current: stage === current,
  }));
}

/**
 * Filter a project index by rail filter and optional title search text.
 * Each named filter (`active`/`review`/`done`) matches `project.status`
 * directly -- the filter ids in `PROJECT_FILTERS` and the values
 * `project.status` actually carries are the same three words, so no
 * separate group-membership table is needed. `all`/omitted filter returns
 * every status, including one outside this vocabulary; an empty/omitted
 * query does no text filtering. Pure and DOM-free so rail.js never needs
 * its own copy of this logic.
 */
export function filterProjects(projects, filter, query) {
  const list = Array.isArray(projects) ? projects : [];
  let result =
    filter && filter !== "all"
      ? list.filter((project) => project && project.status === filter)
      : list.slice();
  const normalizedQuery = typeof query === "string" ? query.trim().toLowerCase() : "";
  if (normalizedQuery) {
    result = result.filter((project) =>
      String(project?.title ?? "").toLowerCase().includes(normalizedQuery),
    );
  }
  return result;
}

function initialState() {
  return {
    status: "loading",
    projects: [],
    filter: "all",
    query: "",
    selectedProjectId: null,
    snapshot: null,
    stageTabs: [],
    viewedStage: null,
    historyOpen: false,
    error: null,
    // Task 06: the one field that drives the bidirectional scenario<->
    // timeline<->materials link (spec §7). `selectedSceneOrigin` names
    // which surface ("scenario"|"timeline"|"media") made the selection, so
    // the *other* surface knows it is the one allowed to auto-scroll (see
    // ui/timeline.js's `shouldAutoScroll`) -- never the surface the user
    // just clicked in, whose own scroll position/focus must not move.
    selectedSceneId: null,
    selectedSceneOrigin: null,
  };
}

/**
 * Whether a previously selected scene id still names a real scene in the
 * *new* snapshot's `active_project.scenes` -- `true` when `scenes` is
 * absent too (nothing to contradict a selection with yet, e.g. a snapshot
 * still loading), so a selection is only ever dropped on an actual
 * mismatch, never merely because scenes haven't arrived in this particular
 * payload. Pure and DOM-free so `replaceSnapshot`'s own defensive reset
 * (a scene a `reorder`/stage regression removed must not keep highlighting
 * a block that no longer exists) is directly testable.
 */
export function sceneStillExists(snapshot, selectedSceneId) {
  if (!selectedSceneId) {
    return false;
  }
  const scenes = snapshot?.active_project?.scenes;
  if (!Array.isArray(scenes)) {
    return true;
  }
  return scenes.some((scene) => scene && scene.scene_id === selectedSceneId);
}

/**
 * Create the shell's single store. Every mutation returns the new state and
 * notifies subscribers synchronously; there is no hidden async scheduling.
 */
export function createStore(initial) {
  let state = { ...initialState(), ...(initial && typeof initial === "object" ? initial : {}) };
  const listeners = new Set();

  function commit(next) {
    state = next;
    for (const listener of listeners) {
      listener(state);
    }
    return state;
  }

  return {
    getState() {
      return state;
    },
    subscribe(listener) {
      if (typeof listener !== "function") {
        throw new TypeError("listener must be a function");
      }
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    setStatus(status) {
      return commit({ ...state, status });
    },
    setProjects(projects) {
      return commit({
        ...state,
        projects: Array.isArray(projects) ? projects.slice() : [],
      });
    },
    setFilter(filter) {
      const next = PROJECT_FILTERS.includes(filter) ? filter : "all";
      return commit({ ...state, filter: next });
    },
    /** Free-text rail search; kept in the store so it survives a project
     * switch or snapshot re-render instead of living inside rail.js. */
    setQuery(query) {
      return commit({ ...state, query: typeof query === "string" ? query : "" });
    },
    setViewedStage(stage) {
      const available = state.stageTabs.some((tab) => tab.stage === stage);
      return available ? commit({ ...state, viewedStage: stage }) : state;
    },
    setHistoryOpen(open) {
      return commit({ ...state, historyOpen: open === true });
    },
    /** Begin loading a newly chosen project; drops the previous snapshot
     * and any scene selection -- a scene id belongs to the project that had
     * it selected, never carried over into a different one. */
    selectProject(id) {
      return commit({
        ...state,
        selectedProjectId: id,
        status: "loading",
        snapshot: null,
        stageTabs: [],
        viewedStage: null,
        error: null,
        selectedSceneId: null,
        selectedSceneOrigin: null,
      });
    },
    clearProjectSelection(status = "choose") {
      return commit({
        ...state,
        selectedProjectId: null,
        status,
        snapshot: null,
        stageTabs: [],
        viewedStage: null,
        error: null,
        selectedSceneId: null,
        selectedSceneOrigin: null,
      });
    },
    /**
     * Adopt a freshly fetched `/api/projects/{id}/snapshot` payload. A
     * `gate_status` of `blocked` surfaces as shell status `blocked` so the
     * blocked empty-state renders instead of stage content. A scene
     * selection that no longer names a real scene in this snapshot (a
     * stage regression, a `reorder`) is dropped rather than kept pointing
     * at nothing -- see `sceneStillExists`.
     */
    replaceSnapshot(snapshot) {
      const viewStage =
        snapshot && typeof snapshot === "object" ? snapshot.view_stage : null;
      const activeProject =
        snapshot && typeof snapshot === "object" ? snapshot.active_project : null;
      const keepSelection = sceneStillExists(snapshot, state.selectedSceneId);
      const nextStageTabs = deriveStageTabs(
        viewStage,
        activeProject ? activeProject.type : undefined,
      );
      const previousProjectId = state.snapshot?.active_project?.id ?? state.selectedProjectId;
      const nextProjectId = activeProject?.id ?? state.selectedProjectId;
      const previousCurrentStage = state.snapshot?.view_stage?.current_stage;
      const nextCurrentStage = viewStage?.current_stage;
      const keepViewedStage =
        previousProjectId === nextProjectId &&
        previousCurrentStage === nextCurrentStage &&
        nextStageTabs.some((tab) => tab.stage === state.viewedStage);
      const nextProjects = Array.isArray(snapshot?.projects)
        ? snapshot.projects.slice()
        : state.projects;
      return commit({
        ...state,
        status: viewStage && viewStage.gate_status === "blocked" ? "blocked" : "ready",
        projects: nextProjects,
        snapshot: snapshot || null,
        stageTabs: nextStageTabs,
        viewedStage: keepViewedStage
          ? state.viewedStage
          : typeof nextCurrentStage === "string"
            ? nextCurrentStage
            : null,
        selectedProjectId:
          activeProject && activeProject.id ? activeProject.id : state.selectedProjectId,
        error: null,
        selectedSceneId: keepSelection ? state.selectedSceneId : null,
        selectedSceneOrigin: keepSelection ? state.selectedSceneOrigin : null,
      });
    },
    /**
     * Select (or, with a falsy `sceneId`, clear) the scene the scenario
     * block / timeline entry / media scene-tag surfaces link to. `origin`
     * names which of those three surfaces made the request (see
     * `initialState`'s doc comment); dropped to `null` together with the
     * selection itself when `sceneId` is falsy.
     */
    selectScene(sceneId, origin) {
      const next = typeof sceneId === "string" && sceneId ? sceneId : null;
      return commit({
        ...state,
        selectedSceneId: next,
        selectedSceneOrigin: next ? (typeof origin === "string" ? origin : null) : null,
      });
    },
    /**
     * Surface a sanitized fetch/transport failure without technical detail.
     * The last known snapshot/stageTabs are kept as-is: a failed retry must
     * not roll back the gate the server already granted (spec §9).
     */
    setError(error) {
      return commit({
        ...state,
        status: "error",
        error: error || null,
      });
    },
  };
}
