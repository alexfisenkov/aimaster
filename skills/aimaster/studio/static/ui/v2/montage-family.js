// Free local T05 format actions. Every result is read back from the HTTP gateway.
import { el } from "./dom.js";
import { getMontage, postMontage, refusalText } from "./montage-api.js";
import { refreshMontage } from "./montage-feed.js";
import { t } from "./locale.js";

export function renderMontageFamily({ project, revision, status, model, finished }) {
  if (finished || status?.engine?.state !== "installed") return null;
  const section = el("section", "v2-card am-format-actions"); section.dataset.hook = "am-format-actions";
  section.append(el("h2", "v2-card-title", t("Формат и выдача")));
  const select = el("select", "am-family-select"); select.setAttribute("aria-label", t("Стиль монтажа"));
  for (const [key, label] of [["basic", "Базовый"], ["dynamic", "Динамичный"], ["cinematic", "Кинематографичный"]]) { const option = el("option", "", t(label)); option.value = key; select.append(option); }
  const feedback = el("p", "am-family-action-status"); feedback.setAttribute("role", "status");
  const preview = el("video", "am-format-preview"); preview.controls = true; preview.playsInline = true; preview.hidden = true;
  function button(label, send) {
    const node = el("button", "v2-chat-button", label); node.type = "button";
    node.addEventListener("click", async () => {
      node.disabled = true; feedback.textContent = t("Выполняю…");
      const result = await send();
      feedback.textContent = result.ok ? t("Готово") : refusalText(result);
      node.disabled = false;
      if (result.ok) { await refreshMontage(); document.dispatchEvent(new CustomEvent("studio:refresh-snapshot", { detail: { projectId: project.id } })); }
    }); return node;
  }
  const actions = el("div", "am-format-buttons");
  actions.append(select,
    button(t("Превью"), async () => {
      const result = await postMontage(project.id, "preview", { style: select.value, duration: 6 });
      if (result.ok && result.body?.url?.startsWith("/assets/")) { preview.src = result.body.url; preview.hidden = false; }
      return result;
    }),
    button(t(project?.montage?.current_version ? "Улучшить ролик" : "Собрать ролик"), () =>
      postMontage(project.id, "build", { expected_revision: revision, style: select.value, improve: Boolean(project?.montage?.current_version) })),
  );
  if (model?.model_hash) actions.append(button(t("Применить стиль"), () => postMontage(project.id, "preset", {
    expected_revision: revision, expected_model_hash: model.model_hash, style: select.value,
  })));
  if (project?.montage?.current_version) actions.append(button(t("Экспорт проекта"), async () => {
    const result = await postMontage(project.id, "export", { version: project.montage.current_version });
    if (result.ok && result.body?.url?.startsWith("/assets/")) {
      const link = el("a", "v2-chat-button", t("Скачать пакет")); link.href = result.body.url; link.setAttribute("download", "");
      section.append(link);
    }
    return result;
  }));
  section.append(actions, preview, feedback);
  getMontage(project.id, "styles").then((result) => {
    if (!result.ok || !select.isConnected) return;
    const known = Array.isArray(result.body?.styles) ? result.body.styles : [];
    for (const item of known) {
      if (!item?.ref || [...select.options].some((option) => option.value === item.ref)) continue;
      const option = el("option", "", item.profile?.label || t("Личный стиль")); option.value = item.ref; select.append(option);
    }
  });
  return section;
}
