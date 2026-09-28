// Запросы экрана «Сборка» к `/api/projects/<id>/montage…`
// (studio/montage_routes.py). Без DOM. Ответ — всегда `{ok: true, body}` или
// `{ok: false, code, message?}`: `message` — русский текст отказа монтажа
// (422 montage_refused), экран показывает его как есть. POST — через общий
// `postJson` (CSRF дашборда из `/api/session`). `signal` — свой таймаут
// каждого запроса (`montage-feed.js`): отменяет `fetch`, когда экран уже не
// ждёт этот ответ — старому проекту он всё равно не нужен, а новому вреден.

import { postJson } from "../actions.js";

const CODE_TEXT = Object.freeze({
  forbidden: "Дашборд не принял запрос — обновите страницу.",
  revision_conflict: "Проект только что изменился — попробуйте ещё раз.",
  network_error: "Нет связи с дашбордом.",
  session_error: "Нет связи с дашбордом — обновите страницу.",
  not_found: "Экран монтажа не нашёл проект — обновите страницу.",
  timeout: "Дашборд долго не отвечал — попробуйте ещё раз.",
});

export function montageUrl(projectId, part = "") {
  const base = `/api/projects/${encodeURIComponent(projectId)}/montage`;
  return part ? `${base}/${part}` : base;
}

export async function getMontage(projectId, part = "", fetchImpl = globalThis.fetch, signal) {
  let response;
  try {
    response = await fetchImpl(montageUrl(projectId, part), { headers: { Accept: "application/json" }, signal });
  } catch {
    return { ok: false, code: "network_error" };
  }
  let body = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (response.ok && body && typeof body === "object") return { ok: true, body };
  const error = body?.error || {};
  const result = { ok: false, code: typeof error.code === "string" ? error.code : `http_${response.status}` };
  if (typeof error.message === "string") result.message = error.message;
  return result;
}

export function postMontage(projectId, part, body = {}) {
  return postJson(montageUrl(projectId, part), body, 200);
}

/** Текст отказа для человека: русский текст сервера, иначе — по коду. */
export function refusalText(result) {
  if (typeof result?.message === "string" && result.message) return result.message;
  return CODE_TEXT[result?.code] || "Не получилось. Попробуйте ещё раз.";
}
