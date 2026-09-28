// Плашки экрана «Сборка»: несобранные правки, ошибки монтажа (текст сервера —
// по-русски, без путей), записки монтажного стола. Список —
// montage-model.notices; у плашки со сборкой или обновлением — кнопка в чат.
// После принятия ролика (`actions: false`) кнопок нет: монтаж уже не меняют.

import { chatButton, el } from "./dom.js";
import { assembleFinal, assembleLabel, updateMontageClips } from "./screen-prompts.js";

export function renderNotices(list, { project, revision, actions = true }) {
  const box = el("div", "am-notices");
  box.dataset.hook = "am-notices";
  box.setAttribute("role", "status");
  for (const notice of list) {
    const row = el("div", "am-notice");
    row.dataset.tone = notice.tone;
    row.dataset.key = notice.key;
    row.append(el("p", "am-notice-text", notice.text));
    if (actions && notice.action === "build") {
      row.append(chatButton(assembleLabel(project), assembleFinal(project, revision)));
    }
    if (actions && notice.action === "refresh") {
      row.append(chatButton("Обновить клипы → чат", updateMontageClips(project, revision)));
    }
    box.append(row);
  }
  return box;
}
