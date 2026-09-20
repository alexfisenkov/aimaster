// Task 08 repair 1, condition 11 ("история решений" is its own module),
// implementing repair condition 7: the inspector's "История решений" --
// every reached stage's own milestone decision plus, while a scene is
// selected, that scene's own linked prompt/result decision history.

import { resolveLabel, STAGE_LABELS } from "./state.js";
import { findGroupRecord } from "./card-model.js";
import { mediaCards, resolveDecisionTone } from "./media.js";

// `reopened` -- ticket 16 condition 4/G05: `stage_decisions` gains
// `{stage: "scenario", decision: "reopened", comment}` whenever the
// dashboard or chat sends `reopen-scenario` (studio/decision_stages.py's
// `build_reopen_mutation`). Without an entry here `formatStageDecisions`
// below silently dropped it -- the same allowlist-only rule every entry in
// this dictionary already follows, not a special case for this one value.
export const DECISION_VALUE_LABELS = Object.freeze({
  approved: "Принято",
  rejected: "Нужны правки",
  reopened: "Возвращено к правке",
});

/** `active_project.stage_decisions[]` -> `{stage, stageLabel, decisionLabel,
 * comment}`, dropping an entry whose `decision` value is not one of the
 * two known ones rather than guessing at a label for it. `stageLabel` is
 * `undefined` for a stage name this dictionary does not recognize --
 * rendered as nothing, never the raw token (repair condition 7: "«Решения
 * по этапам» показывают название этапа из STAGE_LABELS" -- absent before
 * this repair, the raw `stage` key was captured but never actually
 * rendered). */
export function formatStageDecisions(stageDecisions) {
  const list = Array.isArray(stageDecisions) ? stageDecisions : [];
  const result = [];
  for (const entry of list) {
    const decisionLabel = resolveLabel(DECISION_VALUE_LABELS, entry && entry.decision);
    if (!decisionLabel) {
      continue;
    }
    const stage = typeof entry.stage === "string" ? entry.stage : "";
    result.push({
      stage,
      stageLabel: resolveLabel(STAGE_LABELS, stage),
      decisionLabel,
      comment: typeof entry.comment === "string" ? entry.comment : "",
    });
  }
  return result;
}

/** One card's own `decisions[]` (append-only `{decision, comment}`) ->
 * `{decisionLabel, comment}[]`, same allowlist rule as
 * `formatStageDecisions`. */
export function formatCardDecisions(decisions) {
  const list = Array.isArray(decisions) ? decisions : [];
  const result = [];
  for (const entry of list) {
    const decisionLabel = resolveLabel(DECISION_VALUE_LABELS, entry && entry.decision);
    if (!decisionLabel) {
      continue;
    }
    result.push({
      decisionLabel,
      comment: typeof entry.comment === "string" ? entry.comment : "",
    });
  }
  return result;
}

/** Short, unambiguous noun for which kind of card a history entry's own
 * `groupLabel` names (repair condition 4/spec §2: "к какой карточке...
 * относятся"). Motion prompts never get dashboard decisions at all (see
 * ui/card-decorate.js's own `decoratePromptCards` banner -- every card
 * decision at `motion` routes to `video_results`, never `motion_prompts`),
 * so there is no fourth entry here to stay consistent with the three
 * collections `collectCardDecisionEntries` below actually reads. */
const CARD_GROUP_KIND_LABELS = Object.freeze({
  prompt: "Промпт",
  image: "Изображение",
  video: "Видео",
});

/** "Изображение · v2 · текущая" / "Промпт · v1" -- the ordinal and
 * current-ness are never recomputed here; both come straight from
 * ui/media.js's own `mediaCards` (`withOrdinals`/`isLinkedAsCurrent`),
 * the one place task 07 already resolves "which version is this, and is
 * it the current one" correctly. */
function buildCardGroupLabel(kindLabel, ordinal, current) {
  return current ? `${kindLabel} · v${ordinal} · текущая` : `${kindLabel} · v${ordinal}`;
}

/**
 * One card kind's own decision history for `selectedSceneId`, across
 * *every* version of the group linked to that scene -- not only the
 * current one (repair condition 4: "комментарий к отклонённому промпту не
 * пропадает после появления v2 из чата: история показывает решения всех
 * версий группы с подписью версии"). A rejected v1's own comment used to
 * vanish the moment a new v2 became current, because the old code looked
 * up exactly one record, by the scene's own singular link alone.
 *
 * `cards` is `mediaCards(...)`'s own array for this kind -- already
 * filtered to real ids, ordinal-numbered and current-flagged by task 07's
 * `withOrdinals`/`isLinkedAsCurrent`, so "which version is this, and is it
 * current" is never a second, separate calculation here (repair condition
 * 4: "карточка для истории берётся из текущих карточек mediaCards(...),
 * а не отдельным расчётом"). `records` is the matching raw snapshot
 * collection (`image_prompts`/`image_results`/`video_results`) -- the one
 * place `decisions[]` itself actually lives; `mediaCards`'s own cards
 * never carry it, task 07's scope there is display, not decisions.
 */
function collectGroupDecisionEntries(cards, records, groupKey, kindLabel, selectedSceneId) {
  const entries = [];
  for (const card of Array.isArray(cards) ? cards : []) {
    if (card.sceneId !== selectedSceneId) {
      continue;
    }
    const record = findGroupRecord(records, { versionId: card.versionId }, groupKey);
    if (!record) {
      continue;
    }
    const groupLabel = buildCardGroupLabel(kindLabel, card.ordinal, card.current);
    for (const decision of formatCardDecisions(record.decisions)) {
      entries.push({ ...decision, groupLabel });
    }
  }
  return entries;
}

/**
 * Every card-decision source relevant to `selectedSceneId` right now --
 * not just the *current* stage's own collection (repair condition 7:
 * "Решения карточек с комментариями не пропадают после одобрения стадии"
 * -- a prompt's own reject comment used to vanish the instant the project
 * moved on to image_results, because the old code only ever looked at
 * whichever single collection matched `current_stage`).
 *
 * Instead, every collection the snapshot itself still carries is checked,
 * via `mediaCards(snapshot, selectedSceneId)` (repair condition 4 -- see
 * `collectGroupDecisionEntries`'s own banner): `image_prompts` is present
 * in `active_project` from `image_plan` onward and *stays* present at
 * every later stage (projection.py's own cumulative gate, mirrored by
 * `mediaCards` itself), so a prompt's history is visible for the rest of
 * the project's life, never only while `image_plan` happens to be current.
 * The same reasoning is what fixes "На последних стадиях видеопроекта
 * показывается история изображений, а не видео": `video_results` stays
 * present from `motion` onward for a non-photo project (and `mediaCards`
 * already gates it to `undefined` for a photo one), so its own history
 * keeps showing through audio/assembly too, instead of the old code's
 * `currentStage === "motion"` check (false on every later stage) silently
 * falling back to the *image* collection.
 *
 * Exported (mirroring ui/media.js's own `keepForSelectedScene`) so
 * tests/ui/decision-history.test.mjs can assert both fixed bugs directly,
 * without a DOM: `renderDecisionHistory` itself is DOM-only and verified
 * solely through the browser visual gate. Takes the full `snapshot` (not
 * just `active_project`) because `mediaCards` itself does.
 */
export function collectCardDecisionEntries(snapshot, selectedSceneId) {
  if (!selectedSceneId || !snapshot) {
    return [];
  }
  const project = snapshot.active_project || {};
  const cards = mediaCards(snapshot, selectedSceneId);
  const entries = [];
  entries.push(
    ...collectGroupDecisionEntries(
      cards.prompts.image,
      project.image_prompts,
      "prompt_id",
      CARD_GROUP_KIND_LABELS.prompt,
      selectedSceneId,
    ),
  );
  entries.push(
    ...collectGroupDecisionEntries(
      cards.imageResults,
      project.image_results,
      "result_id",
      CARD_GROUP_KIND_LABELS.image,
      selectedSceneId,
    ),
  );
  entries.push(
    ...collectGroupDecisionEntries(
      cards.videoResults,
      project.video_results,
      "result_id",
      CARD_GROUP_KIND_LABELS.video,
      selectedSceneId,
    ),
  );
  return entries;
}

/** One history row: an optional group/stage label first (`entry.groupLabel`
 * for a card entry -- "к какой карточке и какой версии", repair condition
 * 4; `entry.stageLabel` for a stage entry, repair condition 7 -- the two
 * never both exist on the same entry, so checking either is unambiguous),
 * then the decision itself, then its comment if any. */
function buildDecisionListItem(entry) {
  const li = document.createElement("li");
  const prefixLabel = entry.groupLabel || entry.stageLabel;
  if (prefixLabel) {
    const prefix = document.createElement("span");
    prefix.className = "decision-history-stage";
    prefix.textContent = prefixLabel;
    li.append(prefix);
  }
  const label = document.createElement("span");
  label.className = "media-status-tag";
  label.dataset.tone = resolveDecisionTone(entry.decision || entry.decisionLabel);
  label.textContent = entry.decisionLabel;
  li.append(label);
  if (entry.comment) {
    const comment = document.createElement("p");
    comment.className = "decision-history-comment";
    comment.textContent = entry.comment;
    li.append(comment);
  }
  return li;
}

/**
 * Render the decision history the inspector shows (ticket 08 point 9):
 * every reached stage's own milestone decision
 * (`active_project.stage_decisions`, each with its own stage name --
 * repair condition 7), plus -- while a scene is selected -- every linked
 * prompt/result's own history (repair condition 7, see
 * `collectCardDecisionEntries`). Returns `true` only when it painted
 * something, matching every other inspector section's own "nothing yet"
 * contract.
 */
export function renderDecisionHistory(root, snapshot, selectedSceneId) {
  if (!root || !snapshot) {
    return false;
  }
  const project = snapshot.active_project || {};
  const stageEntries = formatStageDecisions(project.stage_decisions);
  const cardEntries = collectCardDecisionEntries(snapshot, selectedSceneId);

  if (stageEntries.length === 0 && cardEntries.length === 0) {
    return false;
  }

  const section = document.createElement("div");
  section.dataset.hook = "decision-history";
  const heading = document.createElement("h3");
  heading.textContent = "История решений";
  section.append(heading);

  if (cardEntries.length > 0) {
    const list = document.createElement("ul");
    list.className = "decision-history-list";
    for (const entry of cardEntries) {
      list.append(buildDecisionListItem(entry));
    }
    section.append(list);
  }

  if (stageEntries.length > 0) {
    const stageHeading = document.createElement("h4");
    stageHeading.textContent = "Решения по этапам";
    section.append(stageHeading);
    const list = document.createElement("ul");
    list.className = "decision-history-list";
    for (const entry of stageEntries) {
      list.append(buildDecisionListItem(entry));
    }
    section.append(list);
  }

  root.append(section);
  return true;
}
