import { submitActionsSequentially, resolveActionErrorMessage } from "./actions.js";
import { draftKey, getDraft, setDraft, clearDraft } from "./card-drafts.js";
import { markControlHooks, noteCardFocusPending, requestProjectRefresh, OUTCOME_UNCONFIRMED_TEXT } from "./card-forms.js";
import { requestAgentPrompt } from "./chat-prompt-dialog.js";
import { exactTarget } from "./agent-control.js";

export function videoModeModel(snapshot, scene, { readOnly = false } = {}) {
  const project = snapshot.active_project || {};
  const positions = project.positions || [];
  const accepted = (kind) => positions.some((item) => item.scene_id === scene.scene_id && item.kind === kind && item.status === "accepted");
  const first = accepted("first_frame"), last = accepted("last_frame");
  const current = !readOnly && snapshot.view_stage?.current_stage === "motion" && (snapshot.view_stage.allowed_actions || []).includes("set-video-mode");
  const reasons = {
    first: !scene.need_first ? "Нужные кадры не отмечены на шаге промптов." : !first ? "Первый кадр ещё не принят." : "",
    firstlast: !scene.need_first || !scene.need_last ? "Нужные кадры не отмечены на шаге промптов." : !first ? "Первый кадр ещё не принят." : !last ? "Последний кадр ещё не принят." : "",
    references: "",
  };
  const scenes = [...(Array.isArray(project.scenes) ? project.scenes : [])]
    .sort((left, right) => (left?.order || 0) - (right?.order || 0));
  const sceneIndex = scenes.findIndex((item) => item?.scene_id === scene.scene_id);
  const previousScene = sceneIndex > 0 ? scenes[sceneIndex - 1] : null;
  const previousPosition = previousScene
    ? positions.find((item) => item?.kind === "video" && item?.scene_id === previousScene.scene_id)
    : null;
  return { sceneId: scene.scene_id, projectId: project.id, revision: snapshot.revision, readOnly,
    previousSceneId: previousScene?.scene_id || null,
    previousResultVersionId: previousScene?.links?.video_result_id || null,
    previousAccepted: previousPosition?.status === "accepted",
    firstPlanned: scene.need_first === true,
    continuityStrategy: scene.continuity_strategy || null,
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
    button.disabled = !model.readOnly && (!choice.enabled || draft?.saving === true);
    button.setAttribute("aria-pressed", String(choice.mode === model.selected));
    const title = document.createElement("span"); title.textContent = `${choice.mode === model.selected ? "● " : "○ "}${choice.label}`;
    const reason = document.createElement("span"); reason.className = "video-mode-reason"; reason.textContent = choice.reason;
    button.append(title, reason);
    button.addEventListener("click", async () => {
      if (model.readOnly) {
        requestAgentPrompt({ title: `Оживить кадр: ${choice.label}`,
          prompt: `Открой ${exactTarget({ projectId: model.projectId, targetId: model.sceneId, revision: model.revision })}. Установи video_mode ${choice.mode} (${choice.label}) штатной командой Creator Studio. Проверь необходимые принятые кадры и референсы, сообщи блокеры и попроси подтверждение перед изменением; генерацию не запускай.` }, button);
        return;
      }
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
  if (model.previousSceneId) {
    const continuity = document.createElement("button");
    continuity.type = "button";
    continuity.className = "agent-prompt-button video-continuity-action";
    continuity.textContent = "Связать с предыдущей сценой";
    continuity.addEventListener("click", () => requestAgentPrompt({
      title: `Непрерывность перед сценой ${model.sceneId}`,
      prompt: `Открой ${exactTarget({ projectId: model.projectId, targetId: model.sceneId, revision: model.revision })}. Перед генерацией этой per_scene-сцены проверь предыдущую сцену «${model.previousSceneId}» и её active result version «${model.previousResultVersionId || "не определена"}» (accepted=${model.previousAccepted}). Текущая continuity_strategy: «${model.continuityStrategy || "не выбрана"}». Если она уже выбрана и соответствует моему текущему тексту, не спрашивай повторно. Иначе предложи три варианта: (1) продолжить от принятого предыдущего видео — скопировать его в новый media-файл, зарегистрировать video_reference и добавить scene-local reference usage=continue; (2) извлечь последний кадр и использовать как start frame; (3) независимый клип с общими референсами. Для варианта 2 учти: planned first frame=${model.firstPlanned}; если он не был запланирован на image_plan, честно объясни, что потребуется вернуться назад и заново пройти последующие стадии, а не обещай недоступную запись на motion. Если персонажи, одежда, реквизит, локация и свет почти не меняются, рекомендуй вариант 1. Не используй неaccepted/hidden/retired/stale результат. Проверь live schema выбранной модели: video continuation, motion control и last-frame — разные режимы, конфликтующие inputs не совмещай. После выбора зафиксируй question lifecycle и обязательно запиши strategy штатной командой scene continuity с точной revision; без read-back continuity_strategy генерацию не запускай. Затем проверь точный reference/frame mapping и пройди model-specific writing-guide gate для video/continue до prompt или запуска.`,
    }, continuity));
    section.append(continuity);
  }
  const inputs = document.createElement("div"); inputs.className = "video-mode-inputs";
  for (const label of [model.firstAccepted && "Первый кадр принят", model.lastAccepted && "Последний кадр принят"].filter(Boolean)) {
    const chip = document.createElement("span"); chip.textContent = label; inputs.append(chip);
  }
  section.append(inputs, status); return section;
}
