// Листалка версий монтажа, новые слева: номер, кто собрал, когда, что
// изменилось. «Сделать текущей» — прямое действие дашборда (POST
// …/montage/restore): локально, бесплатно, обратимо — версии не удаляются.
// «Принять» — главная кнопка подвала «Принять ролик» (решение `approve`
// стадии «Сборка»): она принимает текущую версию.

import { buildStatusLine, markControlHooks, noteCardFocusPending } from "../card-forms.js";
import { badge } from "./board-bits.js";
import { el } from "./dom.js";
import { postMontage, refusalText } from "./montage-api.js";
import { repaintMontage } from "./montage-feed.js";
import { versionRows } from "./montage-model.js";
import { showToast } from "./toast.js";

// «проект:версия» — перерисовка экрана посреди запроса не вернёт кнопку
// раньше ответа и не потеряет текст отказа (он живёт до следующего нажатия).
const pending = new Set();
const refusals = new Map();

function restoreButton(project, revision, row, onChanged) {
  const key = `${project.id}:${row.id}`;
  const targetId = `montage:${key}`;
  const wrap = el("div", "am-version-actions");
  const busy = pending.has(key);
  const button = el("button", "v2-chat-button", busy ? "Отправляется…" : "Сделать текущей");
  button.type = "button";
  button.disabled = busy;
  markControlHooks(button, targetId, "restore");
  const status = buildStatusLine();
  status.textContent = busy ? "" : refusals.get(key) || "";
  button.addEventListener("click", async () => {
    noteCardFocusPending(targetId, "restore");
    pending.add(key);
    refusals.delete(key);
    button.disabled = true;
    button.textContent = "Отправляется…";
    status.textContent = "";
    const result = await postMontage(project.id, "restore", { version: row.id, expected_revision: revision });
    pending.delete(key);
    button.disabled = false;
    button.textContent = "Сделать текущей";
    if (result.ok) {
      showToast(`Текущая версия — ${row.label}`);
      onChanged(project.id);
      return;
    }
    refusals.set(key, refusalText(result));
    status.textContent = refusals.get(key);
    if (result.code === "revision_conflict") onChanged(project.id);
    else if (!wrap.isConnected) repaintMontage(project.id); // экран перерисовали, пока ждали
  });
  wrap.append(button, status);
  return wrap;
}

function versionItem(project, revision, row, flags, onChanged) {
  const item = el("li", "am-version");
  item.dataset.hook = "am-version";
  item.dataset.current = String(row.current);
  const top = el("div", "am-version-top");
  top.append(el("span", "am-version-label", row.label));
  if (row.current) top.append(badge("текущая", "ok"));
  item.append(top, el("p", "am-version-meta", [row.who, row.when].filter(Boolean).join(" · ")),
    el("p", "am-version-summary", row.summary));
  if (!row.current && flags.restore) item.append(restoreButton(project, revision, row, onChanged));
  return item;
}

export function renderVersions({ project, revision, flags, onChanged }) {
  const rows = versionRows(project);
  const box = el("section", "v2-card am-versions");
  box.dataset.hook = "am-versions";
  const head = el("div", "v2-card-head");
  head.append(el("h2", "v2-card-title", "Версии"), el("span", "v2-card-meta", String(rows.length)));
  box.append(head);
  if (!rows.length) {
    box.append(el("p", "v2-section-hint", "Версий пока нет: первую соберёт агент."));
    return box;
  }
  const list = el("ol", "am-version-list");
  list.setAttribute("aria-label", "Версии ролика, новые первыми");
  for (const row of rows) list.append(versionItem(project, revision, row, flags, onChanged));
  box.append(list);
  if (flags.restore) box.append(el("p", "am-versions-hint", "«Принять ролик» внизу принимает текущую версию."));
  return box;
}
