import { fetchCsrfToken } from "../actions.js";
import { requestAgentPrompt } from "../chat-prompt-dialog.js";
import { el } from "./dom.js";
import { familyData, loadFamilyData } from "./family-data.js";
import { t } from "./locale.js";

export function recoveryRequest(projectId, actionId, operation, revision) {
  if (!projectId || !/^action-[0-9a-f]{32}$/.test(actionId) || !["retry", "adopt", "keep"].includes(operation) || !Number.isInteger(revision) || revision < 0) return null;
  return { path: `/api/projects/${encodeURIComponent(projectId)}/recovery/${actionId}`,
    body: { operation, expected_revision: revision } };
}

export function safePreviewUrl(url) {
  return typeof url === "string" && /^\/assets\/asset-[a-f0-9]{32}(?:\?e=\d+&t=[a-f0-9]{64})?$/.test(url);
}

function positionName(project, id) {
  const position = (project.positions || []).find((item) => item.position_id === id);
  if (position?.scene_id) return (project.scenes || []).find((scene) => scene.scene_id === position.scene_id)?.title || t("Сцена");
  if (position?.kind === "audio") return t({ voice: "Голос", music: "Музыка", fx: "Эффекты", atmos: "Атмосфера" }[position.layer] || "Звук");
  if (position?.tag) return (project.references || []).find((ref) => ref.tag === position.tag)?.label || t("Референс");
  return t("Материал");
}

export async function postRecovery(projectId, actionId, operation, revision) {
  const request = recoveryRequest(projectId, actionId, operation, revision);
  if (!request) return { ok: false };
  try {
    const csrf = await fetchCsrfToken();
    const response = await fetch(request.path, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf }, body: JSON.stringify(request.body) });
    if (response.ok) return { ok: true };
    const body = await response.json().catch(() => ({}));
    return { ok: false, code: body?.error?.code };
  } catch { return { ok: false }; }
}

export function renderRecovery(snapshot) {
  const project = snapshot?.active_project;
  const rows = familyData(project?.id)?.routes?.collections || [];
  if (!project || !rows.length) return null;
  const box = el("section", "v2-card am-recovery"); box.dataset.hook = "recovery-panel";
  box.append(el("h2", "v2-card-title", t("Восстановление результата")));
  for (const item of rows) {
    const row = el("div", "am-recovery-item");
    row.dataset.actionId = item.action_id;
    row.append(el("h3", "v2-card-title", positionName(project, item.position_id)));
    row.append(el("p", "v2-section-hint", item.phase === "conflict"
      ? t("Результат сохранён, но проект изменился. Проверьте его и выберите действие.")
      : t("Получение результата не завершено. Сначала восстановите его.")));
    if (item.preview?.representation === "provider_export") row.append(el("p", "v2-section-hint", t("Выгрузка сервиса · оригинал не подтверждён")));
    if (safePreviewUrl(item.preview?.url) && item.preview.mime_type?.startsWith("image/")) {
      const wrap = el("div", "position-preview-button"); const media = el("img"); media.src = item.preview.url; media.alt = t("Восстановленный результат"); wrap.append(media); row.append(wrap);
    } else if (safePreviewUrl(item.preview?.url) && item.preview.mime_type?.startsWith("video/")) {
      const wrap = el("div", "position-preview-button"); const media = el("video"); media.src = item.preview.url; media.controls = true; media.preload = "metadata"; media.setAttribute("aria-label", t("Восстановленный результат")); wrap.append(media); row.append(wrap);
    } else if (safePreviewUrl(item.preview?.url) && item.preview.mime_type?.startsWith("audio/")) {
      const media = el("audio"); media.src = item.preview.url; media.controls = true; media.preload = "metadata"; media.setAttribute("aria-label", t("Восстановленный результат")); row.append(media);
    }
    const status = el("p", "am-family-action-status"); status.setAttribute("role", "status");
    const add = (operation, label) => {
      const button = el("button", "v2-chat-button", t(label)); button.type = "button";
      button.dataset.hook = `recovery-${operation}`;
      button.addEventListener("click", async () => {
        button.disabled = true; status.textContent = t("Проверяю результат…");
        const result = await postRecovery(project.id, item.action_id, operation, snapshot.revision);
        if (!result.ok) { status.textContent = t(result.code === "recovery_stage_approved"
          ? "Этап уже одобрен. Можно оставить текущий результат или обсудить изменение в чате."
          : "Не удалось выполнить действие. Обновите проект или продолжите в чате."); button.disabled = false; return; }
        status.textContent = t("Состояние обновлено.");
        await loadFamilyData(project.id, { force: true });
        document.dispatchEvent(new CustomEvent("studio:refresh-snapshot", { detail: { projectId: project.id } }));
      }); row.append(button);
    };
    if (["received", "blocked"].includes(item.phase)) add("retry", "Забрать готовый результат");
    if (item.phase === "conflict" && safePreviewUrl(item.preview?.url)) {
      if (item.resume_applied) row.append(el("p", "v2-section-hint", t("Результат уже добавлен. Завершите восстановление без повторного выбора.")));
      if (item.can_adopt) add("adopt", item.resume_applied ? "Завершить восстановление" : "Выбрать восстановленный");
      if (item.can_keep) add("keep", "Оставить текущий");
      if (!item.can_adopt) row.append(el("p", "v2-section-hint", t("Выбрать восстановленный сейчас нельзя: этап одобрен или исходное задание изменилось. Продолжите в чате.")));
    }
    const chat = el("button", "v2-chat-button", t(item.phase ? "Продолжить в чате" : "Забрать готовый результат")); chat.type = "button";
    chat.addEventListener("click", () => requestAgentPrompt({ title: t("Восстановление результата"),
      prompt: `Открой проект ${project.id}. Проверь состояние действия ${item.action_id} и восстанови существующий результат, если он доступен. Не запускай новую генерацию без моего подтверждения.` }, chat));
    row.append(chat, status); box.append(row);
  }
  return box;
}
