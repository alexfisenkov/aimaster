// Главные кнопки экрана «Сборка»: «Открыть монтажный стол» и «Собрать
// ролик → чат»; нет движка — «Монтажный стол не установлен» и «Установить →
// чат». Стол — HyperFrames Studio в новой вкладке, через страницу-переходник
// на её же адресе (выключает аналитику Studio, studio/montage/desk_opener.py).
// Вкладка открывается сразу по нажатию, пустой: откройся она после ответа
// сервера, браузер счёл бы её всплывающим окном. Заблокирована — после ответа
// появится ссылка «Перейти к монтажному столу». На телефоне и в Telegram
// стола нет (flags.desk === "hidden") — вместо него подсказка.
//
// Экран перерисовывается целиком по каждому ответу опроса, а стол
// открывается секунды: что летит и чем кончилось, помнит `work`, иначе
// перерисовка вернула бы кнопку раньше ответа и потеряла бы текст отказа.

import { buildStatusLine, markControlHooks } from "../card-forms.js";
import { chatButton, el } from "./dom.js";
import { postMontage, refusalText } from "./montage-api.js";
import { refreshMontage, repaintMontage } from "./montage-feed.js";
import { assembleFinal, assembleLabel, installMontage } from "./screen-prompts.js";

const PHONE_HINT = "Монтажный стол открывается на компьютере. Здесь можно смотреть версии "
  + "и просить правки словами в чате.";
const NO_LINK = "Стол открыт, но ссылки на него нет — закройте стол и откройте заново.";

const work = new Map(); // проект → {action, busy, note}

/** Состояние кнопки `action`; чужое завершённое (стол с тех пор открыли или
 * закрыли) — забыть, чтобы старый отказ не всплыл у другой кнопки. */
function stateOf(projectId, action) {
  const item = work.get(projectId);
  if (item && item.action !== action && !item.busy) work.delete(projectId);
  return item?.action === action ? item : null;
}

/** Кнопка стола: `send()` → текст отказа или "" (удача). */
function deskButton(project, { action, label, className, busyText, send }) {
  const wrap = el("span", "am-inline");
  const state = stateOf(project.id, action);
  const button = el("button", className, label);
  button.type = "button";
  button.disabled = Boolean(state?.busy);
  markControlHooks(button, `montage:${project.id}`, action);
  const status = buildStatusLine();
  status.textContent = state?.busy ? busyText : state?.note || "";
  button.addEventListener("click", async () => {
    work.set(project.id, { action, busy: true, note: "" });
    button.disabled = true;
    status.textContent = busyText;
    const note = await send();
    if (note) work.set(project.id, { action, busy: false, note });
    else work.delete(project.id);
    button.disabled = false;
    status.textContent = note;
    await refreshMontage();
    if (!wrap.isConnected) repaintMontage(project.id); // экран перерисовали, пока ждали
  });
  wrap.append(button, status);
  return wrap;
}

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
  const url = result.ok && typeof result.body?.url === "string" ? result.body.url : null;
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

function deskIsOpen(project, flags) {
  const parts = [];
  if (flags.deskUrl) {
    const link = el("a", "v2-primary v2-primary-back", "Перейти к монтажному столу ↗");
    link.href = flags.deskUrl;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.dataset.hook = "am-desk-go";
    parts.push(link);
  } else {
    parts.push(el("p", "am-note am-desk-nolink", NO_LINK));
  }
  parts.push(deskButton(project, {
    action: "desk-close", label: "Закрыть стол", className: "am-link-button",
    busyText: "Закрываю стол…", send: () => closeDeskRequest(project),
  }));
  return deskBox(parts);
}

function engineMissing(project, revision, reason) {
  const box = el("div", "am-engine");
  box.dataset.hook = "am-engine-missing";
  box.append(el("p", "am-engine-title", "Монтажный стол не установлен"));
  if (reason) box.append(el("p", "am-engine-reason", reason));
  box.append(chatButton("Установить → чат", installMontage(project, revision)));
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
    box.append(chatButton(assembleLabel(project), assembleFinal(project, revision), "v2-primary v2-primary-back"));
  }
  return box;
}
