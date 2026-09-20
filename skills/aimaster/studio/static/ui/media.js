// Versioned prompts, role-grouped references and image/video result cards --
// task 07's slice of the dashboard (spec §2-§3, §7-§10). Pure view-model
// building lives here and is what tests/ui/media-viewer.test.mjs exercises
// directly; the DOM renderers at the bottom are thin and, like shell.js's
// paintMain/paintInspector, are only verified through the browser visual
// gate (no DOM implementation is available under `node --test` -- see
// interfaces.md's task-05 note, which this module follows exactly).
//
// This file never imports viewer.js: a card that wants the lightbox/player
// dispatches a bubbling `studio:open-viewer` DOM event instead (see
// `dispatchOpenViewer` below), which viewer.js's own
// `attachViewerOpenListener` (wired once from app.js) picks up. That keeps
// importing this module's pure functions -- exactly what the tests above
// do -- from ever loading viewer.js's DOM-only code as a side effect.
//
// Scope boundary: decisions (approve/reject/vary/regenerate/hide/retire)
// belong to task 08. Nothing here enqueues an action -- cards only display;
// `selectedSceneId` (task 06's scenario/timeline selection) is accepted
// defensively (any falsy value means "nothing selected") and only ever
// flips a presentational `selected` flag on each card, never filters what
// exists. Assembly's single combined deliverable is out of this file's
// scope (prompts, references, image/video results only) and is
// intentionally not rendered here.

import { resolveLabel, STAGE_LABELS } from "./state.js";
import {
  formatDuration,
  formatSceneRange,
  hasLoadableAsset,
  markAssetError,
  buildAssetPlaceholder,
} from "./media-asset.js";
import { requestSceneSelection, resolveSceneOrder, resolveSceneRange } from "./timeline.js";

export { formatDuration, formatSceneRange, hasLoadableAsset, markAssetError };

// -----------------------------------------------------------------------
// Reference roles
// -----------------------------------------------------------------------

/** Canonical role order, taken from spec §3's own listing -- "персонажем,
 * объектом, продуктом, стилем или локацией" -- i.e. character, object,
 * product, style, location. `assets.py`'s `REFERENCE_ROLES` is a Python
 * `frozenset` (unordered) and cannot be that source; this prose sentence is
 * the only place the codebase states an order at all, so this array follows
 * it exactly. */
export const REFERENCE_ROLE_ORDER = Object.freeze([
  "character",
  "object",
  "product",
  "style",
  "location",
]);

/** Allowlist labels only; an unrecognized role is dropped, never guessed. */
export const REFERENCE_ROLE_LABELS = Object.freeze({
  character: "Персонаж",
  product: "Продукт",
  style: "Стиль",
  object: "Объект",
  location: "Локация",
});

/**
 * Group a flat `references` list (snapshot's `active_project.references`)
 * by role, in the fixed canonical order, dropping empty groups and any item
 * whose role is not one of the five known values -- never a raw or guessed
 * label. Pure and DOM-free.
 */
export function groupReferences(references) {
  const list = Array.isArray(references) ? references : [];
  const byRole = new Map();
  for (const role of REFERENCE_ROLE_ORDER) {
    byRole.set(role, []);
  }
  for (const reference of list) {
    const role = reference && (reference.kind || reference.role);
    if (byRole.has(role)) {
      byRole.get(role).push(reference);
    }
  }
  const groups = [];
  for (const role of REFERENCE_ROLE_ORDER) {
    const items = byRole.get(role);
    if (items.length > 0) {
      groups.push({ role, label: REFERENCE_ROLE_LABELS[role], items });
    }
  }
  return groups;
}

// -----------------------------------------------------------------------
// Status labels -- routed through ui/state.js's one shared, own-keys-only
// resolver (`resolveLabel`) so the constructor/__proto__ safety property is
// proven in exactly one place, and every allowlist dictionary -- state.js's
// own three plus this one -- inherits it instead of each re-implementing
// its own `dict[key]` lookup.
// -----------------------------------------------------------------------

/**
 * Prompt/result lifecycle labels. The public snapshot's `status` field on
 * these records carries the same vocabulary `_PUBLIC_RESULT_STATUSES`
 * defines in projection.py (the only status vocabulary this system has);
 * an unrecognized value renders nothing rather than the raw token.
 */
export const MEDIA_STATUS_LABELS = Object.freeze({
  pending: "Ожидает",
  queued: "В очереди",
  running: "В работе",
  ready: "Готово",
  succeeded: "Готово",
  approved: "Принято",
  // Ticket 08 repair 2, craft finding 5: one token, one label, one
  // dictionary. A prompt's own status badge (this dictionary,
  // ui/card-decorate.js's decoratePromptCards -- a prompt writes its
  // decision straight into `status`, never a separate decisions-only
  // fact) and a result's own decision badge (ui/decision-history.js's
  // DECISION_VALUE_LABELS, via ui/card-decorate.js's buildCardDecisionBadge)
  // are two different surfaces for the exact same real-world event, so
  // they must read the same word -- "Нужны правки" (the concept's own
  // term), never this dictionary's own former "Отклонено".
  rejected: "Нужны правки",
  failed: "Ошибка",
  outcome_unknown: "Исход не подтверждён",
  needs_chat: "Нужно решение в чате",
  needs_chat_setup: "Нужна настройка в чате",
  available: "Доступно",
  unavailable: "Недоступно",
  complete: "Завершено",
});

export function resolveMediaStatusLabel(status) {
  return resolveLabel(MEDIA_STATUS_LABELS, status);
}

const MEDIA_STATUS_TONES = Object.freeze({
  pending: "neutral",
  queued: "attention",
  running: "attention",
  ready: "neutral",
  succeeded: "neutral",
  approved: "success",
  rejected: "attention",
  failed: "danger",
  outcome_unknown: "attention",
  needs_chat: "attention",
  needs_chat_setup: "attention",
  available: "neutral",
  unavailable: "neutral",
  complete: "success",
});

/** Resolve a status tone without ever exposing an unknown server token. */
export function resolveMediaStatusTone(status) {
  return resolveLabel(MEDIA_STATUS_TONES, status) || "neutral";
}

const DECISION_TONES = Object.freeze({
  approved: "success",
  "Принято": "success",
  rejected: "attention",
  "Нужны правки": "attention",
  reopened: "neutral",
  "Возвращено к правке": "neutral",
});

export function resolveDecisionTone(decision) {
  return resolveLabel(DECISION_TONES, decision) || "neutral";
}

// -----------------------------------------------------------------------
// mediaCards: the single pure builder for every card/prompt/reference the
// current snapshot allows. `formatDuration`/`formatSceneRange` (used below
// and re-exported above) live in ./media-asset.js.
// -----------------------------------------------------------------------

function sceneIndexById(scenes) {
  const index = new Map();
  if (Array.isArray(scenes)) {
    scenes.forEach((scene, position) => {
      if (scene && typeof scene.scene_id === "string") {
        index.set(scene.scene_id, { scene, position });
      }
    });
  }
  return index;
}

/**
 * `Map<reference_id, scene_id[]>`, built by scanning every scene's own
 * `links.reference_ids` (task 14, ticket 12's `authoring_media.py.
 * add_reference`: "`--scene` became repeatable... each named scene's own
 * `links.reference_ids` gets this reference's id appended"). This is the
 * *only* place a reference linked to two-or-more scenes is ever recorded
 * server-side -- `add_reference` only stamps the reference's own singular
 * `scene_id` field when exactly one scene was named at all (see
 * `_REFERENCE_KEYS`/`add_reference` in studio/projection.py and
 * studio/authoring_media.py); a reference named for zero or several scenes
 * has no `scene_id` of its own and is findable only through this reverse
 * index. A scene id this index names that is not in `sceneIndex` (a stale
 * link after a `reorder`/removed scene, or simply malformed input) is kept
 * here and dropped later, in `resolveReferenceScenes` below -- never
 * thrown on, per ticket 14's "референс с неизвестной сценой не падают".
 */
function indexReferenceScenes(scenes) {
  const byReferenceId = new Map();
  if (!Array.isArray(scenes)) {
    return byReferenceId;
  }
  for (const scene of scenes) {
    const sceneId = scene && typeof scene.scene_id === "string" ? scene.scene_id : undefined;
    const referenceIds = scene && scene.links && Array.isArray(scene.links.reference_ids)
      ? scene.links.reference_ids
      : undefined;
    if (!sceneId || !referenceIds) {
      continue;
    }
    for (const referenceId of referenceIds) {
      if (typeof referenceId !== "string" || !referenceId) {
        continue;
      }
      if (!byReferenceId.has(referenceId)) {
        byReferenceId.set(referenceId, []);
      }
      const list = byReferenceId.get(referenceId);
      if (!list.includes(sceneId)) {
        list.push(sceneId);
      }
    }
  }
  return byReferenceId;
}

/**
 * Every scene a reference belongs to, as `{sceneId, sceneLabel}` pairs in
 * scene order -- the union of its own singular `scene_id` (set only when
 * `reference add` named exactly one scene) and whatever `referenceScenes`
 * (from `indexReferenceScenes`, above) names for its `reference_id`. A
 * scene id that does not resolve in `sceneIndex` -- unknown or stale -- is
 * silently dropped rather than producing a broken entry (ticket 14:
 * "референс... с неизвестной сценой не падают"); a reference with no scene
 * at all simply returns `[]`. Order follows each scene's own position in
 * `project.scenes` (via `sceneIndex`'s stored `position`), not the order
 * ids happen to appear in `links.reference_ids`, so the same reference
 * shown at two scenes lists them consistently everywhere.
 */
function resolveReferenceScenes(reference, sceneIndex, referenceScenes) {
  const ids = new Set();
  if (reference && typeof reference.scene_id === "string" && reference.scene_id) {
    ids.add(reference.scene_id);
  }
  const referenceId = reference && reference.reference_id;
  if (typeof referenceId === "string" && referenceId && referenceScenes.has(referenceId)) {
    for (const sceneId of referenceScenes.get(referenceId)) {
      ids.add(sceneId);
    }
  }
  const resolved = [];
  for (const sceneId of ids) {
    const entry = sceneIndex.get(sceneId);
    if (!entry) {
      continue; // unknown/stale scene id -- never fatal, just not shown
    }
    resolved.push({ sceneId, sceneLabel: buildSceneLabel(entry), position: entry.position });
  }
  resolved.sort((a, b) => a.position - b.position);
  return resolved.map(({ sceneId, sceneLabel }) => ({ sceneId, sceneLabel }));
}

/** `Map<scene_id, links>` for every scene that carries a `links` object --
 * the one and only source `isLinkedAsCurrent` reads, and always looked up
 * by the item's own `scene_id`, so one scene's links can never apply to
 * another scene's prompts/results. Built once per `mediaCards()` call and
 * shared by both the prompt and result builders below. */
function indexSceneLinks(scenes) {
  const bySceneId = new Map();
  if (Array.isArray(scenes)) {
    for (const scene of scenes) {
      if (
        scene &&
        typeof scene.scene_id === "string" &&
        scene.links &&
        typeof scene.links === "object"
      ) {
        bySceneId.set(scene.scene_id, scene.links);
      }
    }
  }
  return bySceneId;
}

/**
 * Total member count per group key (`prompt_id`/`result_id`), computed once
 * over the full input array so `isLinkedAsCurrent` can tell an unambiguous
 * single-member group's id from an id shared by several versions. Items
 * without the group key at all are simply not counted.
 */
function countGroupMembers(items, groupKeyField) {
  const counts = new Map();
  for (const item of items) {
    const key = item && item[groupKeyField];
    if (typeof key !== "string" || !key) {
      continue;
    }
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  return counts;
}

/**
 * Precompute which groups (`prompt_id`/`result_id`) a scene's plural list
 * link (`prompt_version_ids`/`result_ids`) names ambiguously: two or more
 * of that exact group's own member version ids both appear in the list.
 * Only ever consulted for a scene whose singular link is absent -- exactly
 * the condition under which `isLinkedAsCurrent` reads the list at all (a
 * present singular link always wins outright, so it can never itself be
 * ambiguous). Naming two versions of one group this way is exactly as
 * undecidable as naming that group's own id when it has more than one
 * member: both leave every version in the group not current rather than
 * guessing which one was meant. Keyed by `${sceneId}::${groupId}`, mirroring
 * `indexSceneLinks`'s per-scene lookup, so one scene's ambiguity can never
 * leak onto another scene's same-named group.
 */
function findAmbiguousListGroups(items, groupKeyField, linksBySceneId, singularKey, listKey) {
  const itemsByScene = new Map();
  for (const item of items) {
    const sceneId = typeof item.scene_id === "string" ? item.scene_id : undefined;
    if (!sceneId) {
      continue;
    }
    if (!itemsByScene.has(sceneId)) {
      itemsByScene.set(sceneId, []);
    }
    itemsByScene.get(sceneId).push(item);
  }
  const ambiguous = new Set();
  for (const [sceneId, sceneItems] of itemsByScene) {
    const links = linksBySceneId.get(sceneId);
    if (!links) {
      continue;
    }
    const singular = links[singularKey];
    if (typeof singular === "string" && singular) {
      continue; // singular wins outright; the list is never consulted.
    }
    const list = links[listKey];
    if (!Array.isArray(list)) {
      continue;
    }
    const candidates = new Set(list.filter((value) => typeof value === "string" && value));
    if (candidates.size === 0) {
      continue;
    }
    const matchesByGroup = new Map();
    for (const item of sceneItems) {
      const groupId = item[groupKeyField];
      const versionId = item.version_id;
      if (typeof groupId !== "string" || !groupId) {
        continue;
      }
      if (typeof versionId !== "string" || !versionId || !candidates.has(versionId)) {
        continue;
      }
      matchesByGroup.set(groupId, (matchesByGroup.get(groupId) || 0) + 1);
    }
    for (const [groupId, count] of matchesByGroup) {
      if (count > 1) {
        ambiguous.add(`${sceneId}::${groupId}`);
      }
    }
  }
  return ambiguous;
}

/**
 * Whether one prompt/result item is the version its own scene's `links`
 * names as current (spec §3) -- never "the last one appended to its group",
 * and never "the only one left" either: a scene with no matching link id
 * marks nothing current.
 *
 * `singularKey` is the one scene-link field meant for this exact kind
 * (`image_prompt_version_id`, `motion_prompt_version_id`, `image_result_id`
 * or `video_result_id`); `listKey` is the shared, kind-agnostic list field
 * (`prompt_version_ids`/`result_ids`), consulted only when `singularKey` is
 * absent -- the two are never merged, so a singular link always wins over a
 * disagreeing list rather than both being treated as equally valid.
 *
 * A link value can name either one exact version (`versionId`) or the whole
 * group (`groupId` -- `prompt_id`/`result_id`). Read from the singular
 * field, a version match is always unambiguous -- it is one string, so it
 * can only ever name one thing. Read from the plural list, a version match
 * is unambiguous only when it is not one of two-or-more versions of the
 * *same* group the list names at once: `isAmbiguous` (from
 * `findAmbiguousListGroups`, computed once per list over every item sharing
 * the scene) carries that check and, when true, marks the item not current
 * regardless of anything else -- the list contradicted itself about which
 * version of that group is current, so picking either one would be a guess.
 * A group match (the group's own id, not a version id) is only unambiguous
 * -- and therefore only ever marks something current -- when that group has
 * exactly one member (`groupSize === 1`, from `countGroupMembers`); naming a
 * group of several versions without saying which one leaves every version
 * in it not current, the same as no link at all.
 */
function isLinkedAsCurrent(links, singularKey, listKey, versionId, groupId, groupSize, isAmbiguous) {
  if (!links || isAmbiguous) {
    return false;
  }
  const candidates = new Set();
  const singular = links[singularKey];
  if (typeof singular === "string" && singular) {
    candidates.add(singular);
  } else {
    const list = links[listKey];
    if (Array.isArray(list)) {
      for (const value of list) {
        if (typeof value === "string" && value) {
          candidates.add(value);
        }
      }
    }
  }
  if (candidates.size === 0) {
    return false;
  }
  if (typeof versionId === "string" && versionId && candidates.has(versionId)) {
    return true;
  }
  return (
    groupSize === 1 &&
    typeof groupId === "string" &&
    groupId !== "" &&
    candidates.has(groupId)
  );
}

/**
 * "Сцена {order}" (falls back to 1-based array position); the range is
 * appended only for scenes that carry a genuinely valid range (video
 * projects only -- photo scenes may omit the ms fields entirely, see
 * projection.py's optional-key pass-through).
 *
 * Second repair, 2026-09-17 (ticket 06 condition 10: "порядок и диапазон
 * сцены считает одна функция, и buildSceneLabel использует её"). This
 * used to recompute both independently -- `Number.isFinite(scene.order) ?
 * ... : position + 1` for the order, and a bare `Number.isFinite(start_ms)
 * && Number.isFinite(end_ms)` for the range, with no check at all for a
 * negative or empty (`end_ms <= start_ms`) range. `ui/timeline.js`'s
 * `resolveSceneOrder`/`resolveSceneRange` already own exactly this logic,
 * validation included (ticket 06's own "Range validation ловит
 * отрицательное/пустое время"), so a scene the timeline would refuse to
 * show a range for used to still get a garbled one here, on the very same
 * card's scene tag.
 */
function buildSceneLabel(entry) {
  if (!entry) {
    return undefined;
  }
  const { scene, position } = entry;
  const order = resolveSceneOrder(scene, position);
  const range = resolveSceneRange(scene);
  return range.hasRange ? `Сцена ${order} · ${range.rangeLabel}` : `Сцена ${order}`;
}

/**
 * Tag each item in `items` with its 1-based position among items sharing
 * the same grouping key (`prompt_id`/`result_id`, falling back to the
 * item's own identity when absent so a single ungrouped item is trivially
 * its own, single-member group). Purely a display ordinal ("v1", "v2", …);
 * which member is *current* is decided separately, from scene links, by
 * `isLinkedAsCurrent` above -- not by position in this ordering.
 */
function withOrdinals(items, groupKeyField) {
  const counts = new Map();
  return items.map((item) => {
    const key = item[groupKeyField] || item;
    const ordinal = (counts.get(key) || 0) + 1;
    counts.set(key, ordinal);
    return { ...item, ordinal };
  });
}

function buildPromptCards(prompts, sceneIndex, linksBySceneId, selectedSceneId, kind) {
  if (!Array.isArray(prompts)) {
    return undefined;
  }
  const singularLinkKey = kind === "image" ? "image_prompt_version_id" : "motion_prompt_version_id";
  const groupSizes = countGroupMembers(prompts, "prompt_id");
  const ambiguousListGroups = findAmbiguousListGroups(
    prompts,
    "prompt_id",
    linksBySceneId,
    singularLinkKey,
    "prompt_version_ids",
  );
  const withScene = prompts.map((prompt) => {
    const sceneId = typeof prompt.scene_id === "string" ? prompt.scene_id : undefined;
    const links = sceneId ? linksBySceneId.get(sceneId) : undefined;
    return {
      // Real ids only -- a record with neither `prompt_id` nor
      // `version_id` gets no `data-*-id` hook at all, never a fabricated
      // stand-in. `withOrdinals` above still numbers it correctly (as its
      // own single-member group) by falling back to the item's own object
      // identity when `prompt_id` is absent.
      promptId: prompt.prompt_id,
      versionId: prompt.version_id,
      sceneId,
      sceneLabel: buildSceneLabel(sceneIndex.get(sceneId)),
      text: prompt.text || "",
      status: prompt.status,
      statusLabel: resolveMediaStatusLabel(prompt.status),
      selected: Boolean(selectedSceneId) && sceneId === selectedSceneId,
      current: isLinkedAsCurrent(
        links,
        singularLinkKey,
        "prompt_version_ids",
        prompt.version_id,
        prompt.prompt_id,
        groupSizes.get(prompt.prompt_id) || 1,
        Boolean(sceneId && prompt.prompt_id) &&
          ambiguousListGroups.has(`${sceneId}::${prompt.prompt_id}`),
      ),
    };
  });
  return withOrdinals(withScene, "promptId");
}

/** Statuses that mean generation hasn't produced a file yet -- not a
 * broken/missing asset, just nothing to show for now (spec §9: a result
 * without a file is a normal in-progress state, not a fault). */
const NOT_YET_GENERATED_STATUSES = new Set(["pending", "queued", "running"]);

/**
 * The one precedence every result card's thumbnail resolves through, in
 * this exact order: a loadable file always wins, even over an in-progress
 * status -- a `pending` result whose file already exists shows the file,
 * never a "generating" placeholder for data that is already there. Only
 * when there is no loadable file does the status distinguish a normal wait
 * (`pending`/`queued`/`running`, spec §9) from an actual fault (anything
 * else, including `failed` and `outcome_unknown`). Pure and DOM-free so this
 * precedence -- not just the DOM branches built from it in
 * `buildResultCardNode` -- is what `node --test` exercises directly.
 */
export function resolveAssetDisplayState(assetUrl, status) {
  if (hasLoadableAsset(assetUrl)) {
    return "loaded";
  }
  return NOT_YET_GENERATED_STATUSES.has(status) ? "pending" : "broken";
}

function buildResultCards(results, sceneIndex, linksBySceneId, selectedSceneId, kind) {
  if (!Array.isArray(results)) {
    return undefined;
  }
  const singularLinkKey = kind === "image" ? "image_result_id" : "video_result_id";
  const groupSizes = countGroupMembers(results, "result_id");
  const ambiguousListGroups = findAmbiguousListGroups(
    results,
    "result_id",
    linksBySceneId,
    singularLinkKey,
    "result_ids",
  );
  const withScene = results.map((result) => {
    const sceneId = typeof result.scene_id === "string" ? result.scene_id : undefined;
    const entry = sceneIndex.get(sceneId);
    const links = sceneId ? linksBySceneId.get(sceneId) : undefined;
    const card = {
      // Real ids only -- see buildPromptCards's note above.
      resultId: result.result_id,
      versionId: result.version_id,
      sceneId,
      sceneLabel: buildSceneLabel(entry),
      scene: entry ? entry.scene : undefined,
      assetId: result.asset_id,
      assetUrl: result.asset_url,
      caption: result.caption || "",
      status: result.status,
      statusLabel: resolveMediaStatusLabel(result.status),
      notYetGenerated: resolveAssetDisplayState(result.asset_url, result.status) === "pending",
      hidden: Boolean(result.hidden),
      selected: Boolean(selectedSceneId) && sceneId === selectedSceneId,
      // Task 08 repair 1, condition 6: a retired result is never "Текущая"
      // -- decided right here, in the one place `current` is ever computed
      // for this card, rather than a second calculation or a DOM patch
      // (ui/card-decorate.js) removing `.media-current-badge` after the
      // fact once it notices `record.retired`. `retired` itself is also
      // carried through so that second module never needs to re-derive it
      // from a raw scene-link lookup of its own.
      retired: Boolean(result.retired),
      current:
        !result.retired &&
        isLinkedAsCurrent(
          links,
          singularLinkKey,
          "result_ids",
          result.version_id,
          result.result_id,
          groupSizes.get(result.result_id) || 1,
          Boolean(sceneId && result.result_id) &&
            ambiguousListGroups.has(`${sceneId}::${result.result_id}`),
        ),
    };
    if (kind === "video" && entry) {
      const { scene } = entry;
      if (Number.isFinite(scene.start_ms) && Number.isFinite(scene.end_ms)) {
        card.rangeLabel = formatDuration(scene.end_ms - scene.start_ms);
      }
    }
    return card;
  });
  return withOrdinals(withScene, "resultId");
}

/**
 * Build every prompt/reference/result view-model the current snapshot's
 * progressive-disclosure stage allows. A section is `undefined` (never `[]`)
 * when its source key is entirely absent from `active_project` -- that
 * stage hasn't unlocked it yet, spec §2.1 -- versus `[]` when the key is
 * present but genuinely empty, which callers render as a named empty state
 * rather than nothing at all (spec §9). `selectedSceneId` (task 06's future
 * `selected_scene_id`, absent today) only ever flips each card's
 * presentational `selected` flag; it never filters what exists.
 *
 * `motion`/`videoResults` are additionally gated on `project.type !==
 * "photo"` regardless of whether `motion_prompts`/`video_results` keys are
 * present in the snapshot: the real server (projection.py) already omits
 * them for a photo project, but this is a second, independent guard on the
 * client so a malformed or hand-built snapshot can never leak a video-only
 * section into a photo project's UI.
 */
export function mediaCards(snapshot, selectedSceneId) {
  const project = snapshot && typeof snapshot === "object" ? snapshot.active_project : null;
  if (!project || typeof project !== "object") {
    return { prompts: {}, referenceGroups: undefined, imageResults: undefined, videoResults: undefined };
  }
  const sceneIndex = sceneIndexById(project.scenes);
  const linksBySceneId = indexSceneLinks(project.scenes);
  const referenceScenes = indexReferenceScenes(project.scenes);
  const isPhoto = project.type === "photo";
  return {
    prompts: {
      image: buildPromptCards(project.image_prompts, sceneIndex, linksBySceneId, selectedSceneId, "image"),
      motion: isPhoto
        ? undefined
        : buildPromptCards(project.motion_prompts, sceneIndex, linksBySceneId, selectedSceneId, "motion"),
    },
    referenceGroups: Array.isArray(project.references)
      ? groupReferences(
          project.references.map((reference) => {
            // Task 14: a reference can belong to several scenes at once
            // (scenes[].links.reference_ids, ticket 12's repeatable
            // `--scene`) -- `scenes` (plural, ordered) is the one field
            // every caller below reads; `sceneId`/`sceneLabel` (singular)
            // are kept alongside, set to the *first* resolved scene, only
            // because they are still what a single-scene reference's own
            // scene tag has always rendered from (buildReferenceItem below
            // handles the plural list itself for the two-or-more case).
            const scenes = resolveReferenceScenes(reference, sceneIndex, referenceScenes);
            const sceneIds = scenes.map((entry) => entry.sceneId);
            return {
              ...reference,
              scenes,
              sceneIds,
              sceneId: scenes[0]?.sceneId,
              sceneLabel: scenes[0]?.sceneLabel,
              selected: Boolean(selectedSceneId) && sceneIds.includes(selectedSceneId),
            };
          }),
        )
      : undefined,
    imageResults: buildResultCards(project.image_results, sceneIndex, linksBySceneId, selectedSceneId, "image"),
    videoResults: isPhoto
      ? undefined
      : buildResultCards(project.video_results, sceneIndex, linksBySceneId, selectedSceneId, "video"),
  };
}

// -----------------------------------------------------------------------
// Pure rendering decisions -- "which sections exist at this stage" and
// "does this asset have a loadable URL at all" are both decisions a card
// list of any size makes the same way, so they are pulled out of the DOM
// builders below and exercised directly under `node --test` instead of
// only through the (untestable-in-Node) browser visual gate.
// -----------------------------------------------------------------------

/**
 * Which of the media gallery's two subsections the current stage has
 * unlocked, mirroring `mediaCards`'s `undefined`-means-"not this stage yet"
 * contract. `renderMediaGallery` paints nothing and returns `false` when
 * neither is visible, so stage 1's DOM stays scenario-only (spec §2.1).
 */
export function gallerySections(cards) {
  const hasImages = cards.imageResults !== undefined;
  const hasVideos = cards.videoResults !== undefined;
  return { visible: hasImages || hasVideos, hasImages, hasVideos };
}

/** Same idea as `gallerySections`, for the inspector's prompts/references
 * panel. */
export function referencePanelSections(cards) {
  const hasPrompts = cards.prompts.image !== undefined || cards.prompts.motion !== undefined;
  const hasReferences = cards.referenceGroups !== undefined;
  return { visible: hasPrompts || hasReferences, hasPrompts, hasReferences };
}

// -----------------------------------------------------------------------
// DOM rendering -- thin, verified only through the browser visual gate
// (no DOM under `node --test`; see the file banner and interfaces.md).
// `hasLoadableAsset`/`markAssetError`/`buildAssetPlaceholder` (used below,
// and the first two re-exported above) live in ./media-asset.js.
// -----------------------------------------------------------------------

function buildAccessibleLabel(parts) {
  return parts.filter((part) => typeof part === "string" && part).join(", ");
}

/**
 * Ask viewer.js to open the lightbox/player for one card's asset, without
 * this module importing viewer.js (see the file banner). `trigger`
 * dispatches its own event and lets it bubble to `document`, where
 * viewer.js's `attachViewerOpenListener` (wired once, from app.js) picks it
 * up and calls `openImageViewer`/`openVideoViewer`.
 */
function dispatchOpenViewer(kind, asset, scene, trigger) {
  trigger.dispatchEvent(
    new CustomEvent("studio:open-viewer", {
      bubbles: true,
      detail: { kind, asset, scene },
    }),
  );
}

function buildCurrentBadge() {
  const badge = document.createElement("span");
  badge.className = "media-current-badge";
  badge.textContent = "Текущая";
  return badge;
}

/**
 * A card's own scene tag, doubling as one of two scene-selection triggers
 * this module is allowed to add (ticket 06 amendment 6: "из плеера видео
 * можно перейти к его сцене" -- a video result's card, visible both before
 * and after using its viewer, is where that lives; ui/viewer.js's own
 * in-player "Перейти к сцене" control is the other). Calls
 * `ui/timeline.js`'s `requestSceneSelection` -- repair 2026-09-17, ticket 06
 * condition 10 -- rather than building a second, separately maintained
 * copy of the same `studio:scene-selected` dispatch, so a click here
 * reaches the exact same app.js listener and store method through the one
 * shared definition. A tag whose item carries no `sceneId` (never expected
 * today, but `sceneLabel` alone is not itself an id) falls back to a
 * plain, non-interactive span rather than a button with nothing real to
 * select.
 *
 * `data-hook="media-scene-tag"` (second repair, 2026-09-17, ticket 06
 * condition 5) lets `ui/shell.js`'s focus capture/restore recognize this
 * button too, alongside the scenario/timeline selection hooks it already
 * knew about (`ui/state.js`'s `SCENE_FOCUS_HOOKS`) -- without it, pressing
 * Enter on a scene tag *inside the inspector* selected the scene
 * correctly but then lost focus to `<body>` on the repaint that followed,
 * since `paintInspector` (unlike `paintMain`) had no focus-preservation of
 * its own to fall into.
 */
function buildSceneTag(sceneId, sceneLabel) {
  if (!sceneId) {
    const span = document.createElement("span");
    span.className = "media-scene-tag";
    span.textContent = sceneLabel;
    return span;
  }
  const button = document.createElement("button");
  button.type = "button";
  button.className = "media-scene-tag media-scene-tag-button";
  button.dataset.hook = "media-scene-tag";
  button.textContent = sceneLabel;
  button.dataset.sceneId = sceneId;
  button.setAttribute("aria-label", `Перейти к сцене в сценарии: ${sceneLabel}`);
  button.addEventListener("click", () => requestSceneSelection(sceneId, "media"));
  return button;
}

/** One reference thumbnail button; a broken/missing image swaps to a
 * placeholder without touching any sibling card (spec §8/§9), and the scene
 * it belongs to is visible as real text (a `.media-scene-tag`), not only
 * inside the button's aria-label. */
function buildReferenceItem(item) {
  const li = document.createElement("li");
  li.className = "media-reference-item";
  li.dataset.hook = "reference-item";
  if (item.reference_id) {
    li.dataset.referenceId = item.reference_id;
  }
  // Ticket 14 repair, condition 9: `data-scene-id` carries *every* linked
  // scene's id, space-separated (`mediaCards`'s own plural `item.sceneIds`
  // -- see that function's own comment), not only the first -- a token
  // list a real `[data-scene-id~="…"]` attribute selector already reads
  // correctly, the same shape `classList` uses. `item.sceneId` (singular)
  // is only mediaCards's convenience for kinds that are always tied to
  // exactly one scene (prompts, results); a reference is not one of them.
  const sceneIds = Array.isArray(item.sceneIds) ? item.sceneIds.filter(Boolean) : [];
  if (sceneIds.length > 0) {
    li.dataset.sceneId = sceneIds.join(" ");
  } else if (item.sceneId) {
    li.dataset.sceneId = item.sceneId;
  }
  li.dataset.selected = String(Boolean(item.selected));

  const button = document.createElement("button");
  button.type = "button";
  button.className = "media-thumb-button";
  // Repair, ticket 14 punch-list item 3 (review blocker G04) -- same fix as
  // buildResultCardNode's own thumbnail (this file, below): a reference's
  // thumbnail is just as keyboard-focusable, and a real background repaint
  // (renderReferencePanel rebuilds this whole list on every commit) used to
  // drop that focus the same way. `data-target-id` uses the one real id a
  // reference has, `item.reference_id` -- there is no version axis for
  // references the way there is for prompts/results.
  if (item.reference_id) {
    button.dataset.hook = "card-control";
    button.dataset.targetId = item.reference_id;
    button.dataset.action = "open";
  }
  // Same widening: the accessible name names every scene this reference is
  // actually tagged with below (buildSceneTag, one per `item.scenes`
  // entry), never only the first -- an aria-label that silently dropped a
  // second scene would disagree with what a sighted user sees right next
  // to it.
  const scenes = Array.isArray(item.scenes) ? item.scenes : [];
  const sceneLabels = scenes.map((scene) => scene && scene.sceneLabel).filter(Boolean);
  button.setAttribute(
    "aria-label",
    buildAccessibleLabel(["Открыть референс", item.label, ...sceneLabels]) ||
      "Открыть референс",
  );

  if (hasLoadableAsset(item.asset_url)) {
    const img = document.createElement("img");
    img.alt = "";
    img.loading = "lazy";
    img.addEventListener("error", () => {
      // The url looked loadable at render time (a well-formed /assets/
      // path) but the request or decode failed after the fact -- same
      // dead end as the "known unavailable up front" branch below, so it
      // gets the same treatment: disabled, honest label, no click handler
      // left pretending there is something to open.
      const message = "Референс недоступен";
      const placeholder = buildAssetPlaceholder(message);
      img.replaceWith(placeholder);
      markAssetError(placeholder, item.asset_id);
      button.disabled = true;
      button.setAttribute("aria-label", message);
    });
    img.src = item.asset_url;
    button.append(img);
    button.addEventListener("click", () =>
      dispatchOpenViewer(
        "image",
        { assetUrl: item.asset_url, caption: item.label, assetId: item.asset_id },
        undefined,
        button,
      ),
    );
  } else {
    // No `asset_id`/loadable url at all (or a broken one): no active
    // control pretending there is something to open -- see the matching
    // fix in buildResultCardNode.
    button.disabled = true;
    button.setAttribute("aria-label", "Референс недоступен");
    const placeholder = buildAssetPlaceholder("Референс недоступен");
    button.append(placeholder);
    markAssetError(placeholder, item.asset_id);
  }

  const caption = document.createElement("span");
  caption.className = "media-item-caption";
  caption.textContent = item.label || "";
  li.append(button, caption);

  // Task 14: one tag per linked scene -- a reference bound to two-or-more
  // scenes (scenes[].links.reference_ids) shows at every one of them, not
  // only the first (ticket 14: "референс на две сцены виден у обеих").
  // Reuses the same `scenes` array the aria-label above already read.
  for (const scene of scenes) {
    if (scene && scene.sceneLabel) {
      li.append(buildSceneTag(scene.sceneId, scene.sceneLabel));
    }
  }

  return li;
}

function buildPromptEntry(prompt) {
  const li = document.createElement("li");
  li.className = "media-prompt-entry";
  li.dataset.hook = "prompt-entry";
  // Real ids only, each independently guarded -- a prompt missing one of
  // the two never gets a fabricated stand-in.
  if (prompt.promptId) {
    li.dataset.promptId = prompt.promptId;
  }
  if (prompt.versionId) {
    // Distinguishes versions of the *same* prompt so task 08 can address a
    // specific one, separately from the group-level `data-prompt-id`.
    li.dataset.versionId = prompt.versionId;
  }
  if (prompt.sceneId) {
    li.dataset.sceneId = prompt.sceneId;
  }
  li.dataset.selected = String(Boolean(prompt.selected));

  const meta = document.createElement("div");
  meta.className = "media-prompt-meta";
  const version = document.createElement("span");
  version.className = "media-version-badge";
  version.textContent = `v${prompt.ordinal}`;
  meta.append(version);
  if (prompt.current) {
    meta.append(buildCurrentBadge());
  }
  if (prompt.sceneLabel) {
    meta.append(buildSceneTag(prompt.sceneId, prompt.sceneLabel));
  }
  if (prompt.statusLabel) {
    const status = document.createElement("span");
    status.className = "media-status-tag";
    status.dataset.tone = resolveMediaStatusTone(prompt.status);
    status.textContent = prompt.statusLabel;
    meta.append(status);
  }

  const text = document.createElement("p");
  text.className = "media-prompt-text";
  text.textContent = prompt.text;

  li.append(meta, text);
  return li;
}

function buildResultCardNode(card, kind) {
  const li = document.createElement("li");
  li.className = "media-result-card";
  li.dataset.hook = kind === "video" ? "video-card" : "image-card";
  if (card.resultId) {
    li.dataset.resultId = card.resultId;
  }
  if (card.versionId) {
    // Distinguishes versions of the same result -- task 08 addresses
    // actions (approve/reject/hide/…) to one specific version by this,
    // never by the group-level `data-result-id` alone.
    li.dataset.versionId = card.versionId;
  }
  if (card.sceneId) {
    li.dataset.sceneId = card.sceneId;
  }
  li.dataset.selected = String(Boolean(card.selected));
  if (card.hidden) {
    li.dataset.hidden = "true";
  }

  const button = document.createElement("button");
  button.type = "button";
  button.className = "media-thumb-button";
  // Repair, ticket 14 (review blocker G04): this thumbnail is a real,
  // keyboard-focusable control -- an operator tabbed onto "Открыть
  // изображение/видео" but had not yet clicked it -- and a real,
  // unrelated background repaint (e.g. a chat record landing during the
  // poll) used to drop that focus to <body>/a fallback heading, same as
  // every other unhooked control this ticket's review named. Carries the
  // exact same `data-hook="card-control"`/`data-target-id`/`data-action`
  // triple ui/card-forms.js's own `markControlHooks` stamps on every
  // decision control of this same card (not imported from there -- see
  // ui/card-reorder.js's own reorder buttons for the established
  // precedent of setting these three inline rather than crossing the
  // display/decision module boundary, ui/card-decorate.js's own file
  // banner) -- `targetId` mirrors ui/card-decorate.js's own
  // `record.version_id || record[groupKey]` exactly, so
  // ui/shell.js's findCardControlFocusTarget (the search
  // repaintZonePreservingFocus's own card-control axis runs) can also fall
  // back onto this same thumbnail as the "nearest control of the same card"
  // once a decision button it was actually looking for has disappeared,
  // exactly the way any two decision buttons on one row already do for
  // each other.
  // `"open"` never collides with the real wire action-type allowlist
  // (approve/reject/edit/vary/regenerate/hide/unhide/retire/restore/
  // reorder-*/continue-in-chat, interfaces.md's task-08 hooks list) --
  // this button never calls submitAction at all, only dispatchOpenViewer.
  const thumbTargetId = card.versionId || card.resultId;
  if (thumbTargetId) {
    button.dataset.hook = "card-control";
    button.dataset.targetId = thumbTargetId;
    button.dataset.action = "open";
  }

  if (hasLoadableAsset(card.assetUrl)) {
    const label = buildAccessibleLabel([
      kind === "video" ? "Открыть видео" : "Открыть изображение",
      card.caption,
      card.sceneLabel,
    ]);
    button.setAttribute("aria-label", label || (kind === "video" ? "Открыть видео" : "Открыть изображение"));
    const mediaEl =
      kind === "video" ? document.createElement("video") : document.createElement("img");
    if (kind === "video") {
      mediaEl.muted = true;
      mediaEl.preload = "metadata";
      mediaEl.setAttribute("aria-hidden", "true");
      mediaEl.tabIndex = -1;
    } else {
      mediaEl.alt = "";
      mediaEl.loading = "lazy";
    }
    mediaEl.addEventListener("error", () => {
      // Same reasoning as buildReferenceItem's error handler above: this
      // looked loadable at render time, the request/decode failed after
      // the fact, so it gets the same disabled/honest-label treatment as
      // a card known broken up front (the final `else` branch below).
      const message = kind === "video" ? "Видео недоступно" : "Изображение недоступно";
      const placeholder = buildAssetPlaceholder(message);
      mediaEl.replaceWith(placeholder);
      markAssetError(placeholder, card.assetId);
      button.disabled = true;
      button.setAttribute("aria-label", message);
    });
    mediaEl.src = card.assetUrl;
    button.append(mediaEl);
    if (card.rangeLabel) {
      const badge = document.createElement("span");
      badge.className = "media-duration-badge";
      badge.textContent = card.rangeLabel;
      button.append(badge);
    }
    button.addEventListener("click", () => {
      const asset = { assetUrl: card.assetUrl, caption: card.caption, assetId: card.assetId };
      dispatchOpenViewer(kind, asset, kind === "video" ? card.scene : undefined, button);
    });
  } else if (card.notYetGenerated) {
    // Not a broken asset -- generation simply hasn't produced a file yet
    // (e.g. status "running", spec §9's "Генерируется" example). No
    // data-asset-error, no studio:asset-error, and no "Open..." button
    // pretending there is something to open: the button stays in the DOM
    // (so the card's layout matches its loaded siblings) but is disabled
    // and labelled for what is actually true instead.
    const message = kind === "video" ? "Видео ещё не готово" : "Изображение ещё не готово";
    button.disabled = true;
    button.setAttribute("aria-label", message);
    button.append(buildAssetPlaceholder(message));
  } else {
    // A genuinely broken/missing/failed asset (never "not yet generated"
    // -- that is the branch above) gets no active control pretending
    // there is something to open: disabled, same as that branch, and
    // labelled for what is actually true instead of "Открыть...".
    const message = kind === "video" ? "Видео недоступно" : "Изображение недоступно";
    button.disabled = true;
    button.setAttribute("aria-label", message);
    const placeholder = buildAssetPlaceholder(message);
    button.append(placeholder);
    markAssetError(placeholder, card.assetId);
  }

  const footer = document.createElement("div");
  footer.className = "media-item-footer";
  const version = document.createElement("span");
  version.className = "media-version-badge";
  version.textContent = `v${card.ordinal}`;
  footer.append(version);
  if (card.current) {
    footer.append(buildCurrentBadge());
  }
  if (card.hidden) {
    const hiddenBadge = document.createElement("span");
    hiddenBadge.className = "media-hidden-badge";
    hiddenBadge.textContent = "Скрыто";
    footer.append(hiddenBadge);
  }
  if (card.sceneLabel) {
    footer.append(buildSceneTag(card.sceneId, card.sceneLabel));
  }
  if (card.statusLabel) {
    const status = document.createElement("span");
    status.className = "media-status-tag";
    status.dataset.tone = resolveMediaStatusTone(card.status);
    status.textContent = card.statusLabel;
    footer.append(status);
  }
  if (card.caption) {
    const caption = document.createElement("p");
    caption.className = "media-item-caption";
    caption.textContent = card.caption;
    footer.append(caption);
  }

  li.append(button, footer);
  return li;
}

function buildEmptySection(message) {
  const p = document.createElement("p");
  p.className = "media-empty";
  p.textContent = message;
  return p;
}

function buildPromptSubsection(headingText, items) {
  const wrap = document.createElement("div");
  const heading = document.createElement("h4");
  heading.className = "media-prompt-subheading";
  heading.textContent = headingText;
  wrap.append(heading);
  if (items.length === 0) {
    wrap.append(buildEmptySection("Промптов пока нет."));
  } else {
    const list = document.createElement("ul");
    list.className = "media-prompt-list";
    for (const prompt of items) {
      list.append(buildPromptEntry(prompt));
    }
    wrap.append(list);
  }
  return wrap;
}

// Ticket 06 amendment 6: "при выбранной сцене инспектор показывает
// материалы только этой сцены, а не всего проекта" -- narrower than what
// `mediaCards` itself promises (that function's own test locks in that it
// never filters, only flags `.selected`; see tests/ui/media-viewer.test.mjs).
// The narrowing happens only here, in this DOM step, strictly for display:
// an item with no `sceneId` at all (a project-wide reference, never tied to
// one scene) is never hidden by a scene selection, only one that names a
// *different* scene is.
//
// Exported (second repair, 2026-09-17, ticket 06 condition 9: "у сужения
// инспектора по сцене есть краснеющий тест"). Before this, the only path
// that ever ran this filter was `renderReferencePanel` itself -- a DOM
// function this project's `node --test` run cannot exercise at all (see
// the file banner) -- so a mutation as blunt as always returning `true`
// (no narrowing at all) passed the whole suite silently.
//
// Task 14: a reference item now carries `sceneIds` (plural, possibly
// several) instead of relying on `sceneId` alone -- checked first when
// present, so a reference linked to two-or-more scenes narrows correctly
// at either one; a prompt/result item (always exactly one `sceneId`, never
// a `sceneIds` array) falls through to the original singular check
// unchanged.
export function keepForSelectedScene(item, selectedSceneId) {
  if (!selectedSceneId) {
    return true;
  }
  if (Array.isArray(item.sceneIds)) {
    return item.sceneIds.length === 0 || item.sceneIds.includes(selectedSceneId);
  }
  return !item.sceneId || item.sceneId === selectedSceneId;
}

/**
 * Render the reference groups and versioned prompts into `root` (the
 * `[data-hook="inspector"]` zone). Returns `true` when it painted anything,
 * so the caller (shell.js's paintInspector) can fall back to its own
 * "nothing yet" copy instead of showing both at once. Image and motion
 * prompts render as two visibly labelled subsections rather than one merged
 * list, so their kind is distinguishable on both desktop and mobile without
 * relying on an aria-only cue.
 */
export function renderReferencePanel(root, snapshot, selectedSceneId) {
  const cards = mediaCards(snapshot, selectedSceneId);
  const sections = referencePanelSections(cards);
  if (!sections.visible) {
    return false;
  }

  const section = document.createElement("div");
  section.dataset.hook = "reference-panel";

  if (sections.hasPrompts) {
    const heading = document.createElement("h3");
    heading.textContent = "Промпты";
    section.append(heading);
    const imagePrompts = (cards.prompts.image || []).filter((item) =>
      keepForSelectedScene(item, selectedSceneId),
    );
    const motionPrompts = (cards.prompts.motion || []).filter((item) =>
      keepForSelectedScene(item, selectedSceneId),
    );
    if (imagePrompts.length === 0 && motionPrompts.length === 0) {
      section.append(
        buildEmptySection(selectedSceneId ? "У этой сцены пока нет промптов." : "Промптов пока нет."),
      );
    } else {
      if (cards.prompts.image !== undefined) {
        section.append(buildPromptSubsection("Промпты для изображений", imagePrompts));
      }
      if (cards.prompts.motion !== undefined) {
        section.append(buildPromptSubsection("Промпты для видео", motionPrompts));
      }
    }
  }

  if (sections.hasReferences) {
    const heading = document.createElement("h3");
    heading.textContent = "Референсы";
    section.append(heading);
    const referenceGroups = cards.referenceGroups
      .map((group) => ({
        ...group,
        items: group.items.filter((item) => keepForSelectedScene(item, selectedSceneId)),
      }))
      .filter((group) => group.items.length > 0);
    if (referenceGroups.length === 0) {
      section.append(
        buildEmptySection(selectedSceneId ? "У этой сцены пока нет референсов." : "Референсов пока нет."),
      );
    } else {
      for (const group of referenceGroups) {
        const groupHeading = document.createElement("h4");
        groupHeading.className = "media-reference-group-label";
        groupHeading.textContent = group.label;
        const list = document.createElement("ul");
        list.className = "media-reference-group";
        list.dataset.role = group.role;
        for (const item of group.items) {
          list.append(buildReferenceItem(item));
        }
        section.append(groupHeading, list);
      }
    }
  }

  root.append(section);
  return true;
}

/**
 * Render the image/video result galleries into `root` (mounted in `#main`,
 * below the scenario slot). Returns `true` when it painted anything, so the
 * caller only appends its wrapper to the DOM when there is media to show --
 * scenario stage must have zero media DOM at all (spec §2.1). Section
 * headings reuse `ui/state.js`'s `STAGE_LABELS` instead of a second,
 * separately-hardcoded copy of the same words.
 */
export function renderMediaGallery(root, snapshot, selectedSceneId) {
  const cards = mediaCards(snapshot, selectedSceneId);
  const sections = gallerySections(cards);
  if (!sections.visible) {
    return false;
  }

  const section = document.createElement("div");
  section.dataset.hook = "media-gallery";

  if (sections.hasImages) {
    const heading = document.createElement("h2");
    heading.textContent = STAGE_LABELS.image_results;
    section.append(heading);
    if (cards.imageResults.length === 0) {
      section.append(buildEmptySection("Результатов пока нет."));
    } else {
      const list = document.createElement("ul");
      list.className = "media-card-grid";
      for (const card of cards.imageResults) {
        list.append(buildResultCardNode(card, "image"));
      }
      section.append(list);
    }
  }

  if (sections.hasVideos) {
    const heading = document.createElement("h2");
    heading.textContent = STAGE_LABELS.motion;
    section.append(heading);
    if (cards.videoResults.length === 0) {
      section.append(buildEmptySection("Результатов пока нет."));
    } else {
      const list = document.createElement("ul");
      list.className = "media-card-grid";
      for (const card of cards.videoResults) {
        list.append(buildResultCardNode(card, "video"));
      }
      section.append(list);
    }
  }

  root.append(section);
  return true;
}
