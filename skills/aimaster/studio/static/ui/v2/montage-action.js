// Кнопка прямого действия экрана «Сборка» («Открыть монтажный стол»,
// «Закрыть стол», «Показать в папке», «Сделать текущей»). Экран
// перерисовывается целиком по каждому ответу опроса, а запрос идёт секунды:
// что летит и чем кончилось, помнит `work` по месту кнопки (`slot`), иначе
// перерисовка вернула бы кнопку раньше ответа и потеряла бы текст отказа.
// Текст отказа живёт до следующего нажатия. У одного места одна запись:
// завершённая запись другого действия на том же месте (стол открыли —
// теперь там «Закрыть стол») забывается, чтобы старый отказ не всплыл.

import { buildStatusLine, markControlHooks, noteCardFocusPending } from "../card-forms.js";
import { el } from "./dom.js";
import { repaintMontage } from "./montage-feed.js";

const work = new Map(); // slot → {action, busy, note}

function stateOf(slot, action) {
  const item = work.get(slot);
  if (item && item.action !== action && !item.busy) work.delete(slot);
  return item?.action === action ? item : null;
}

/**
 * @param {object} options
 * @param {string} options.slot место кнопки: проект, проект:версия
 * @param {string} options.projectId чей экран перерисовать, если его перерисовали, пока ждали
 * @param {string} options.targetId `data-target-id` — фокус переживает перерисовку
 * @param {string} options.action `data-action`
 * @param {string} options.label надпись; `busyLabel` — надпись, пока летит (по умолчанию та же)
 * @param {string} options.className
 * @param {string} [options.busyText] строка под кнопкой, пока летит
 * @param {() => Promise<string>} options.send запрос → текст отказа или "" (удача)
 * @param {() => Promise<void>|void} [options.after] после ответа — до проверки, на месте ли кнопка
 */
export function actionButton({
  slot, projectId, targetId, action, label, busyLabel = label, className, busyText = "", send, after,
}) {
  const wrap = el("span", "am-inline");
  const state = stateOf(slot, action);
  const button = el("button", className, state?.busy ? busyLabel : label);
  button.type = "button";
  button.disabled = Boolean(state?.busy);
  markControlHooks(button, targetId, action);
  const status = buildStatusLine();
  status.textContent = state?.busy ? busyText : state?.note || "";
  button.addEventListener("click", async () => {
    noteCardFocusPending(targetId, action);
    work.set(slot, { action, busy: true, note: "" });
    button.disabled = true;
    button.textContent = busyLabel;
    status.textContent = busyText;
    const note = await send();
    if (note) work.set(slot, { action, busy: false, note });
    else work.delete(slot);
    button.disabled = false;
    button.textContent = label;
    status.textContent = note;
    await after?.();
    if (!wrap.isConnected) repaintMontage(projectId); // экран перерисовали, пока ждали
  });
  wrap.append(button, status);
  return wrap;
}
