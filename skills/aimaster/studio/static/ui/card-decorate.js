// Task 08 repair 1, condition 11 ("украшение карточек" is its own
// module): the two entry points ui/shell.js calls after ui/media.js's own
// renderers have inserted their nodes -- `decorateResultCards`/
// `decoratePromptCards` -- plus the row assembly, the retired badge and
// the on-card decision badge (repair condition 4, R03) they are built
// from.
//
// This module never imports ui/media.js or ui/scenario.js, and neither of
// those import this one (ticket 08 amendment 2). It decorates their
// already-rendered DOM from the outside, queried only by documented
// `data-hook`s -- never a class either of those two modules owns.

import { clearDraft, draftKey, pruneDrafts } from "./card-drafts.js";
import {
  findGroupRecord,
  isCardCollectionCurrent,
  resolveCardActions,
} from "./card-model.js";
import {
  buildCommentForm,
  buildPromptEditControl,
  buildSimpleButton,
  buildStatusLine,
} from "./card-forms.js";
import { buildReorderButtons, attachDragReorder } from "./card-reorder.js";
import { buildGrantArea } from "./grant-action.js";
import { prunePendingRequests, resolveGrantCardState } from "./paid-action-state.js";
import { DECISION_VALUE_LABELS } from "./decision-history.js";
import { resolveLabel } from "./state.js";
import { resolveDecisionTone } from "./media.js";
import { appendMoreMenuContent, buildMoreMenu } from "./more-menu.js";

export { resolveDecisionTone };

function buildRetiredBadge() {
  const badge = document.createElement("span");
  badge.className = "card-retired-badge";
  badge.textContent = "Убрано из работы";
  return badge;
}

/**
 * Mark a card `retired` visually -- unconditionally, regardless of whether
 * its own stage is still current (ticket 08 point 9: a retired card stays
 * visibly retired for the rest of the project's life). The "Текущая"
 * badge itself is suppressed *upstream*, in ui/media.js's own
 * `buildResultCards` (repair condition 6: "«Убрано из работы» снимает
 * «Текущая» через модель, а не удалением чужого класса
 * .media-current-badge") -- `record.retired` already forces
 * `mediaCards(...).current` to `false` before this ever runs, so there is
 * no badge left here to remove and no second "is this current" calculation
 * in this file at all.
 */
function markRetiredCard(card) {
  card.append(buildRetiredBadge());
}

/** The latest decision on this card's own append-only `decisions[]`, as a
 * small persistent badge on the card face (repair condition 4, R03: "После
 * «Принять» или «Нужны правки» карточка показывает последнее решение...
 * Повторная отправка того же решения не выглядит так, будто ничего не
 * произошло"). Reuses `.media-status-tag` (styles/media.css), the same
 * class ui/card-decorate.js's own decision-history list already uses for
 * the identical `decisionLabel` vocabulary -- one dictionary
 * (`DECISION_VALUE_LABELS`), one visual treatment, never a second one. */
function buildCardDecisionBadge(decisions) {
  const list = Array.isArray(decisions) ? decisions : [];
  const last = list[list.length - 1];
  const label = last && resolveLabel(DECISION_VALUE_LABELS, last.decision);
  if (!label) {
    return null;
  }
  const wrap = document.createElement("div");
  wrap.className = "card-decision-badge";
  const tag = document.createElement("span");
  tag.className = "media-status-tag";
  tag.dataset.tone = resolveDecisionTone(last.decision);
  tag.textContent = label;
  wrap.append(tag);
  if (last.comment) {
    const comment = document.createElement("p");
    comment.className = "decision-history-comment";
    comment.textContent = last.comment;
    wrap.append(comment);
  }
  return wrap;
}

/**
 * Whether "Вернуться в чат" (an `outcome_unknown` card's own hint, spec
 * §5) is a real control right now -- repair condition 2's own fix: the
 * pre-repair code always rendered this as static text (this task's own
 * diagnosis, "«Вернуться в чат» — простой текст"), even though
 * `continue-in-chat` is on every stage's `view_stage.allowed_actions`
 * (interfaces.md's task-08 notes: a chat-queue action type the decisions
 * worker never itself applies -- chat claims it via the CLI's own `claim`
 * subcommand).
 *
 * `"button"` -- the server currently lists `continue-in-chat` and no
 * attempt for this exact target is already queued/running; `"queued"` --
 * one already is, so a second click would only queue a duplicate hand-off;
 * `"text-only"` -- the server does not currently allow `continue-in-chat`
 * at all, so the hint stays plain text, exactly as it always has.
 *
 * Pure and exported so tests/ui/card-decorate.test.mjs can pin all three
 * outcomes directly; the actual button/text choice this drives is DOM-only
 * and verified through the browser visual gate like every other builder
 * in this file.
 */
export function resolveReturnToChatState({ allowedActions, actions, targetId }) {
  const allowed = Array.isArray(allowedActions) && allowedActions.includes("continue-in-chat");
  if (!allowed) {
    return "text-only";
  }
  const list = Array.isArray(actions) ? actions : [];
  const entry = list.find(
    (item) => item && item.target_id === targetId && item.action_type === "continue-in-chat",
  );
  if (entry && (entry.status === "queued" || entry.status === "running")) {
    return "queued";
  }
  return "button";
}

/** Append the "Вернуться в чат" notice/control for an `outcome_unknown`
 * card -- `resolveReturnToChatState`'s own three outcomes, rendered.
 * `"button"` reuses `buildSimpleButton` (the same one-click client every
 * free card decision already shares, ui/actions.js's `submitAction`),
 * wired to `continue-in-chat` for this card's own `targetId` with
 * `awaitUpdate: false` -- this chat hand-off never bumps the project's own
 * revision (see ui/card-forms.js's banner on `buildSimpleButton`), so
 * waiting on one would only delay, and then misreport, a click that
 * actually succeeded.
 *
 * Client repair 2, craft-review finding 12: the standalone
 * `buildReturnToChatButtonProps` factory this used to call existed only so
 * a test could assert on its output without clicking a real button --
 * inlined here now that tests/ui/card-decorate.test.mjs proves the same
 * contract through the real control instead (`decorateResultCards` +
 * a click). */
function appendReturnToChatControl({ buttons, targetId, expectedRevision, projectId, status, allowedActions, actionEntries }) {
  const state = resolveReturnToChatState({ allowedActions, actions: actionEntries, targetId });
  if (state === "button") {
    buttons.append(
      buildSimpleButton({
        actionType: "continue-in-chat",
        targetId,
        expectedRevision,
        projectId,
        row: buttons,
        status,
        label: "Вернуться в чат",
        awaitUpdate: false,
      }),
    );
    return;
  }
  const hint = document.createElement("p");
  hint.className = "card-busy-notice";
  hint.textContent = state === "queued" ? "Передано в чат." : "Вернуться в чат";
  buttons.append(hint);
}

/** Build the full action row for one card: approve/reject/hide/unhide/
 * retire/restore/edit from `actions` (already allowlist-filtered by
 * `resolveCardActions`), plus `vary`/`regenerate` handled once, together,
 * from their own combined state (`resolveGrantCardState`, ui/
 * paid-action-state.js -- the pending-request cache first, the ledger's
 * own `snapshot.actions` only once nothing is pending, client repair 2)
 * -- never per action type, since "Одно платное действие на карточку"
 * (condition 1) means the two share one busy/notice state. Returns `null`
 * when there is nothing at all to show (condition 10: "в blocked нет
 * пустых рядов действий" -- an empty `actions` list, from an allowlist
 * that currently grants nothing, never becomes a stray empty row). */
export function buildCardActionsRow({ actions, record, kind, targetId, expectedRevision, projectId, actionEntries, allowedActions,
  hookTargetId = targetId, lockTargetIds = null, working = false, generateLabel = null }) {
  const hasGenerate = actions.includes("generate");
  const hasVary = actions.includes("vary");
  const hasRegenerate = actions.includes("regenerate");
  const grantState =
    hasGenerate || hasVary || hasRegenerate || lockTargetIds
      ? resolveGrantCardState({ projectId, actions: actionEntries, targetId, targetIds: lockTargetIds, working }) : null;
  const otherActions = actions.filter((action) => !["generate", "vary", "regenerate"].includes(action));
  if (otherActions.length === 0 && !hasGenerate && !hasVary && !hasRegenerate && !grantState) {
    return null;
  }

  const row = document.createElement("div");
  row.className = "card-actions-row";
  row.dataset.hook = "card-actions";

  const status = buildStatusLine();
  const buttons = document.createElement("div");
  buttons.className = "card-actions-buttons";
  const moreItems = [];

  for (const actionType of otherActions) {
    let control;
    if (actionType === "reject") {
      control = buildCommentForm({
          actionType: "reject",
          targetId,
          hookTargetId,
          expectedRevision,
          projectId,
          key: draftKey(projectId, kind, hookTargetId),
          row: buttons,
          status,
        });
    } else if (actionType === "edit") {
      control = buildPromptEditControl({ targetId, expectedRevision, projectId, currentText: record.text || "", row: buttons, status });
    } else {
      control = buildSimpleButton({ actionType, targetId, hookTargetId, expectedRevision, projectId, row: buttons, status });
    }
    if (["reject", "hide", "unhide", "retire", "restore"].includes(actionType)) {
      const wrap = document.createElement("div");
      wrap.className = "more-menu-control";
      wrap.append(control);
      moreItems.push({ id: actionType, content: wrap });
    } else {
      buttons.append(control);
    }
  }

  if (grantState && grantState.kind === "blocked") {
    // A genuinely blocked target -- queued/running/outcome_unknown from
    // the *ledger* (snapshot.actions), not this render's own in-flight
    // submit -- stays a plain notice, no grant-area control at all
    // (ui/grant-action.js's own protocol is unrelated to this state: it
    // owns "a submit just happened", not "the server already told us this
    // is busy").
    const notice = document.createElement("p");
    notice.className = "card-busy-notice";
    notice.textContent = grantState.text;
    buttons.append(notice);
    if (grantState.returnToChat) {
      appendReturnToChatControl({ buttons, targetId, expectedRevision, projectId, status, allowedActions, actionEntries });
    }
  } else if (hasGenerate || hasVary || hasRegenerate || grantState?.kind === "pending") {
    // grantState here is null (render both types normally), a "notice"
    // (both types render, plus the notice) or a "pending" (an unconfirmed
    // request already exists -- only that one type renders, in retry
    // mode). ui/grant-action.js's buildGrantArea owns both types' DOM and
    // the whole submit protocol together now (client repair 2) -- see
    // that module's own file banner for why one grant type used to leave
    // the other fully clickable after a lost response.
    const grantArea = buildGrantArea({
      grantState,
      hasVary,
      hasRegenerate,
      hasGenerate,
      targetId,
      hookTargetId,
      targetIds: { generate: hookTargetId, vary: targetId, regenerate: targetId },
      generateLabel,
      expectedRevision,
      projectId,
      actionEntries,
      status,
      controlRoot: buttons,
    });
    buttons.append(grantArea);
    const regenerate = grantArea.querySelector('[data-action="regenerate"]');
    if (regenerate?.parentNode) {
      moreItems.push({ id: "regenerate", content: regenerate.parentNode });
    }
  }

  if (moreItems.length > 0) {
    buttons.append(buildMoreMenu({ projectId, targetId: hookTargetId, items: moreItems }));
  }

  row.append(status, buttons);
  return row;
}

/**
 * Decorate every already-rendered `[data-hook="image-card"]`/
 * `[data-hook="video-card"]` inside `root` (ui/media.js's gallery,
 * mounted in `main`) with its own action row and drag-and-drop, gated on
 * `view_stage.allowed_actions` and whether that card's own collection is
 * the current stage's (see `isCardCollectionCurrent`). A card whose
 * collection is not current gets no row at all -- read-only, ticket 08
 * point 10.
 */
export function decorateResultCards(root, snapshot) {
  if (!root || !snapshot) {
    return;
  }
  const project = snapshot.active_project;
  const viewStage = snapshot.view_stage || {};
  const allowedActions = viewStage.allowed_actions;
  const currentStage = viewStage.current_stage;
  const revision = snapshot.revision;
  const projectId = project && project.id;
  const actionEntries = snapshot.actions;

  const kinds = [
    { hook: "image-card", collectionKind: "image_result", stateKey: "image_results", groupKey: "result_id" },
    { hook: "video-card", collectionKind: "video_result", stateKey: "video_results", groupKey: "result_id" },
  ];

  // Client repair 2, condition 17's own first invariant: pending-request
  // records are pruned against this *current* snapshot before any card's
  // row -- and therefore before any control reads the pending cache -- is
  // built at all, never after. Pre-repair-2, this same prune ran at the
  // very end of this function, one pass after `buildCardActionsRow` had
  // already read (and rendered from) whatever the cache still held --
  // this repair's own diagnosis: "ряд строится из записи о неподтверждённом
  // запросе раньше, чем prunePendingRequests её снимает". Target ids come
  // straight from each *current* collection's own records -- every id a
  // pending record could possibly exist for, whether or not a matching
  // DOM card happens to exist in `root` yet.
  if (projectId) {
    const allTargetIds = [];
    for (const { collectionKind, stateKey, groupKey } of kinds) {
      if (!isCardCollectionCurrent(collectionKind, currentStage)) {
        continue;
      }
      const records = project && project[stateKey];
      for (const record of Array.isArray(records) ? records : []) {
        allTargetIds.push(record.version_id || record[groupKey]);
      }
    }
    prunePendingRequests(projectId, actionEntries, allTargetIds);
  }

  for (const { hook, collectionKind, stateKey, groupKey } of kinds) {
    const records = project && project[stateKey];
    const isCurrent = isCardCollectionCurrent(collectionKind, currentStage);
    const currentIds = isCurrent && Array.isArray(records) ? records.map((item) => item.version_id) : [];
    const reorderOffered = isCurrent && Array.isArray(allowedActions) && allowedActions.includes("reorder");
    const cards = root.querySelectorAll(`[data-hook="${hook}"]`);
    // Scoped to this one collectionKind (repair condition 8/10): pruning
    // with a prefix any other namespace (prompts, stage, the other result
    // kind) would never match keeps three independent decoration passes
    // from clobbering each other's still-open drafts -- see
    // ui/card-drafts.js's own `pruneDrafts` banner.
    const knownDraftKeysForKind = new Set();
    for (const card of cards) {
      const groupId = card.dataset.resultId;
      const versionId = card.dataset.versionId;
      const record = findGroupRecord(records, { groupId, versionId }, groupKey);
      if (!record) {
        continue;
      }
      // Runs for every card unconditionally, before the read-only guard
      // below skips a past-stage card's interactive row entirely -- see
      // markRetiredCard's own banner for why this has no "only while
      // current" qualifier.
      if (record.retired) {
        markRetiredCard(card);
      }
      const decisionBadge = buildCardDecisionBadge(record.decisions);
      if (decisionBadge) {
        card.append(decisionBadge);
      }
      if (!isCurrent) {
        continue; // read-only: a past-stage card gets no action row.
      }
      const targetId = record.version_id || record[groupKey];
      const actions = resolveCardActions(allowedActions, "result", record);
      knownDraftKeysForKind.add(draftKey(projectId, collectionKind, targetId));
      const row = buildCardActionsRow({
        actions,
        record,
        kind: collectionKind,
        targetId,
        expectedRevision: revision,
        projectId,
        actionEntries,
        allowedActions,
      });
      if (row) {
        card.append(row);
      }
      if (reorderOffered && !record.retired) {
        const reorderControls = buildReorderButtons({
          collectionKey: stateKey,
          currentIds,
          id: targetId,
          expectedRevision: revision,
          projectId,
        });
        const moreMenu = row?.querySelector('[data-hook="more-menu"]');
        if (!appendMoreMenuContent(moreMenu, reorderControls)) {
          card.append(reorderControls);
        }
        attachDragReorder(card, {
          id: targetId,
          collectionKey: stateKey,
          getCurrentIds: () => currentIds,
          expectedRevision: revision,
          projectId,
          getStatus: () => reorderControls.querySelector(".card-action-status"),
        });
      }
    }
    if (projectId) {
      pruneDrafts(`${projectId}::${collectionKind}::`, knownDraftKeysForKind);
      // Reorder's own 409/network-failure message (repair condition 8) is
      // one draft per collection, not per item. Cleared by its own exact
      // key -- never a shared `${projectId}::reorder::` prefix scan, which
      // would also match ui/card-reorder.js's `decorateSceneReorder`'s own
      // "scenes" draft and delete it out from under a sibling render pass
      // that legitimately still needs it (ui/card-drafts.js's own
      // `pruneDrafts` banner: each caller owns only its own namespace).
      if (!reorderOffered) {
        clearDraft(draftKey(projectId, "reorder", stateKey));
      }
    }
  }
}

/**
 * Decorate every already-rendered `[data-hook="prompt-entry"]` inside
 * `root` (ui/media.js's reference panel, mounted in the inspector) with an
 * action row -- approve/reject-with-comment/edit -- but only for an
 * `image_prompts` entry while `image_plan` is the current stage (motion
 * prompts never get dashboard decisions -- studio/decision_planners.py
 * routes every card decision at `motion` to `video_results`, never
 * `motion_prompts`).
 */
export function decoratePromptCards(root, snapshot) {
  if (!root || !snapshot) {
    return;
  }
  const project = snapshot.active_project;
  const viewStage = snapshot.view_stage || {};
  const allowedActions = viewStage.allowed_actions;
  const currentStage = viewStage.current_stage;
  const revision = snapshot.revision;
  const projectId = project && project.id;
  const actionEntries = snapshot.actions;
  const records = project && project.image_prompts;

  // No `buildCardDecisionBadge` here, unlike `decorateResultCards` --
  // repair condition 4/R03 is that a decision becomes *visible*, and for
  // a prompt it already is: `studio/decision_planners.py`'s own
  // `_plan_card_decision` writes a prompt's decision straight into its
  // `status` field (never a separate `decision`/`decisions[]`-only fact
  // the way a result's is), so ui/media.js's own status badge
  // ("Принято"/"Нужны правки", from MEDIA_STATUS_LABELS -- ticket 08
  // repair 2/craft finding 5 unified the word with card-model.js's
  // CARD_ACTION_LABELS.reject button label and
  // ui/decision-history.js's DECISION_VALUE_LABELS.rejected) already
  // shows it. A second badge here would repeat the exact same word
  // right next to the first one -- confirmed live: a fixture prompt
  // with both `status: "approved"` and `decisions: [...]` rendered
  // "Принято" twice on one card before this fix.
  if (!isCardCollectionCurrent("prompt", currentStage)) {
    return;
  }
  const cards = root.querySelectorAll('[data-hook="prompt-entry"]');
  // Two namespaces, not one: `buildCommentForm`'s own reject draft
  // (`draftKey(projectId, "prompt", targetId)`) and
  // `buildPromptEditControl`'s own edit draft (`"prompt-edit"`) never
  // share a key for the same prompt, so each is pruned by its own scoped
  // prefix (see ui/card-drafts.js's `pruneDrafts` banner).
  const knownRejectDraftKeys = new Set();
  const knownEditDraftKeys = new Set();
  for (const card of cards) {
    const groupId = card.dataset.promptId;
    const versionId = card.dataset.versionId;
    const record = findGroupRecord(records, { groupId, versionId }, "prompt_id");
    if (!record) {
      continue;
    }
    const targetId = record.version_id || record.prompt_id;
    const actions = resolveCardActions(allowedActions, "prompt", record);
    knownRejectDraftKeys.add(draftKey(projectId, "prompt", targetId));
    knownEditDraftKeys.add(draftKey(projectId, "prompt-edit", targetId));
    const row = buildCardActionsRow({
      actions,
      record,
      kind: "prompt",
      targetId,
      expectedRevision: revision,
      projectId,
      actionEntries,
      allowedActions,
    });
    if (row) {
      card.append(row);
    }
  }
  if (projectId) {
    pruneDrafts(`${projectId}::prompt::`, knownRejectDraftKeys);
    pruneDrafts(`${projectId}::prompt-edit::`, knownEditDraftKeys);
  }
}
