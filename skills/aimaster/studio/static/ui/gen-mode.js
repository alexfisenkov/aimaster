import { resolveActionErrorMessage, submitActionsSequentially } from "./actions.js";
import { clearDraft, draftKey, getDraft, setDraft } from "./card-drafts.js";
import { markControlHooks, noteCardFocusPending, OUTCOME_UNCONFIRMED_TEXT, requestProjectRefresh } from "./card-forms.js";

const MODES = Object.freeze([
  Object.freeze({ id: "per_scene", title: "Кадр за кадром", description: "Каждая сцена генерируется отдельно, со своим промптом и решением." }),
  Object.freeze({ id: "one_shot", title: "Одним заходом, весь ролик", description: "Один длинный промпт с посекундной разбивкой и всеми референсами." }),
]);

export function genModeModel(snapshot, { readOnly = false } = {}) {
  const project = snapshot?.active_project;
  if (!project || project.type === "photo") return null;
  return {
    projectId: project.id,
    revision: snapshot.revision,
    selected: project.gen_mode === "one_shot" ? "one_shot" : "per_scene",
    canEdit: !readOnly && snapshot?.view_stage?.allowed_actions?.includes("set-gen-mode"),
    modes: MODES,
  };
}

export function renderGenMode(snapshot, { readOnly = false } = {}) {
  const model = genModeModel(snapshot, { readOnly });
  if (!model) return null;
  const section = document.createElement("section");
  section.className = "plan-section gen-mode";
  section.dataset.hook = "gen-mode";
  const heading = document.createElement("h2");
  heading.textContent = "Как генерируем ролик";
  const description = document.createElement("p");
  description.className = "plan-section-description";
  description.textContent = "Выберите способ один раз на этом шаге. Позже его можно изменить после возврата к сценарию.";
  const choices = document.createElement("div");
  choices.className = "gen-mode-options";
  const key = draftKey(model.projectId, "step-plan-gen-mode", "project");
  let draft = getDraft(key);
  if (Number.isFinite(draft?.savedRevision) && model.revision > draft.savedRevision) {
    clearDraft(key);
    draft = undefined;
  }
  const status = document.createElement("p");
  status.className = "plan-status";
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  status.textContent = draft?.message || "";
  const buttons = [];
  for (const mode of model.modes) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "gen-mode-option";
    button.dataset.genMode = mode.id;
    button.dataset.selected = String(model.selected === mode.id);
    button.setAttribute("aria-pressed", String(model.selected === mode.id));
    const title = document.createElement("strong");
    title.textContent = mode.title;
    const copy = document.createElement("span");
    copy.textContent = mode.description;
    button.append(title, copy);
    if (model.canEdit) {
      markControlHooks(button, "project", `set-gen-mode:${mode.id}`);
      button.disabled = draft?.saving === true;
      button.addEventListener("click", async () => {
        if (mode.id === model.selected) return;
        noteCardFocusPending("project", `set-gen-mode:${mode.id}`);
        status.textContent = "Сохраняется…";
        setDraft(key, { message: status.textContent, saving: true, lastAction: `set-gen-mode:${mode.id}` });
        const result = await submitActionsSequentially({
          actions: [{ actionType: "set-gen-mode", targetId: "project", payload: { mode: mode.id } }],
          expectedRevision: model.revision,
          controls: buttons,
        });
        if (result.ok && result.confirmed !== false && result.completed === 1) {
          status.textContent = "Сохранено";
          setDraft(key, { message: status.textContent, saving: false, savedRevision: result.confirmedRevision, lastAction: `set-gen-mode:${mode.id}` });
          requestProjectRefresh(model.projectId);
        } else {
          status.textContent = result.ok ? OUTCOME_UNCONFIRMED_TEXT : resolveActionErrorMessage(result.code);
          setDraft(key, { message: status.textContent, saving: false, lastAction: `set-gen-mode:${mode.id}` });
          if (!result.ok && ["revision_conflict", "action_failed"].includes(result.code)) requestProjectRefresh(model.projectId);
        }
      });
    } else {
      button.disabled = true;
    }
    buttons.push(button);
    choices.append(button);
  }
  section.append(heading, description, choices, status);
  return section;
}
