// Фаза «noengine», 1400×900: дашборд перезапущен без движка (пустая папка
// движка — как у человека до установки). «Монтажный стол не установлен»,
// причина по-русски; «Установить → чат» — запрос без абсолютных путей,
// со ссылкой на engine.install_argv; вместо схемы — подсказка; «Скачать»
// собранного ролика — на месте.

import { absoluteIn, openProject, promptOf, text, until } from "./lib.mjs";

export async function noengine(c, cfg, { page }) {
  await openProject(page, cfg);
  const title = await until(page, () => document.querySelector('[data-hook="am-engine-missing"] .am-engine-title')
    ?.textContent.trim(), null, { timeout: 30000 });
  const reason = await text(page, '[data-hook="am-engine-missing"] .am-engine-reason');
  c.add("missing.title", title === "Монтажный стол не установлен", title || "плашки нет");
  c.add("missing.reason", /[а-яё]/i.test(reason || "") && !absoluteIn(reason || "", [cfg.workspace]).length,
    reason || "причины нет");
  await c.step("missing.install_prompt", async () => {
    const prompt = await promptOf(page, '[data-hook="am-engine-missing"] [data-action="install"]');
    const hits = absoluteIn(prompt, [cfg.workspace, cfg.enginePrefix]);
    return [prompt.includes("install_argv") && !hits.length,
      hits.length ? `пути в запросе: ${hits.join(", ")}` : "install_argv есть, путей нет"];
  });
  const hint = await text(page, '[data-hook="am-layers"] .v2-section-hint');
  const tracks = await page.$$eval(".am-track", (rows) => rows.length);
  c.add("missing.schema", tracks === 0 && hint === "Схема появится, когда будет установлен монтажный стол.",
    `${hint}; дорожек: ${tracks}`);
  const download = await text(page, '[data-part="am-download"]');
  c.add("missing.download", download === "Скачать", download || "«Скачать» нет");
  c.add("missing.no_desk", !(await page.$('[data-action="desk-open"]')), "кнопки стола нет");
  await c.shot(page, "no-engine");
}
