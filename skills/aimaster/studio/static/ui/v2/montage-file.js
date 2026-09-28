// Файл текущей версии: «Скачать» (тот же /assets/<id> с download=1 — имя
// файла даёт сервер), «Показать в папке» (только на компьютере: сервер
// открывает Finder, Проводник или файловый менеджер Linux), путь к файлу
// текстом и «Скопировать путь». Путь — от папки над рабочей, ровно как на
// экране: абсолютных путей сервер не отдаёт. Версию и адрес файла даёт
// снимок проекта, путь — живое состояние, если оно про ту же версию.

import { buildStatusLine, markControlHooks } from "../card-forms.js";
import { el } from "./dom.js";
import { postMontage, refusalText } from "./montage-api.js";
import { downloadHref, versionRows } from "./montage-model.js";
import { showToast } from "./toast.js";

function downloadLink(href) {
  const link = el("a", "v2-chat-button", "Скачать");
  link.href = href;
  link.setAttribute("download", "");
  link.dataset.hook = "am-download";
  return link;
}

function revealButton(project) {
  const wrap = el("span", "am-inline am-reveal");
  const button = el("button", "v2-chat-button", "Показать в папке");
  button.type = "button";
  markControlHooks(button, `montage:${project.id}`, "reveal");
  const status = buildStatusLine();
  button.addEventListener("click", async () => {
    button.disabled = true;
    status.textContent = "";
    const result = await postMontage(project.id, "reveal");
    button.disabled = false;
    if (!result.ok) status.textContent = refusalText(result);
  });
  wrap.append(button, status);
  return wrap;
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

function pathLine(project, shown) {
  const line = el("div", "am-file-path");
  const text = el("code", "am-file-path-text", shown);
  text.dataset.hook = "am-file-path";
  const copy = el("button", "am-link-button", "Скопировать путь");
  copy.type = "button";
  markControlHooks(copy, `montage:${project.id}`, "copy-path");
  copy.addEventListener("click", async () => {
    showToast((await copyText(shown)) ? "Путь скопирован"
      : "Не получилось скопировать — выделите путь и скопируйте сами");
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
  if (href) actions.append(downloadLink(href));
  if (flags.reveal && shown) actions.append(revealButton(project));
  if (actions.childElementCount) card.append(actions);
  if (shown) card.append(pathLine(project, shown));
  return card;
}
