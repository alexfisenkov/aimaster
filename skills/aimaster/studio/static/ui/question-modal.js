// Barrel for the question-modal subsystem (spec §6, ticket 14). Ticket 14
// repair, condition 10: the original single 1071-line module is now three
// focused ones --
//   - ./question-model.js  -- pure answer model: validation, wire-payload
//     building, read-only description, the per-`kind` behavior table.
//   - ./question-dialog.js -- the DOM singleton overlay, its focus-trap
//     lifecycle, submit/close/liveness-sync.
//   - ./question-panel.js  -- the always-visible "Вопросы" panel entry
//     point (visible even in `blocked` with no scenario yet).
// This file exists only so every *external* import keeps working
// unchanged: ui/shell.js imports `renderQuestionsPanel` from here, app.js
// imports `attachQuestionOpenListener`/`syncQuestionModalWithQuestions`
// from here, and tests/ui/question-modal.test.mjs imports the full set
// (plus the pure model functions) from here too. Nothing outside this
// module's own three pieces needs to know the split exists at all.

export {
  validateSelection,
  buildAnswerPayload,
  describeAnswer,
  resolveSubtitle,
  showsCustomSection,
  describeValidationHint,
  QUESTION_KIND_TABLE,
} from "./question-model.js";

export {
  openQuestionModal,
  closeQuestionModal,
  syncQuestionModalWithQuestions,
  attachQuestionOpenListener,
} from "./question-dialog.js";

export { renderQuestionsPanel } from "./question-panel.js";
