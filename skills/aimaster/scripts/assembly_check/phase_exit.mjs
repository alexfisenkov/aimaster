// Фаза «exit», 1400×900: стол открывается с экрана и остаётся открытым.
// Дальше оркестратор останавливает дашборд, как агент, и проверяет, что стол
// ушёл вместе с ним и ни одного процесса прогона не осталось.

import { openDeskFromScreen, openProject } from "./lib.mjs";

export async function exit(c, cfg, { browser, page }) {
  await openProject(page, cfg);
  await page.waitForSelector('[data-hook="am-desk"] [data-action="desk-open"]', { timeout: 30000 });
  const href = (await openDeskFromScreen(browser, page))?.href || "";
  c.add("desk.open", href.startsWith("http://127.0.0.1:"), href || "стол не открылся за 90 с");
  c.data.deskUrl = href;
  await c.shot(page, "desk-open");
}
