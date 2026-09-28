// Листалка версий монтажа, новые слева: номер, кто собрал, когда, что
// изменилось. «Сделать текущей» — прямое действие дашборда (POST
// …/montage/restore): локально, бесплатно, обратимо — версии не удаляются.
// «Принять» — главная кнопка подвала «Принять ролик» (решение `approve`
// стадии «Сборка»): она принимает текущую версию. Экран перерисовывается по
// каждому ответу опроса: куда пролистана листалка, помнит `scrolled` по
// проекту; что летит и чем кончилось — montage-action.js.

import { badge } from "./board-bits.js";
import { el } from "./dom.js";
import { actionButton } from "./montage-action.js";
import { postMontage, refusalText } from "./montage-api.js";
import { versionRows } from "./montage-model.js";
import { showToast } from "./toast.js";

const scrolled = new Map(); // проект → scrollLeft листалки

function restoreButton(project, revision, row, onChanged) {
  const key = `${project.id}:${row.id}`;
  const wrap = el("div", "am-version-actions");
  wrap.append(actionButton({
    slot: `restore:${key}`, projectId: project.id, targetId: `montage:${key}`, action: "restore",
    label: "Сделать текущей", busyLabel: "Отправляется…", className: "v2-chat-button",
    send: async () => {
      const result = await postMontage(project.id, "restore", { version: row.id, expected_revision: revision });
      if (result.ok) {
        showToast(`Текущая версия — ${row.label}`);
        onChanged(project.id);
        return "";
      }
      if (result.code === "revision_conflict") onChanged(project.id);
      return refusalText(result);
    },
  }));
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

/** Листалка встаёт на прежнее место, когда её уже вставили в страницу:
 * до этого у неё нет ширины и `scrollLeft` не ставится. */
function keepScroll(projectId, list) {
  list.addEventListener("scroll", () => scrolled.set(projectId, list.scrollLeft), { passive: true });
  const left = scrolled.get(projectId);
  if (left) queueMicrotask(() => { list.scrollLeft = left; });
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
  keepScroll(project.id, list);
  box.append(list);
  if (flags.restore) box.append(el("p", "am-versions-hint", "«Принять ролик» внизу принимает текущую версию."));
  return box;
}
