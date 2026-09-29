// Фаза «phone», 390×844 (isMobile, hasTouch): без горизонтальной прокрутки;
// стола и «Показать в папке» нет, есть подсказка «открывается на
// компьютере»; «Скачать» и «Собрать ролик → чат» не ниже 44 px; превью не
// выше ~65 % экрана; версии листаются вбок; дорожка схемы — 44 px, касание
// блока показывает клип; подвал прилипает к низу экрана.

import { SCHEMA_WAIT, click, openProject, text, until } from "./lib.mjs";

const HINT = "Монтажный стол открывается на компьютере";

const height = (page, selector) => page.$eval(selector, (node) => node.getBoundingClientRect().height).catch(() => 0);

export const PHONE = { width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 2 };

async function footer(c, page) {
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight / 2));
  const view = await until(page, () => {
    const node = document.querySelector('[data-hook="v2-footer"]');
    if (!node) return null;
    const rect = node.getBoundingClientRect();
    return { position: getComputedStyle(node).position, bottom: Math.round(rect.bottom), inner: window.innerHeight };
  }, null, { timeout: 5000 });
  c.add("footer.sticky", Boolean(view) && ["sticky", "fixed"].includes(view.position)
    && Math.abs(view.bottom - view.inner) <= 2, JSON.stringify(view));
}

export async function phone(c, cfg, { page }) {
  await openProject(page, cfg);
  await until(page, () => document.querySelector(".am-track"), null, { timeout: SCHEMA_WAIT });
  await c.shot(page, "top");
  const scroll = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
  c.add("no_hscroll", scroll[0] <= scroll[1], `ширина страницы ${scroll[0]} при экране ${scroll[1]}`);
  const visible = (selector) => page.$eval(selector, (node) => node.getBoundingClientRect().width > 0).catch(() => false);
  const desk = await visible('[data-action="desk-open"]');
  const reveal = await visible('[data-action="reveal"]');
  const hint = (await page.evaluate(() => document.body.innerText)).includes(HINT);
  c.add("desk_hidden", !desk && !reveal && hint, `стол ${desk ? "виден" : "скрыт"}, папка ${reveal ? "видна" : "скрыта"}, подсказка ${hint ? "есть" : "нет"}`);
  const sizes = [await height(page, '[data-part="am-download"]'),
    await height(page, '[data-hook="am-main-actions"] [data-action="build"]')];
  c.add("tap_targets", sizes.every((size) => size >= 44), `«Скачать» ${sizes[0]} px, «Собрать» ${sizes[1]} px`);
  const share = await page.evaluate(() => document.querySelector('[data-part="v2-final-slot"]')
    .getBoundingClientRect().height / window.innerHeight);
  c.add("preview_height", share > 0 && share <= 0.65, `превью — ${Math.round(share * 100)} % высоты экрана`);
  const list = await page.$eval(".am-version-list", (node) => ({
    overflow: getComputedStyle(node).overflowX, scroll: node.scrollWidth, width: node.clientWidth }));
  c.add("versions_sideways", ["auto", "scroll"].includes(list.overflow) && list.scroll > list.width, JSON.stringify(list));
  const lane = await height(page, '.am-track[data-layer="video"] .am-lane');
  c.add("lane_height", lane >= 44, `дорожка ${lane} px`);
  await c.step("block_tap", async () => {
    await click(page, '.am-track[data-layer="video"] [data-part="am-block"]', { tap: true });
    const detail = await text(page, ".am-layer-detail");
    return [/^Клип: /.test(detail || ""), detail];
  });
  await footer(c, page);
  await c.shot(page, "full", { fullPage: true });
}
