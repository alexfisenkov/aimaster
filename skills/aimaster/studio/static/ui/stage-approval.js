// Task 08 repair 1: the "Одобрить стадию"/"Вернуть на доработку" bar
// (spec §3), implementing repair condition 2 -- the approve half must
// disappear once `view_stage.gate_status` is already `approved`, while
// reject stays (that path is how a finished project returns to review,
// task 11's own `decision_stages.apply_project_status`).
//
// A stage-level decision reuses the exact same `action_type` strings a
// card-level one does (`approve`/`reject`) -- the server tells the two
// apart purely by `target_id` (studio/decision_planners.py's
// `plan_approve`/`plan_reject`: `target_id in MILESTONE_TARGETS` is a
// milestone decision). This module only ever addresses the milestone
// form: `target_id` is always the current stage's own name. The DOM's own
// `data-action` hook stays `approve-stage`/`reject-stage`
// (interfaces.md's task-08 hooks list), distinct from that wire-level
// `action_type`.

import { buildCommentForm, buildSimpleButton, buildStatusLine } from "./card-forms.js";
import { draftKey, pruneDrafts } from "./card-drafts.js";
import { agentControl, exactTarget } from "./agent-control.js";

/** Every stage that gets its own "Одобрить стадию"/"Вернуть на доработку"
 * bar -- `scenario` is excluded (ui/scenario.js's dedicated
 * approve-scenario/revise-scenario controls own it), matching the
 * server's own `decision_stages.MILESTONE_TARGETS` exactly (every stage of
 * either sequence but `scenario`; a photo project simply never reaches
 * `motion` or `audio`). There is no `qa` stage any more (G12). */
export const STAGE_APPROVAL_TARGETS = Object.freeze([
  "image_plan",
  "image_results",
  "motion",
  "audio",
  "assembly",
]);

/** Whether the stage-approval bar should render at all: the current stage
 * is one of `STAGE_APPROVAL_TARGETS` and `approve`/`reject` are actually
 * in `allowed_actions` right now (they are not while `gate_status` is
 * `blocked` -- domain.py's `allowed_actions` collapses to
 * `["continue-in-chat"]` there, and the two always travel together
 * otherwise: `domain._STAGE_ACTIONS` never lists one of them for a stage
 * without the other). */
export function stageApprovalVisible(viewStage) {
  const currentStage = viewStage && viewStage.current_stage;
  const allowed = (viewStage && viewStage.allowed_actions) || [];
  return STAGE_APPROVAL_TARGETS.includes(currentStage) && allowed.includes("approve");
}

/**
 * Whether the "Одобрить стадию" button specifically should render --
 * repair condition 2: `assembly` (the one stage `derive_view_stage` never
 * advances `current_stage` past once reached, domain.py) stays
 * `allowed_actions`-eligible for `approve` even after it has already been
 * approved once (the server-side allowlist is purely per-stage, not
 * per-gate-status), so this is the one client-side check standing between
 * a finished project and a lingering "Одобрить стадию" button the server
 * would now refuse (`decision_stages.plan_milestone`'s own repair,
 * condition 14). `gate_status === "approved"` never happens for an
 * *earlier* stage -- every one of those leaves `current_stage` the
 * instant it is approved -- so this only ever actually differs from
 * `stageApprovalVisible` on `assembly`.
 */
export function approveStageVisible(viewStage) {
  return stageApprovalVisible(viewStage) && viewStage.gate_status !== "approved";
}

/**
 * Render "Одобрить стадию" / "Вернуть на доработку" into `root`. `approve`
 * submits immediately (`buildSimpleButton`, shared with every card-level
 * single-click decision); `reject` reveals a comment field
 * (`buildCommentForm`, the same shared control a card's own `reject`
 * uses -- repair condition 10: "одна форма комментария на все места").
 * Returns `true` only when it painted the bar.
 */
export function renderStageActions(root, snapshot, {
  approveLabel = "Одобрить стадию",
  heading: headingText = "Решение по стадии",
  description = "",
  canApprove = true,
} = {}) {
  const viewStage = snapshot && snapshot.view_stage;
  if (!snapshot || !stageApprovalVisible(viewStage)) {
    return false;
  }
  const stage = viewStage.current_stage;
  const revision = snapshot.revision;
  const projectId = snapshot.active_project && snapshot.active_project.id;

  const wrap = document.createElement("div");
  wrap.className = "stage-actions";
  wrap.dataset.hook = "stage-actions";
  const heading = document.createElement("h3");
  heading.textContent = headingText;
  wrap.append(heading);
  if (description) {
    const copy = document.createElement("p");
    copy.className = "stage-actions-description";
    copy.textContent = description;
    wrap.append(copy);
  }

  const status = buildStatusLine();
  const buttons = document.createElement("div");
  buttons.className = "card-actions-buttons";

  if (approveStageVisible(viewStage)) {
    const approve = buildSimpleButton({
        actionType: "approve",
        targetId: stage,
        expectedRevision: revision,
        projectId,
        row: buttons,
        status,
        label: approveLabel,
        hookAction: "approve-stage",
      });
    approve.disabled = !canApprove;
    buttons.append(approve);
  }

  const rejectKey = draftKey(projectId, "stage", stage);
  buttons.append(
    buildCommentForm({
      actionType: "reject",
      targetId: stage,
      expectedRevision: revision,
      projectId,
      key: rejectKey,
      row: buttons,
      status,
      toggleLabel: "Вернуть на доработку",
      focusHookAction: "reject-stage",
    }),
  );

  wrap.append(buttons, status);
  root.append(wrap);

  // A previous stage's own reject draft (repair condition 8/10: "черновики
  // исчезнувших целей удаляются") -- only one stage bar is ever visible at
  // a time, so anything under this project's `::stage::` namespace that is
  // not *this* stage's own key is stale.
  if (projectId) {
    pruneDrafts(`${projectId}::stage::`, new Set([rejectKey]));
  }

  return true;
}

export function renderChatStageActions(root, snapshot, stage, { approveLabel = "Одобрить стадию" } = {}) {
  const projectId = snapshot?.active_project?.id;
  if (!projectId || !STAGE_APPROVAL_TARGETS.includes(stage)) return false;
  const wrap = document.createElement("div");
  wrap.className = "stage-actions";
  wrap.dataset.hook = "stage-actions-chat";
  wrap.append(
    agentControl({ label: approveLabel, title: approveLabel, targetId: stage, action: "approve-stage-chat", className: "agent-prompt-button agent-prompt-button-primary",
      prompt: `Открой ${exactTarget({ projectId, targetId: stage, revision: snapshot.revision })}. Проверь readiness и обязательные результаты этой стадии. Если есть блокеры, перечисли их и не меняй состояние; иначе одобри стадию штатной командой Creator Studio и сообщи результат.` }),
    agentControl({ label: "Вернуть на доработку", title: `Доработать стадию ${stage}`, targetId: stage, action: "reject-stage-chat",
      prompt: `Открой ${exactTarget({ projectId, targetId: stage, revision: snapshot.revision })}. Спроси комментарий к доработке, покажи точное решение и после моего подтверждения верни стадию на доработку штатной командой Creator Studio.` }),
  );
  root.append(wrap);
  return true;
}
