// Renders the left project rail: brand, search, filters, project index and
// the small channel link. Cross-module signals it emits (all on `document`,
// bubbling): `studio:project-selected`, `studio:filter-changed`,
// `studio:query-changed`. Filter/query text themselves live in the shared
// store (app.js owns writing them back) — this module only reads them and
// reports interaction; it never resets them itself.
//
// The skeleton (brand/search/filters/list container) is built exactly once
// per root element and cached on the node; every later call only patches
// the dynamic parts. Rebuilding the whole subtree on every store commit
// would destroy the search input mid-keystroke and drop keyboard focus
// from a project button the instant its row is selected.

import {
  displayProjectTitle,
  filterProjects,
  PROJECT_FILTERS,
  resolveTypeLabel,
  STAGE_LABELS,
} from "./state.js";

const FILTER_LABELS = Object.freeze({
  all: "Все",
  active: "Активные",
  review: "На проверке",
  done: "Завершённые",
});

function selectProject(projectId) {
  document.dispatchEvent(
    new CustomEvent("studio:project-selected", {
      detail: { projectId },
      bubbles: true,
    }),
  );
}

function emitFilterChanged(filter) {
  document.dispatchEvent(
    new CustomEvent("studio:filter-changed", { detail: { filter }, bubbles: true }),
  );
}

function emitQueryChanged(query) {
  document.dispatchEvent(
    new CustomEvent("studio:query-changed", { detail: { query }, bubbles: true }),
  );
}

function buildSkeleton(root) {
  root.textContent = "";

  const brand = document.createElement("div");
  brand.className = "rail-brand";
  const name = document.createElement("span");
  name.textContent = "AI Мастерская";
  brand.append(name);

  const searchWrap = document.createElement("div");
  searchWrap.className = "rail-search";
  // Visible label: the placeholder alone is too pale to carry the field's
  // purpose at WCAG AA contrast, so the caption must be real, shown text.
  const searchLabel = document.createElement("label");
  searchLabel.className = "rail-search-label";
  searchLabel.setAttribute("for", "rail-search-input");
  searchLabel.textContent = "Поиск проектов";
  const searchInput = document.createElement("input");
  searchInput.type = "search";
  searchInput.id = "rail-search-input";
  // No placeholder: the visible label above already names the field, and a
  // placeholder here would either duplicate it or risk shipping text that
  // can't clear WCAG AA contrast at the placeholder's necessarily muted
  // color (measured 2.94:1 in review).
  searchWrap.append(searchLabel, searchInput);
  searchInput.addEventListener("input", () => emitQueryChanged(searchInput.value));

  const filterGroup = document.createElement("div");
  filterGroup.className = "rail-filters";
  filterGroup.setAttribute("role", "group");
  filterGroup.setAttribute("aria-label", "Фильтр проектов");
  const filterButtons = new Map();
  for (const filter of PROJECT_FILTERS) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = FILTER_LABELS[filter];
    button.dataset.filter = filter;
    button.setAttribute("aria-pressed", "false");
    button.addEventListener("click", () => emitFilterChanged(filter));
    filterButtons.set(filter, button);
    filterGroup.append(button);
  }

  const listRegion = document.createElement("div");
  listRegion.className = "rail-list-region";
  const list = document.createElement("ul");
  list.className = "rail-list";
  const emptyMessage = document.createElement("p");
  emptyMessage.className = "rail-empty";
  emptyMessage.hidden = true;
  listRegion.append(list, emptyMessage);

  const footer = document.createElement("div");
  footer.className = "rail-footer";
  const channelLink = document.createElement("a");
  channelLink.className = "rail-channel-link";
  channelLink.href = "https://t.me/masterskaya_video";
  channelLink.target = "_blank";
  channelLink.rel = "noreferrer noopener";
  channelLink.textContent = "Канал";
  footer.append(channelLink);

  root.append(brand, searchWrap, filterGroup, listRegion, footer);
  return { searchInput, filterButtons, list, emptyMessage };
}

/**
 * Which project id (if any) should regain keyboard focus after the list is
 * rebuilt. Pure decision, factored out of the DOM lookup below, so the
 * seam -- "did the project that held focus survive this filter/query
 * commit" -- is directly testable without a DOM: a project that dropped
 * out of `visibleProjects` (e.g. a filter change hid it) is never a
 * refocus target, and `focusedProjectId` itself is returned unchanged
 * otherwise.
 */
export function resolveRefocusProjectId(visibleProjects, focusedProjectId) {
  if (!focusedProjectId) {
    return null;
  }
  const list = Array.isArray(visibleProjects) ? visibleProjects : [];
  const stillVisible = list.some((project) => project?.id === focusedProjectId);
  return stillVisible ? focusedProjectId : null;
}

function paintList(refs, projects, filter, query, selectedProjectId) {
  const { list, emptyMessage } = refs;

  // A project button may currently hold keyboard focus (the user just
  // activated it, or tabbed onto it). Rebuilding the list below always
  // destroys that node; remember which project it belonged to so an
  // equivalent, freshly built button can take focus back afterward.
  const active = document.activeElement;
  const focusedProjectId =
    active instanceof HTMLElement && list.contains(active) && active.dataset.projectId
      ? active.dataset.projectId
      : null;

  list.textContent = "";
  const visible = filterProjects(projects, filter, query);
  const refocusProjectId = resolveRefocusProjectId(visible, focusedProjectId);

  if (visible.length === 0) {
    emptyMessage.textContent = projects.length === 0 ? "Проектов пока нет." : "Ничего не найдено.";
    emptyMessage.hidden = false;
    list.hidden = true;
    return;
  }
  emptyMessage.hidden = true;
  list.hidden = false;

  let refocusTarget = null;
  for (const project of visible) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "rail-project";
    if (project.id) {
      button.dataset.projectId = project.id;
    }
    if (project.id && project.id === selectedProjectId) {
      button.setAttribute("aria-current", "true");
    }
    const displayTitle = displayProjectTitle(project);
    const stageLabel = typeof project?.stage === "string"
      && Object.prototype.hasOwnProperty.call(STAGE_LABELS, project.stage)
      ? STAGE_LABELS[project.stage]
      : undefined;
    const typeLabel = resolveTypeLabel(project?.type);
    const metaParts = [typeLabel, stageLabel].filter(Boolean);
    const title = document.createElement("span");
    title.className = "rail-project-title";
    title.textContent = displayTitle;
    const meta = document.createElement("span");
    meta.className = "rail-project-meta";
    if (metaParts.length > 0) {
      meta.textContent = metaParts.join(" · ");
    }
    button.append(title, meta);
    // Explicit name: the nested title/status spans have no visible
    // separator between them, which would otherwise run together into one
    // word for assistive tech (e.g. "Ночной городАктивный"). An unknown
    // status never appears here since statusLabel is already allowlisted.
    button.setAttribute(
      "aria-label",
      metaParts.length > 0 ? `${displayTitle}, ${metaParts.join(", ")}` : displayTitle,
    );
    button.addEventListener("click", () => selectProject(project.id));
    item.append(button);
    list.append(item);
    if (project.id && project.id === refocusProjectId) {
      refocusTarget = button;
    }
  }
  if (refocusTarget) {
    refocusTarget.focus();
  }
}

/**
 * Render the project rail into `root` (the `#project-rail` element).
 * `state` is the shell's full view model; reads `projects`,
 * `selectedProjectId`, `filter` and `query`. Safe to call on every store
 * commit — only the list repaints; the search input and filter buttons are
 * built once and never recreated.
 */
export function renderProjectRail(root, state) {
  if (!root) {
    throw new TypeError("root is required");
  }
  const projects = Array.isArray(state?.projects) ? state.projects : [];
  const selectedProjectId = state?.selectedProjectId ?? null;
  const filter = state?.filter ?? "all";
  const query = state?.query ?? "";

  let refs = root.__railRefs;
  if (!refs) {
    refs = buildSkeleton(root);
    root.__railRefs = refs;
  }

  if (refs.searchInput.value !== query) {
    refs.searchInput.value = query;
  }
  for (const [key, button] of refs.filterButtons) {
    button.setAttribute("aria-pressed", String(key === filter));
  }

  paintList(refs, projects, filter, query, selectedProjectId);
}
