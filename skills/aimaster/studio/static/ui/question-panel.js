// Always-visible questions entry point (ticket 14: "Вопросы видны и в
// blocked без сценария"). `snapshot.questions` exists independent of
// whether `active_project` carries a script/scenes at all (task 01's
// `build_snapshot` fills it from `QuestionStore.pending`, not from project
// state -- interfaces.md, "Из таска 01") -- this renderer has the same
// shape as ui/media.js's renderReferencePanel/renderMediaGallery: paints
// nothing and returns `false` when there is nothing pending, so a caller
// only appends its wrapper when there is something to show.
//
// Deliberately never imports ui/question-dialog.js (or vice versa): the two
// only ever meet through the bubbling `studio:open-question` DOM event
// (opening) and the `data-hook="questions-panel"`/`"question-open"`
// contract documented below (ui/question-dialog.js's own
// `pruneAnsweredQuestionRow`, closing) -- the same decoupling ui/media.js's
// `studio:open-viewer` and ui/viewer.js already use for cards vs. the
// lightbox, so this module stays swappable/testable without ever touching
// the dialog's own DOM-singleton machinery.

/**
 * One clickable entry per pending question. Ticket 14 repair, condition 7:
 * the button dispatches `studio:open-question` *on itself* (bubbling), the
 * same shape ui/media.js's own `dispatchOpenViewer` uses for
 * `studio:open-viewer` -- never on `document` directly, which would make
 * `event.target` the document itself and leave ui/question-dialog.js's own
 * `attachQuestionOpenListener` with no real element to hand back to
 * `openQuestionModal` as `trigger` (so focus could never return to the
 * control that opened it, only to a same-id re-find that happens to still
 * exist).
 */
export function renderQuestionsPanel(root, questions) {
  const list = Array.isArray(questions) ? questions : [];
  if (list.length === 0) {
    return false;
  }
  const section = document.createElement("section");
  section.className = "questions-panel";
  section.dataset.hook = "questions-panel";
  section.setAttribute("aria-label", "Вопросы");

  const heading = document.createElement("h2");
  heading.textContent = "Вопросы";
  section.append(heading);

  const ul = document.createElement("ul");
  ul.className = "questions-panel-list";
  for (const question of list) {
    if (!question || typeof question.question_id !== "string") {
      continue;
    }
    const li = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "questions-panel-item";
    button.dataset.hook = "question-open";
    button.dataset.questionId = question.question_id;
    const text = document.createElement("span");
    text.className = "questions-panel-item-text";
    text.textContent = question.text || "";
    button.append(text);
    button.addEventListener("click", () => {
      button.dispatchEvent(
        new CustomEvent("studio:open-question", { bubbles: true, detail: { question } }),
      );
    });
    li.append(button);
    ul.append(li);
  }
  section.append(ul);
  root.append(section);
  return true;
}
