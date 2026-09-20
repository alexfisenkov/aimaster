import { submitActionsSequentially, resolveActionErrorMessage } from "./actions.js";
import { draftKey, getDraft, setDraft, clearDraft } from "./card-drafts.js";
import { markControlHooks, noteCardFocusPending, requestProjectRefresh, OUTCOME_UNCONFIRMED_TEXT } from "./card-forms.js";

export function videoModeModel(snapshot, scene, { readOnly = false } = {}) {
  const positions = snapshot.active_project?.positions || [];
  const accepted = (kind) => positions.some((item) => item.scene_id === scene.scene_id && item.kind === kind && item.status === "accepted");
  const first = accepted("first_frame"), last = accepted("last_frame");
  const current = !readOnly && snapshot.view_stage?.current_stage === "motion" && (snapshot.view_stage.allowed_actions || []).includes("set-video-mode");
  const reasons = {
    first: !scene.need_first ? "Нужные кадры не отмечены на шаге промптов." : !first ? "Первый кадр ещё не принят." : "",
    firstlast: !scene.need_first || !scene.need_last ? "Нужные кадры не отмечены на шаге промптов." : !first ? "Первый кадр ещё не принят." : !last ? "Последний кадр ещё не принят." : "",
    references: "",
  };
  return { sceneId: scene.scene_id, projectId: snapshot.active_project.id, revision: snapshot.revision,
    firstAccepted: first, lastAccepted: last, selected: scene.video_mode || (scene.need_first ? "first" : "references"),
    choices: [["first", "Из первого кадра"], ["firstlast", "Первый и последний кадр"], ["references", "По референсам и промпту"]]
      .map(([mode, label]) => ({ mode, label, reason: reasons[mode], enabled: current && !reasons[mode] })) };
}

export function renderVideoMode(model) {
  const section = document.createElement("section"); section.className = "video-mode";
  const heading = document.createElement("h4"); heading.textContent = "Как оживляем кадр"; section.append(heading);
  const key = draftKey(model.projectId, "position-video-mode", model.sceneId);
  let draft = getDraft(key);
  if (draft?.savedRevision < model.revision) { clearDraft(key); draft = null; }
  const status = document.createElement("p"); status.className = "video-mode-status"; status.setAttribute("role", "status");
  status.textContent = draft?.message || "";
  for (const choice of model.choices) {
    const button = document.createElement("button"); button.type = "button"; button.className = "video-mode-choice";
    markControlHooks(button, model.sceneId, `video-mode-${choice.mode}`);
    button.disabled = !choice.enabled || draft?.saving === true;
    button.setAttribute("aria-pressed", String(choice.mode === model.selected));
    const title = document.createElement("span"); title.textContent = `${choice.mode === model.selected ? "● " : "○ "}${choice.label}`;
    const reason = document.createElement("span"); reason.className = "video-mode-reason"; reason.textContent = choice.reason;
    button.append(title, reason);
    button.addEventListener("click", async () => {
      if (choice.mode === model.selected) return;
      noteCardFocusPending(model.sceneId, `video-mode-${choice.mode}`);
      status.textContent = "Сохраняется…"; setDraft(key, { saving: true, message: status.textContent });
      const result = await submitActionsSequentially({ actions: [{ actionType: "set-video-mode", targetId: model.sceneId, payload: { mode: choice.mode } }],
        expectedRevision: model.revision, controls: [...section.querySelectorAll("button")] });
      const saved = result.ok && result.confirmed !== false && result.completed === 1;
      status.textContent = saved ? "Сохранено" : result.ok ? OUTCOME_UNCONFIRMED_TEXT : resolveActionErrorMessage(result.code);
      setDraft(key, { saving: false, message: status.textContent, ...(saved ? { savedRevision: result.confirmedRevision } : {}) });
      if (saved || ["revision_conflict", "action_failed"].includes(result.code)) requestProjectRefresh(model.projectId);
    });
    section.append(button);
  }
  const inputs = document.createElement("div"); inputs.className = "video-mode-inputs";
  for (const label of [model.firstAccepted && "Первый кадр принят", model.lastAccepted && "Последний кадр принят"].filter(Boolean)) {
    const chip = document.createElement("span"); chip.textContent = label; inputs.append(chip);
  }
  section.append(inputs, status); return section;
}
