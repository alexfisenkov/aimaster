// Окно «запрос агенту» (редизайн 2026-09-23): белое, радиус 18, не шире
// 560px; на телефоне выезжает шторкой снизу (это CSS). Текст промпта
// строит вызывающий — здесь он только показывается и копируется.

import { showToast } from "./v2/toast.js";

let dialogRefs = null;
let returnFocus = null;

function copyText(textarea) {
  const value = textarea.value;
  if (navigator.clipboard?.writeText) {
    return navigator.clipboard.writeText(value);
  }
  textarea.focus();
  textarea.select();
  const copied = document.execCommand("copy");
  textarea.setSelectionRange(0, 0);
  return copied ? Promise.resolve() : Promise.reject(new Error("copy_failed"));
}

function buildDialog() {
  const dialog = document.createElement("dialog");
  dialog.className = "chat-prompt-dialog";
  dialog.dataset.hook = "chat-prompt-dialog";

  const form = document.createElement("form");
  form.method = "dialog";
  form.className = "chat-prompt-dialog-card";

  const heading = document.createElement("h2");
  heading.id = "chat-prompt-dialog-title";
  heading.textContent = "Запрос для агента";
  const description = document.createElement("p");
  description.id = "chat-prompt-dialog-description";
  description.className = "chat-prompt-dialog-description";
  description.textContent = "Скопируйте текст и отправьте его агенту в рабочий чат.";
  const attachment = document.createElement("p");
  attachment.className = "chat-prompt-dialog-attachment";
  attachment.hidden = true;
  const textarea = document.createElement("textarea");
  textarea.readOnly = true;
  textarea.rows = 8;
  textarea.setAttribute("aria-label", "Текст запроса агенту");
  const status = document.createElement("p");
  status.className = "chat-prompt-dialog-status";
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  const controls = document.createElement("div");
  controls.className = "chat-prompt-dialog-controls";
  const copy = document.createElement("button");
  copy.type = "button";
  copy.className = "chat-prompt-copy";
  copy.textContent = "Скопировать запрос";
  const close = document.createElement("button");
  close.type = "submit";
  close.textContent = "Закрыть";
  close.className = "chat-prompt-close";
  controls.append(close, copy);
  form.append(heading, description, attachment, textarea, status, controls);
  dialog.append(form);
  dialog.setAttribute("aria-labelledby", heading.id);
  dialog.setAttribute("aria-describedby", description.id);
  document.body.append(dialog);

  copy.addEventListener("click", async () => {
    try {
      await copyText(textarea);
      status.dataset.tone = "ok";
      status.textContent = "Скопировано. Вернитесь в чат и отправьте запрос агенту.";
      showToast("Запрос скопирован");
    } catch {
      status.dataset.tone = "warn";
      status.textContent = "Не удалось скопировать автоматически. Выделите текст и скопируйте вручную.";
      textarea.focus();
      textarea.select();
    }
  });
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });
  dialog.addEventListener("close", () => {
    if (returnFocus?.isConnected) returnFocus.focus();
    returnFocus = null;
  });
  return { dialog, heading, attachment, textarea, status };
}

export function openAgentPrompt({ title, prompt, attachmentHint = "", trigger = null } = {}) {
  if (!dialogRefs) dialogRefs = buildDialog();
  if (dialogRefs.dialog.open) dialogRefs.dialog.close();
  returnFocus = trigger;
  dialogRefs.heading.textContent = title || "Запрос для агента";
  dialogRefs.textarea.value = typeof prompt === "string" ? prompt : "";
  dialogRefs.attachment.textContent = attachmentHint;
  dialogRefs.attachment.hidden = !attachmentHint;
  dialogRefs.status.textContent = "";
  delete dialogRefs.status.dataset.tone;
  dialogRefs.dialog.showModal();
  dialogRefs.textarea.focus();
}

export function requestAgentPrompt(detail, trigger = null) {
  document.dispatchEvent(new CustomEvent("studio:agent-prompt", {
    bubbles: true,
    detail: { ...detail, trigger },
  }));
}

export function attachAgentPromptListener() {
  document.addEventListener("studio:agent-prompt", (event) => {
    openAgentPrompt(event?.detail || {});
  });
}
