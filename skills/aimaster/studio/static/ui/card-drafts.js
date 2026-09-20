// Task 08 repair 1, condition 11 ("черновики комментариев" is its own
// module) and condition 10 ("одна форма комментария на все места"): ONE
// shared draft store for every open comment/edit/reorder-message box this
// dashboard renders -- a card's reject comment, a prompt's edit text+
// reason, a stage's reject comment, and a reorder control's own surviving
// error message (condition 8: "409 на порядке показывает сообщение,
// которое переживает перерисовку"). Before this repair, card-actions.js
// and stage-actions.js each kept their own, separately-maintained Map with
// the same shape -- this is the one place that shape lives now.
//
// Every card in the gallery/inspector/stage bar is rebuilt from scratch on
// every repaint (no DOM patch-in-place here, unlike ui/rail.js's list), so
// without this a comment typed into "Нужны правки" -- or a 409 message a
// reorder click just set -- would vanish the instant an unrelated commit
// (an unrelated card's own action, a snapshot poll) repainted the zone.
// Pure Map bookkeeping; never touches `document` or `fetch`.

const drafts = new Map();

/**
 * Build one draft key from its parts, joined the same way every caller
 * already did by hand before this module existed (`${a}::${b}::${c}`).
 * Callers own their own part shape -- `draftKey(projectId, kind, targetId)`
 * for a card comment/edit, `draftKey(projectId, "stage", stage)` for a
 * stage reject, `draftKey(projectId, "reorder", collectionKey)` for a
 * reorder message -- so two different purposes can never collide as long
 * as each supplies a distinct middle part.
 */
export function draftKey(...parts) {
  return parts.join("::");
}

export function getDraft(key) {
  return drafts.get(key);
}

export function setDraft(key, value) {
  drafts.set(key, value);
}

export function clearDraft(key) {
  drafts.delete(key);
}

/**
 * Drop every draft whose key starts with `prefix` and is not in
 * `knownKeys`. Ticket 08 point 10 ("мелочи из ревью"): `pruneCommentDrafts`
 * existed in the pre-repair code but was never called from anywhere, so a
 * card/prompt/scene/stage that disappeared from the snapshot (a past
 * stage, a deleted scene) left its draft in memory forever.
 *
 * `prefix` is deliberately not just `projectId` -- ui/card-decorate.js's
 * `decorateResultCards`/`decoratePromptCards` and ui/stage-approval.js's
 * `renderStageActions` each call this independently, once per render, and
 * each only knows about *its own* namespace's current targets (a result
 * card, a prompt, a stage reject). Scoping every call to
 * `${projectId}::${kind}::` (never the bare `${projectId}::`) is what lets
 * three independent callers each prune their own drafts without one call
 * wiping out a sibling namespace's still-relevant entries.
 */
export function pruneDrafts(prefix, knownKeys) {
  for (const key of drafts.keys()) {
    if (key.startsWith(prefix) && !knownKeys.has(key)) {
      drafts.delete(key);
    }
  }
}
