// Файл текущей версии: «Скачать» (тот же /assets/<id> с download=1 — имя
// файла даёт сервер), «Показать в папке» (только на компьютере: сервер
// открывает Finder, Проводник или файловый менеджер Linux), путь к файлу
// текстом и «Скопировать путь». Путь — от папки над рабочей, ровно как на
// экране: абсолютных путей сервер не отдаёт. Версию и адрес файла даёт
// снимок проекта, путь — живое состояние, если оно про ту же версию.
// «Показать в папке» помнит «летит» и отказ через перерисовку
// (montage-action.js); у всех контролов — метки фокуса (`markControlHooks`).

import { markControlHooks } from "../card-forms.js";
import { el } from "./dom.js";
import { actionButton } from "./montage-action.js";
import { postMontage, refusalText } from "./montage-api.js";
import { downloadHref, versionRows } from "./montage-model.js";
import { showToast } from "./toast.js";

function downloadLink(project, href) {
  const link = el("a", "v2-chat-button", "Скачать");
  link.href = href;
  link.setAttribute("download", "");
  markControlHooks(link, `montage:${project.id}`, "download");
  link.dataset.part = "am-download";
  return link;
}

function revealButton(project) {
  const wrap = actionButton({
    slot: `reveal:${project.id}`, projectId: project.id, targetId: `montage:${project.id}`,
    action: "reveal", label: "Показать в папке", className: "v2-chat-button", busyText: "Открываю папку…",
    send: async () => {
      const result = await postMontage(project.id, "reveal");
      return result.ok ? "" : refusalText(result);
    },
  });
  wrap.className = "am-inline am-reveal"; // на телефоне её прячет и CSS
  return wrap;
}

/** Буфер обмена; не пустил (нет разрешения, встроенный браузер) — выделить
 * путь на экране и попробовать старым способом: выделенное останется. */
async function copyPath(node, text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    try {
      window.getSelection()?.selectAllChildren(node);
      return document.execCommand("copy");
    } catch {
      return false;
    }
  }
}

function pathLine(project, shown) {
  const line = el("div", "am-file-path");
  const text = el("code", "am-file-path-text", shown);
  text.dataset.part = "am-file-path";
  const copy = el("button", "am-link-button", "Скопировать путь");
  copy.type = "button";
  markControlHooks(copy, `montage:${project.id}`, "copy-path");
  copy.addEventListener("click", async () => {
    showToast((await copyPath(text, shown)) ? "Путь скопирован"
      : "Не получилось скопировать — путь выделен, скопируйте его сами");
  });
  line.append(text, copy);
  return line;
}

export function renderFileCard({ project, status, flags }) {
  const current = versionRows(project).find((row) => row.current) || null;
  const card = el("section", "v2-card am-file");
  card.dataset.hook = "am-file";
  card.append(el("h2", "v2-card-title", current ? `Ролик ${current.label}` : "Ролик"));
  if (!current) {
    card.append(el("p", "v2-section-hint", "Ролик ещё не собран — первую версию соберёт агент."));
    return card;
  }
  const shown = status?.current_version === current.id ? status?.file?.shown || null : null;
  const actions = el("div", "am-file-actions");
  const href = downloadHref(current.assetUrl);
  if (href) actions.append(downloadLink(project, href));
  if (flags.reveal && shown) actions.append(revealButton(project));
  if (actions.childElementCount) card.append(actions);
  if (shown) card.append(pathLine(project, shown));
  return card;
}
