// Vertical timeline of video scene ranges -- the left-hand navigator that
// stays bidirectionally in sync with scenario.js's scene blocks through one
// shared field, the store's `selectedSceneId` (see ui/state.js). Photo
// projects never get an artificial timeline: `timelineModel` decides that
// purely from whether any scene actually carries a valid `start_ms`/
// `end_ms` range, never from `project.type` -- the same data-driven
// approach media-asset.js's own range formatting already uses.
//
// Pure view-model building (`timelineModel`, `resolveSceneOrder`,
// `resolveSceneRange`, `shouldAutoScroll`) is exercised directly by
// tests/ui/scenario-timeline.test.mjs. `renderTimeline` and
// `scrollSceneIntoView` touch the DOM and are verified only through the
// browser visual gate -- no DOM is available under `node --test` in this
// project (see tests/ui/focus-preservation.test.mjs's banner).
//
// Repair, 2026-09-17 (ticket 06 condition 10). `resolveRefocusSceneId`
// used to live here, tested directly but never actually called from any
// render path -- ui/shell.js's `captureSceneFocus`/`restoreSceneFocus`
// (a direct DOM query against the freshly rebuilt `main`, not a
// pre-computed "is it still visible" list) is what real focus restoration
// across a repaint goes through, for every scene-linked hook including
// this file's own timeline entries. A tested-but-unreachable function is
// worse than no function -- it looks like coverage of a real path while
// proving nothing about one -- so it was removed along with its tests
// rather than kept as unreachable inventory.

import { formatSceneRange } from "./media-asset.js";
import { SCENE_FOCUS_HOOKS } from "./state.js";

/**
 * A scene's display order: its own `order` field when present (server
 * numbers scenes from 1 after any `reorder`, per decision_reorder.py), the
 * scene's 1-based array position otherwise. Mirrors ui/media.js's
 * `buildSceneLabel` exactly so the same scene never shows two different
 * numbers across the timeline, the scenario blocks and the media gallery.
 */
export function resolveSceneOrder(scene, position) {
  return Number.isFinite(scene?.order) ? scene.order : position + 1;
}

/**
 * Defensive range validation for one scene: `{hasRange:false}` for a
 * missing, non-finite, negative or empty (end<=start) range -- never a
 * thrown error or a garbled label -- `{hasRange:true, startMs, endMs,
 * rangeLabel, overlapping}` otherwise. `projection.py` already refuses an
 * `end_ms<=start_ms` scene server-side and a photo scene may omit both
 * fields entirely by design, but this is the client's own second check
 * (defense in depth, the same posture `resolveAssetDisplayState`/
 * `formatDuration` already take elsewhere in this codebase) rather than
 * trusting every snapshot blindly. `overlapping` surfaces
 * `scene.overlap_scene_ids` (already computed upstream) explicitly, never
 * silently -- ticket 06's "явно маркирует overlaps".
 */
export function resolveSceneRange(scene) {
  const startMs = scene?.start_ms;
  const endMs = scene?.end_ms;
  const hasValidRange =
    Number.isFinite(startMs) && startMs >= 0 && Number.isFinite(endMs) && endMs > startMs;
  if (!hasValidRange) {
    return { hasRange: false };
  }
  const overlapIds = Array.isArray(scene?.overlap_scene_ids) ? scene.overlap_scene_ids : [];
  return {
    hasRange: true,
    startMs,
    endMs,
    rangeLabel: formatSceneRange(startMs, endMs),
    overlapping: overlapIds.length > 0,
  };
}

/**
 * Build the timeline's pure view model. `visible` is `false` -- and
 * `entries` empty -- whenever no scene has a valid range at all: stage 1
 * (no `scenes` key yet), a pure photo project (scenes without ms fields),
 * or a video project whose scenes are all still missing their range.
 * `renderTimeline` paints nothing at all in that case, so photo projects
 * never grow an artificial shell (spec: "без искусственной шкалы").
 */
export function timelineModel(snapshot, selectedSceneId) {
  const project = snapshot && typeof snapshot === "object" ? snapshot.active_project : null;
  const scenes = project && Array.isArray(project.scenes) ? project.scenes : undefined;
  if (!scenes) {
    return { visible: false, entries: [] };
  }
  const entries = scenes
    .map((scene, position) => {
      const range = resolveSceneRange(scene);
      const sceneId = typeof scene?.scene_id === "string" ? scene.scene_id : undefined;
      return {
        sceneId,
        order: resolveSceneOrder(scene, position),
        ...range,
        selected: Boolean(selectedSceneId) && sceneId === selectedSceneId,
      };
    })
    .filter((entry) => entry.hasRange && entry.sceneId);
  return { visible: entries.length > 0, entries };
}

/**
 * Whether `pane` ("scenario"|"timeline"|"media") should auto-scroll its
 * selected entry into view, given which pane originated the selection and
 * whether the visitor prefers reduced motion. The pane the user just
 * interacted with already has what they clicked in view (and, per spec
 * §10, must keep its own focus rather than have scroll position yanked out
 * from under it); only the *other* pane needs to catch up -- and never
 * automatically at all under reduced motion (spec §10: "автоматическая
 * прокрутка отключается при reduced motion").
 *
 * Second repair, 2026-09-17 (ticket 06 condition 2: "выбор с блока не
 * уводит блок с экрана... прокрутки к таймлайну нет"). The timeline pane
 * itself never auto-scrolls any more, regardless of which pane originated
 * the selection -- spec §2 only ever assigns scroll-and-highlight to a
 * *timeline* selection reaching the scenario block ("Выбор элемента
 * таймлайна прокручивает и подсвечивает блок сценария"); a *block*
 * selection only highlights the range and materials, it was never
 * supposed to scroll the timeline too. On narrow layouts, where the two
 * panes share one column (spec §10), scrolling the timeline into view
 * right after a block click carried that very block off screen -- the
 * opposite of "нажатый блок остаётся на экране". Desktop keeps the
 * timeline visible without any of this via plain CSS `position: sticky`
 * (styles/scenario.css), not a scroll call. Selecting *from* the timeline
 * still scrolls the scenario block, unchanged.
 */
export function shouldAutoScroll(pane, originPane, reducedMotion) {
  if (reducedMotion || !pane) {
    return false;
  }
  if (pane === "timeline") {
    return false;
  }
  return pane !== originPane;
}

// -----------------------------------------------------------------------
// DOM: selection dispatch, scroll sync, rendering. Browser-gate-only below
// this line -- see the file banner.
// -----------------------------------------------------------------------

/**
 * Ask the app to select `sceneId` (falsy clears the selection -- see
 * ticket 06 condition 7's "Все сцены" control), tagging which surface
 * originated the request (`shouldAutoScroll` reads this to decide which
 * *other* pane scrolls). Dispatches a bubbling `studio:scene-selected` DOM
 * event rather than calling the store directly -- the same cross-module
 * pattern ui/rail.js (`studio:project-selected`) and ui/media.js
 * (`studio:open-viewer`) already use, picked up once by app.js. Named
 * `requestSceneSelection`, not `selectScene` (repair 2026-09-17, ticket 06
 * condition 10): the old name was one keystroke away from -- and, in code
 * review, kept getting confused with -- `ui/state.js`'s store method of
 * the same name, which *applies* a selection rather than merely asking for
 * one. ui/scenario.js, ui/media.js and ui/viewer.js all import this one
 * function rather than each dispatching their own copy of the same event.
 */
export function requestSceneSelection(sceneId, origin) {
  document.dispatchEvent(
    new CustomEvent("studio:scene-selected", {
      bubbles: true,
      detail: { sceneId: typeof sceneId === "string" ? sceneId : null, origin: typeof origin === "string" ? origin : null },
    }),
  );
}

/**
 * Scroll every pane's own entry for `sceneId` into view, except the pane
 * named by `originPane` (see `shouldAutoScroll`). Called by ui/shell.js's
 * `renderShell`, *after* the scenario slot it operates on has actually been
 * inserted into the live document (repair 2026-09-17, ticket 06 condition
 * 3): calling this against a detached node -- as ui/scenario.js's own
 * `renderScenesLayout` used to, before its caller had appended anything
 * anywhere -- makes `scrollIntoView()` a silent no-op, which is exactly
 * why autoscroll never actually moved anything. Callers gate the call
 * itself on whether the selection genuinely changed (see
 * `shellZonesNeedRepaint`'s own test), so an unrelated repaint with the
 * same selection never re-triggers a scroll.
 */
export function scrollSceneIntoView(container, sceneId, originPane, reducedMotion) {
  if (!container || !sceneId) {
    return;
  }
  for (const { hook, pane } of SCENE_FOCUS_HOOKS) {
    if (!pane || !shouldAutoScroll(pane, originPane, reducedMotion)) {
      continue;
    }
    const selector = `[data-hook="${hook}"][data-scene-id="${CSS.escape(sceneId)}"]`;
    const el = container.querySelector(selector);
    if (el && typeof el.scrollIntoView === "function") {
      el.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }
}

/**
 * Render the vertical scene-range navigator into `root` (appended, not
 * replacing `root`'s own content -- scenario.js mounts this alongside its
 * own scenario panel inside one `.scenario-layout`). Returns `true` only
 * when it painted anything; a photo project or a pre-`image_plan` snapshot
 * gets no timeline DOM at all, matching `mediaCards`'s own
 * undefined-means-"not this stage" contract elsewhere in this codebase.
 */
export function renderTimeline(root, snapshot, selectedSceneId) {
  const model = timelineModel(snapshot, selectedSceneId);
  if (!model.visible) {
    return false;
  }

  const nav = document.createElement("nav");
  nav.className = "timeline-panel";
  nav.dataset.hook = "timeline-panel";
  nav.setAttribute("aria-label", "Таймлайн сцен");

  const list = document.createElement("ol");
  list.className = "timeline-list";
  for (const entry of model.entries) {
    const li = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "timeline-entry";
    button.dataset.hook = "timeline-entry";
    button.dataset.sceneId = entry.sceneId;
    button.dataset.selected = String(entry.selected);
    if (entry.selected) {
      button.setAttribute("aria-current", "true");
    }

    const order = document.createElement("span");
    order.className = "timeline-entry-order";
    order.textContent = String(entry.order);
    const range = document.createElement("span");
    range.className = "timeline-entry-range";
    range.textContent = entry.rangeLabel;
    button.append(order, range);

    if (entry.overlapping) {
      const warn = document.createElement("span");
      warn.className = "timeline-entry-overlap";
      warn.textContent = "Пересечение";
      button.append(warn);
    }

    const srLabel = document.createElement("span");
    srLabel.className = "visually-hidden";
    srLabel.textContent = entry.selected
      ? `Сцена ${entry.order}, ${entry.rangeLabel}, выбрана`
      : `Перейти к сцене ${entry.order}, ${entry.rangeLabel}`;
    button.append(srLabel);

    button.addEventListener("click", () => requestSceneSelection(entry.sceneId, "timeline"));
    li.append(button);
    list.append(li);
  }

  nav.append(list);
  root.append(nav);
  return true;
}
