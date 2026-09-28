// Главные кнопки экрана «Сборка»: «Открыть монтажный стол» и «Собрать
// ролик → чат»; нет движка — «Монтажный стол не установлен» и «Установить →
// чат». Стол — HyperFrames Studio в новой вкладке, через страницу-переходник
// на её же адресе (выключает аналитику Studio, studio/montage/desk_opener.py).
// Вкладка открывается сразу по нажатию, пустой: откройся она после ответа
// сервера, браузер счёл бы её всплывающим окном. Заблокирована — после ответа
// появится ссылка «Перейти к монтажному столу». Адрес стола — только
// 127.0.0.1/localhost/[::1] (`loopbackUrl`), иначе стол «без ссылки». На
// телефоне и в Telegram стола нет (flags.desk === "hidden") — вместо него
// подсказка. После «Принять ролик» оставленный открытым стол можно только
// закрыть. Что летит и чем кончилось — montage-action.js.

import { markControlHooks } from "../card-forms.js";
import { chatButton, el } from "./dom.js";
import { actionButton } from "./montage-action.js";
import { postMontage, refusalText } from "./montage-api.js";
import { refreshMontage } from "./montage-feed.js";
import { loopbackUrl } from "./montage-model.js";
import { assembleFinal, assembleLabel, installMontage } from "./screen-prompts.js";

const PHONE_HINT = "Монтажный стол открывается на компьютере. Здесь можно смотреть версии "
  + "и просить правки словами в чате.";
const NO_LINK = "Стол открыт, но ссылки на него нет — закройте стол и откройте заново.";
const LEFT_OPEN = "Ролик принят, а монтажный стол ещё открыт — закройте его.";

function blankTab() {
  try {
    const tab = window.open("", "_blank");
    if (!tab) return null;
    tab.opener = null;
    tab.document.title = "Монтажный стол";
    tab.document.body.textContent = "Открываю монтажный стол…";
    return tab;
  } catch {
    return null;
  }
}

async function openDeskRequest(project) {
  const tab = blankTab();
  const result = await postMontage(project.id, "desk");
  const url = result.ok ? loopbackUrl(result.body?.url) : null;
  try {
    if (url && tab) tab.location.replace(url);
    else tab?.close();
  } catch {
    // вкладку уже закрыли сами — ссылка «Перейти к монтажному столу» останется на экране
  }
  // Открыт без ссылки — экран после опроса скажет это сам (NO_LINK).
  return result.ok ? "" : refusalText(result);
}

async function closeDeskRequest(project) {
  const result = await postMontage(project.id, "desk/close");
  return result.ok ? "" : refusalText(result);
}

function deskButton(project, options) {
  return actionButton({
    slot: `desk:${project.id}`, projectId: project.id, targetId: `montage:${project.id}`,
    after: refreshMontage, ...options,
  });
}

function deskBox(content) {
  const box = el("div", "am-desk");
  box.dataset.hook = "am-desk";
  box.append(...content);
  return box;
}

function openDesk(project) {
  return deskBox([deskButton(project, {
    action: "desk-open", label: "Открыть монтажный стол", className: "v2-primary v2-primary-back",
    busyText: "Запускаю монтажный стол…", send: () => openDeskRequest(project),
  })]);
}

function goLink(project, url) {
  const link = el("a", "v2-primary v2-primary-back", "Перейти к монтажному столу ↗");
  link.href = url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  markControlHooks(link, `montage:${project.id}`, "desk-go");
  link.dataset.part = "am-desk-go";
  return link;
}

function deskIsOpen(project, flags) {
  const parts = [];
  if (flags.deskCloseOnly) parts.push(el("p", "am-note am-desk-left", LEFT_OPEN));
  else if (flags.deskUrl) parts.push(goLink(project, flags.deskUrl));
  else parts.push(el("p", "am-note am-desk-nolink", NO_LINK));
  parts.push(deskButton(project, {
    action: "desk-close", label: "Закрыть стол", className: "am-link-button",
    busyText: "Закрываю стол…", send: () => closeDeskRequest(project),
  }));
  return deskBox(parts);
}

function markedChat(project, action, label, request, className) {
  const button = chatButton(label, request, className);
  markControlHooks(button, `montage:${project.id}`, action);
  return button;
}

function engineMissing(project, revision, reason) {
  const box = el("div", "am-engine");
  box.dataset.hook = "am-engine-missing";
  box.append(el("p", "am-engine-title", "Монтажный стол не установлен"));
  if (reason) box.append(el("p", "am-engine-reason", reason));
  box.append(markedChat(project, "install", "Установить → чат", installMontage(project, revision)));
  return box;
}

export function renderMainActions({ project, revision, status, flags }) {
  const box = el("div", "am-main-actions");
  box.dataset.hook = "am-main-actions";
  if (flags.engine === "missing" && flags.build) {
    box.append(engineMissing(project, revision, status?.engine?.reason));
  }
  if (flags.desk === "closed") box.append(openDesk(project));
  if (flags.desk === "busy") box.append(el("p", "am-note", "Монтажный стол открывается или закрывается…"));
  if (flags.desk === "open") box.append(deskIsOpen(project, flags));
  if (flags.deskHint) box.append(el("p", "am-note", PHONE_HINT));
  if (flags.build) {
    box.append(markedChat(project, "build", assembleLabel(project), assembleFinal(project, revision),
      "v2-primary v2-primary-back"));
  }
  return box;
}
