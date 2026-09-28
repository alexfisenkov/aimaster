// Плашки экрана «Сборка»: несобранные правки, ошибки монтажа (текст сервера —
// по-русски, без путей), записки монтажного стола. Список —
// montage-model.notices. Плашка про сборку («Есть несобранные правки»,
// «файла нет — соберите заново») только говорит, что случилось: кнопка
// «Собрать ролик → чат» на экране одна — главная, рядом с файлом ролика.
// У плашки про устаревшие клипы своя кнопка — «Обновить клипы → чат».
// После принятия ролика (`actions: false`) кнопок нет: монтаж уже не меняют.

import { markControlHooks } from "../card-forms.js";
import { chatButton, el } from "./dom.js";
import { updateMontageClips } from "./screen-prompts.js";

function refreshButton(project, revision, key) {
  const button = chatButton("Обновить клипы → чат", updateMontageClips(project, revision));
  markControlHooks(button, `montage:${project.id}`, `refresh:${key}`);
  return button;
}

export function renderNotices(list, { project, revision, actions = true }) {
  const box = el("div", "am-notices");
  box.dataset.hook = "am-notices";
  box.setAttribute("role", "status");
  for (const notice of list) {
    const row = el("div", "am-notice");
    row.dataset.tone = notice.tone;
    row.dataset.key = notice.key;
    row.append(el("p", "am-notice-text", notice.text));
    if (actions && notice.action === "refresh") row.append(refreshButton(project, revision, notice.key));
    box.append(row);
  }
  return box;
}
