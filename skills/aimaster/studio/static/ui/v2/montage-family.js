// Free local format/delivery actions. Presentation survives snapshot repaints.
import { el, chatButton } from "./dom.js";
import { assembleFinal } from "./screen-prompts.js";
import { getMontage, postMontage, refusalText } from "./montage-api.js";
import { refreshMontage } from "./montage-feed.js";
import { loopbackUrl } from "./montage-model.js";
import { inTelegram, isPhone } from "./responsive.js";
import { t } from "./locale.js";

const states = new Map();
function presentation(project) {
  const key = `${project.id}:${project.assembly_mode}:${project.montage?.current_version || JSON.stringify(project.assembly?.asset_ids || [])}`;
  if (!states.has(key)) {
    if (states.size >= 32) states.delete(states.keys().next().value);
    states.set(key, { style: "basic", message: "", preview: null, url: null, desk: null, busy: false });
  }
  return states.get(key);
}

export function renderMontageFamily({ project, revision, status, model, finished }) {
  const materials = project.assembly_mode === "materials";
  const installed = status?.engine?.state === "installed";
  const ready = materials ? project.assembly?.kind === "materials" : Boolean(project.montage?.current_version);
  if (!materials && !installed && !ready) return null;
  const saved = presentation(project);
  const section = el("section", "v2-card am-format-actions"); section.dataset.hook = "am-format-actions";
  section.append(el("h2", "v2-card-title", t(materials ? ready ? "Материалы готовы" : "Материалы" : "Формат и выдача")));
  const feedback = el("p", "am-family-action-status", t(saved.message)); feedback.setAttribute("role", "status");
  const links = el("div", "am-format-downloads");
  function drawLinks() {
    links.replaceChildren();
    for (const [url, label, download] of [[saved.url, "Скачать пакет", true], [saved.desk, "Перейти к монтажному столу ↗", false]]) {
      if (!url) continue;
      const link = el("a", "v2-chat-button", t(label)); link.href = url;
      if (download) link.setAttribute("download", "");
      else { link.target = "_blank"; link.rel = "noopener noreferrer"; }
      links.append(link);
    }
  }
  function button(label, send, changes = false) {
    const node = el("button", "v2-chat-button", t(label)); node.type = "button"; node.disabled = saved.busy;
    node.addEventListener("click", async () => {
      if (saved.busy) return;
      saved.busy = true; node.disabled = true; saved.message = "Выполняю…"; feedback.textContent = t(saved.message);
      const result = await send();
      saved.busy = false; saved.message = result.ok ? "Готово" : refusalText(result); feedback.textContent = t(saved.message);
      node.disabled = false; drawLinks();
      if (result.ok && changes) {
        document.dispatchEvent(new CustomEvent("studio:refresh-snapshot", { detail: { projectId: project.id } }));
        if (section.isConnected) await refreshMontage();
      }
    }); return node;
  }
  const actions = el("div", "am-format-buttons");
  if (materials && !ready) actions.append(chatButton(t("Подготовить материалы → чат"), assembleFinal(project, revision), "v2-chat-button"));
  if (!materials && installed) {
    const select = el("select", "am-family-select"); select.setAttribute("aria-label", t("Стиль монтажа"));
    for (const [key, label] of [["basic", "Базовый"], ["dynamic", "Динамичный"], ["cinematic", "Кинематографичный"]]) {
      const option = el("option", "", t(label)); option.value = key; select.append(option);
    }
    select.value = saved.style;
    select.addEventListener("change", () => { saved.style = select.value; });
    if (!saved.preview) {
      saved.preview = el("video", "am-format-preview"); saved.preview.controls = true; saved.preview.playsInline = true; saved.preview.hidden = true;
    }
    actions.append(select, button("Превью", async () => {
      const result = await postMontage(project.id, "preview", { style: saved.style, duration: 6 });
      if (result.ok && result.body?.url?.startsWith("/assets/")) { saved.preview.src = result.body.url; saved.preview.hidden = false; }
      return result;
    }), button(ready ? "Улучшить ролик" : "Собрать ролик", () => postMontage(project.id, "build", {
      expected_revision: revision, style: saved.style, improve: ready,
    }), true));
    if (!finished && model?.model_hash) actions.append(button("Применить стиль", () => postMontage(project.id, "preset", {
      expected_revision: revision, expected_model_hash: model.model_hash, style: saved.style,
    }), true));
    if (ready && !isPhone() && !inTelegram()) actions.append(button("Редактировать ролик", async () => {
      const result = await postMontage(project.id, "open-edit", { expected_revision: revision });
      if (result.ok) saved.desk = loopbackUrl(result.body?.url);
      return result;
    }, true));
    getMontage(project.id, "styles").then((result) => {
      if (!result.ok || !select.isConnected) return;
      for (const item of result.body?.styles || []) {
        if (!item?.ref || [...select.options].some((option) => option.value === item.ref)) continue;
        const option = el("option", "", item.profile?.label || t("Личный стиль")); option.value = item.ref; select.append(option);
      }
      select.value = saved.style;
    });
  }
  if (ready) actions.append(button("Экспорт проекта", async () => {
    const result = await postMontage(project.id, "export", { version: materials ? null : project.montage.current_version });
    if (result.ok && result.body?.url?.startsWith("/assets/")) saved.url = result.body.url;
    return result;
  }));
  if (materials && project.assembly?.summary) section.append(el("p", "v2-final-summary", project.assembly.summary));
  section.append(actions);
  if (saved.preview) section.append(saved.preview);
  drawLinks(); section.append(links, feedback);
  return section;
}
