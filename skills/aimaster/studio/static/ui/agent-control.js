import { requestAgentPrompt } from "./chat-prompt-dialog.js";

export function exactTarget({ projectId, targetId, versionId, revision }) {
  const quote = (value) => `«${value ?? "—"}»`;
  return [
    `project_id ${quote(projectId)}`,
    targetId ? `target_id ${quote(targetId)}` : "",
    versionId ? `version_id ${quote(versionId)}` : "",
    Number.isFinite(revision) ? `snapshot revision ${revision}` : "",
  ].filter(Boolean).join(", ");
}

export function agentControl({ label, title, prompt, attachmentHint = "", className = "agent-prompt-button", targetId = "", action = "" }) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = className;
  button.textContent = label;
  if (targetId) button.dataset.targetId = targetId;
  if (action) button.dataset.action = action;
  button.addEventListener("click", () => requestAgentPrompt({ title, prompt, attachmentHint }, button));
  return button;
}
