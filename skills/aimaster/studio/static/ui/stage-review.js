// Compatibility composition root for stages that have not moved approval
// into a dedicated step renderer. Task 39 gives audio/assembly their own.
import { renderStageActions } from "./stage-approval.js";

/** The single entry point ui/shell.js calls: assembly panel and the
 * stage-approval bar, in that fixed order -- each independently gated, so
 * only the ones the current stage actually unlocks ever paint anything. */
export function renderStageReview(root, snapshot) {
  if (!root || !snapshot) {
    return;
  }
  if (["image_plan", "image_results", "motion", "audio", "assembly"].includes(snapshot.view_stage?.current_stage)) {
    return;
  }
  renderStageActions(root, snapshot);
}
