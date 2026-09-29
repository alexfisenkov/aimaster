// Фаза «after», 1400×900: агент собрал v2 от имени человека (montage render
// --by owner), стол ещё открыт. Экран: «текущая v2», карточка v2 от «Вы»,
// плашки несобранных правок нет; «Сделать текущей» у v1 → тост «Текущая
// версия — v1», v1 текущая, последняя запись истории — от «you» (снимок
// проекта); «Закрыть стол» → снова «Открыть монтажный стол» (порт стола
// проверяет оркестратор).

import { click, openProject, until } from "./lib.mjs";

const versions = (page) => page.$$eval('[data-hook="am-version"]', (items) => items.map((item) => ({
  label: item.querySelector(".am-version-label")?.textContent,
  current: item.dataset.current === "true",
  meta: item.querySelector(".am-version-meta")?.textContent || "",
})));

async function v2(c, page) {
  const status = await until(page, () => {
    const now = document.querySelector('[data-part="v2-final-slot"] .v2-final-status')?.textContent;
    return now === "текущая v2" ? now : "";
  }, null, { timeout: 20000 });
  c.add("v2.current", Boolean(status), status || "нет «текущая v2» за 20 с");
  const rows = await versions(page);
  c.add("v2.card", rows.length === 2 && rows[0].label === "v2" && rows[0].current && rows[0].meta.startsWith("Вы"),
    JSON.stringify(rows));
  const gone = await until(page, () => !document.querySelector('.am-notice[data-key="unrendered"]'), null,
    { timeout: 15000 });
  c.add("v2.banner_gone", Boolean(gone), gone ? "плашки несобранных правок нет" : "плашка осталась");
  await c.shot(page, "v2");
}

async function restoreV1(c, cfg, page) {
  await click(page, '[data-hook="am-version"][data-current="false"] [data-action="restore"]');
  const toast = await until(page, () => {
    const node = document.querySelector('[data-hook="v2-toast"]');
    return node && !node.hidden ? node.textContent.trim() : "";
  }, null, { timeout: 15000, every: 100 });
  c.add("restore.toast", toast === "Текущая версия — v1", toast || "тоста нет");
  const current = await until(page, () => {
    const row = document.querySelector('[data-hook="am-version"][data-current="true"] .am-version-label');
    return row?.textContent === "v1" ? "v1" : "";
  }, null, { timeout: 15000 });
  c.add("restore.current", current === "v1", current ? "v1 текущая" : "v1 не стала текущей");
  await c.step("restore.history", async () => {
    const last = await page.evaluate(async (id) => {
      const snapshot = await (await fetch(`/api/projects/${encodeURIComponent(id)}/snapshot`)).json();
      return snapshot.active_project.history.at(-1);
    }, cfg.projectId);
    return [last?.kind === "montage-restored" && last?.actor === "you",
      `последняя запись истории: ${last?.kind} от ${last?.actor}`];
  });
  await c.shot(page, "restored");
}

export async function after(c, cfg, { page }) {
  await openProject(page, cfg);
  await v2(c, page);
  await restoreV1(c, cfg, page);
  await click(page, '[data-hook="am-desk"] [data-action="desk-close"]');
  const open = await until(page, () => document.querySelector('[data-hook="am-desk"] [data-action="desk-open"]')
    ?.textContent.trim(), null, { timeout: 30000 });
  c.add("desk.closed", open === "Открыть монтажный стол", open || "кнопки «Открыть монтажный стол» нет");
}
