// Task 08 repair 1, condition 11 ("порядок" is its own module) and repair
// condition 9 (spec §7: drag-and-drop alongside "Выше/Ниже"). Every piece
// of full-order reordering lives here: the two pure order computations
// (`buildReorderOrder`, one step; `computeDropOrder`, an arbitrary drop),
// the one submit path both the buttons and drag-and-drop call, the
// Up/Down buttons themselves, native HTML5 drag-and-drop wiring, and the
// scene-block decorator.
//
// Drag-and-drop is native HTML5 DnD (`draggable`, `dragstart`/`dragover`/
// `drop`) -- no inline `style="..."`/`on*="..."` attributes anywhere (the
// page CSP has no `'unsafe-inline'`); every affordance is a CSS class
// toggled through `classList`, every handler an `addEventListener` call
// from this module. It is a *supplementary* pointer-only affordance --
// "Выше/Ниже" stays the keyboard-accessible path (spec §10).

import { submitAction } from "./actions.js";
import { draftKey, getDraft, setDraft } from "./card-drafts.js";
import { isCardCollectionCurrent } from "./card-model.js";
import { buildStatusLine, finishFreeActionSubmit, noteCardFocusPending, requestProjectRefresh } from "./card-forms.js";

/**
 * The full reordered id list after moving `id` one step (`direction` -1 or
 * +1) within `currentIds` -- `null` when `id` is not found or the move
 * would go out of bounds (already first/last), the caller's cue to do
 * nothing rather than submit a no-op reorder. Pure; `currentIds` is never
 * mutated.
 */
export function buildReorderOrder(currentIds, id, direction) {
  const list = Array.isArray(currentIds) ? currentIds.slice() : [];
  const index = list.indexOf(id);
  if (index < 0) {
    return null;
  }
  const target = index + direction;
  if (target < 0 || target >= list.length) {
    return null;
  }
  const [moved] = list.splice(index, 1);
  list.splice(target, 0, moved);
  return list;
}

/**
 * The full reordered id list after dropping `draggedId` on `targetId`,
 * `placement` naming which side of the target it lands
 * (`"before"`/`"after"`) -- `null` when either id is missing from
 * `currentIds`, or they are the same id (a drop back onto itself is a
 * no-op, not a one-item "move"). Pure; mirrors `buildReorderOrder`'s own
 * contract (never mutates `currentIds`, never submits anything itself).
 */
export function computeDropOrder(currentIds, draggedId, targetId, placement) {
  const list = Array.isArray(currentIds) ? currentIds : [];
  if (!draggedId || !targetId || draggedId === targetId) {
    return null;
  }
  if (!list.includes(draggedId) || !list.includes(targetId)) {
    return null;
  }
  const withoutDragged = list.filter((id) => id !== draggedId);
  const targetIndex = withoutDragged.indexOf(targetId);
  const insertAt = placement === "after" ? targetIndex + 1 : targetIndex;
  withoutDragged.splice(insertAt, 0, draggedId);
  return withoutDragged;
}

/**
 * The one submit path both the Up/Down buttons and drag-and-drop go
 * through (repair condition 9: "перетаскивание отправляет тот же полный
 * порядок... через ту же функцию, что и кнопки"). `status`'s message
 * survives a repaint via ui/card-drafts.js (repair condition 8: "409 на
 * порядке показывает сообщение, которое переживает перерисовку") -- a
 * reorder has no typed text to preserve, only the outcome message itself,
 * so the "draft" here is just `{message, sourceId}`.
 *
 * `sourceId` (client repair 2, non-blocking note 5: "сообщение о 409...
 * показывается один раз, а не под каждым элементом") is the one item this
 * particular attempt was submitted *for* -- the Up/Down pair's own `id`,
 * or drag-and-drop's own drop target. The whole collection shares one
 * draft key (there is exactly one in-flight reorder at a time for a given
 * collection), but every item in that collection builds its *own*
 * `buildReorderButtons` call and therefore its own status line; without
 * `sourceId`, every one of them would restore and display the identical
 * persisted message after a repaint, N times over. `buildReorderButtons`
 * only shows it back on the one item whose `id` matches.
 */
async function submitReorder({ collectionKey, order, expectedRevision, projectId, controls, status, sourceId }) {
  const key = draftKey(projectId, "reorder", collectionKey);
  status.textContent = "Отправляется…";
  const result = await submitAction({
    actionType: "reorder",
    targetId: collectionKey,
    payload: { order },
    expectedRevision,
    controls,
  });
  finishFreeActionSubmit({
    result,
    status,
    projectId,
    saveDraft: () => setDraft(key, { message: status.textContent, sourceId }),
    clearDraftKey: key,
  });
}

/** Up/down reorder controls for one item in a flat, full-order collection.
 * `atStart`/`atEnd` disable the direction that would be a no-op. The
 * status line restores whatever message a previous 409/network failure
 * left (condition 8) instead of always starting blank -- but only on the
 * one item that message was actually about (`draft.sourceId === id`,
 * client repair 2's own fix for the message showing up under every item
 * in the collection instead of just once). */
export function buildReorderButtons({ collectionKey, currentIds, id, expectedRevision, projectId }) {
  const wrap = document.createElement("div");
  wrap.className = "card-reorder-buttons";
  const status = buildStatusLine();
  const draft = getDraft(draftKey(projectId, "reorder", collectionKey));
  status.textContent = draft && draft.sourceId === id ? draft.message || "" : "";

  function move(direction) {
    return async () => {
      const order = buildReorderOrder(currentIds, id, direction);
      if (!order) {
        return;
      }
      noteCardFocusPending(id, direction < 0 ? "reorder-up" : "reorder-down");
      await submitReorder({
        collectionKey,
        order,
        expectedRevision,
        projectId,
        controls: [upButton, downButton],
        status,
        sourceId: id,
      });
    };
  }

  const index = currentIds.indexOf(id);
  const upButton = document.createElement("button");
  upButton.type = "button";
  upButton.className = "card-reorder-button";
  upButton.dataset.hook = "card-control";
  upButton.dataset.targetId = id;
  upButton.dataset.action = "reorder-up";
  upButton.disabled = index <= 0;
  upButton.textContent = "Выше";
  upButton.setAttribute("aria-label", "Переместить выше");
  upButton.addEventListener("click", move(-1));

  const downButton = document.createElement("button");
  downButton.type = "button";
  downButton.className = "card-reorder-button";
  downButton.dataset.hook = "card-control";
  downButton.dataset.targetId = id;
  downButton.dataset.action = "reorder-down";
  downButton.disabled = index < 0 || index >= currentIds.length - 1;
  downButton.textContent = "Ниже";
  downButton.setAttribute("aria-label", "Переместить ниже");
  downButton.addEventListener("click", move(1));

  wrap.append(upButton, downButton, status);
  return wrap;
}

/**
 * Wire native HTML5 drag-and-drop onto one already-rendered list item
 * (a scene block, a result card) so dropping it on a sibling reorders the
 * whole collection through the exact same `submitReorder` the Up/Down
 * buttons call.
 *
 * `getCurrentIds`/`getStatus` are thunks, not values -- corrected comment,
 * client repair 2, craft-review finding 9: this used to claim they "read
 * the current order at drop time", which overstated what a thunk alone
 * buys. What it actually protects against: every `drop` handler on this
 * element calls it fresh, rather than each one closing over its own
 * separately-captured snapshot of `currentIds`/`status` from whenever
 * `attachDragReorder` itself ran -- the callers (`decorateResultCards`,
 * `decorateSceneReorder`) both re-run this on every repaint, rebuilding
 * every list item's own listeners from scratch each time, so in normal
 * operation this element and its thunk are already this render pass's
 * own. What a thunk here does *not* do is read some live, always-current
 * order straight from the DOM or a later render than the one that built
 * it -- `getCurrentIds`'s own closure (`decorateResultCards`'s `currentIds`,
 * `decorateSceneReorder`'s `scenes`) is still fixed to whichever snapshot
 * this particular `decorateResultCards`/`decorateSceneReorder` call was
 * given.
 */
export function attachDragReorder(element, { id, collectionKey, getCurrentIds, expectedRevision, projectId, getStatus }) {
  element.draggable = true;
  element.addEventListener("dragstart", (event) => {
    event.dataTransfer.setData("text/plain", id);
    event.dataTransfer.effectAllowed = "move";
    element.classList.add("card-dragging");
  });
  element.addEventListener("dragend", () => {
    element.classList.remove("card-dragging");
  });
  element.addEventListener("dragover", (event) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    element.classList.add("card-drag-over");
  });
  element.addEventListener("dragleave", () => {
    element.classList.remove("card-drag-over");
  });
  element.addEventListener("drop", async (event) => {
    event.preventDefault();
    element.classList.remove("card-drag-over");
    const draggedId = event.dataTransfer.getData("text/plain");
    if (!draggedId || draggedId === id) {
      return;
    }
    const rect = element.getBoundingClientRect();
    const placement = event.clientY - rect.top > rect.height / 2 ? "after" : "before";
    const order = computeDropOrder(getCurrentIds(), draggedId, id, placement);
    if (!order) {
      return;
    }
    const status = getStatus();
    if (!status) {
      return;
    }
    await submitReorder({ collectionKey, order, expectedRevision, projectId, controls: [], status, sourceId: id });
  });
}

/**
 * Decorate every already-rendered scene block inside `root`
 * (ui/scenario.js's own `[data-hook="scenario-block-select"]` headers,
 * mounted in `main`) with reorder controls plus drag-and-drop -- only
 * while `image_plan` is current and `reorder` is allowed. Targets are
 * found only through that documented hook (repair condition 10: "цели
 * ищутся только по документированным data-hook, не по классам
 * scenario.js") -- the reorder controls are appended as the header's own
 * next sibling (`header.parentElement`, i.e. the block's own `<li>`) so
 * this never needs to also query `.scenario-block`/`.scenario-block-body`,
 * classes this module does not own.
 */
export function decorateSceneReorder(root, snapshot) {
  if (!root || !snapshot) {
    return;
  }
  const project = snapshot.active_project;
  const viewStage = snapshot.view_stage || {};
  const allowedActions = viewStage.allowed_actions;
  if (
    !isCardCollectionCurrent("scenes", viewStage.current_stage) ||
    !Array.isArray(allowedActions) ||
    !allowedActions.includes("reorder")
  ) {
    return;
  }
  const scenes = Array.isArray(project && project.scenes) ? project.scenes : [];
  const getCurrentIds = () => scenes.map((scene) => scene.scene_id);
  const projectId = project && project.id;
  const revision = snapshot.revision;
  const headers = root.querySelectorAll('[data-hook="scenario-block-select"]');
  for (const header of headers) {
    const sceneId = header.dataset.sceneId;
    if (!sceneId) {
      continue;
    }
    // Client repair 2, craft-review finding 9: the null-check used to run
    // *after* `block.append(reorderControls)` had already dereferenced
    // `block` -- a defensive check that guarded nothing, since a null
    // `block` would already have thrown one line above it. Checked first
    // now, before anything touches `block` at all.
    const block = header.parentElement;
    if (!block) {
      continue;
    }
    const reorderControls = buildReorderButtons({
      collectionKey: "scenes",
      currentIds: getCurrentIds(),
      id: sceneId,
      expectedRevision: revision,
      projectId,
    });
    block.append(reorderControls);
    const status = reorderControls.querySelector(".card-action-status");
    attachDragReorder(block, {
      id: sceneId,
      collectionKey: "scenes",
      getCurrentIds,
      expectedRevision: revision,
      projectId,
      getStatus: () => status,
    });
  }
}
