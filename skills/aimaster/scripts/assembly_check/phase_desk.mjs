// Фаза «desk» (после «desktop», та же страница): «Открыть монтажный стол» →
// «Перейти к монтажному столу ↗» и «Закрыть стол», ссылка — 127.0.0.1 с
// rel="noopener noreferrer"; ссылка — в НОВОЙ странице: Studio на
// #project/current, аналитика выключена до загрузки, ни одного запроса мимо
// 127.0.0.1; клип 2 сдвинут мышью на 0,5 с (studio.mjs) → current/index.html
// изменился; дашборд за 15 с показывает «Есть несобранные правки», конец
// схемы сдвинулся; «Собрать ролик → чат» — запрос с montage diff, montage
// render --by owner, бесплатно, без «платное действие».

import { openDeskFromScreen, promptOf, text, until } from "./lib.mjs";
import { SHIFT, dragClip, external, openStudio } from "./studio.mjs";

/** «0:03.5» (как fmtTime схемы) → 3.5. */
const seconds = (clock) => {
  const [minutes, rest] = String(clock).split(":");
  return Number(minutes) * 60 + Number(rest);
};

async function openDesk(c, browser, page) {
  const link = await openDeskFromScreen(browser, page);
  if (!link) throw new Error("стол не открылся за 90 с: нет ссылки «Перейти к монтажному столу»");
  const closeText = await text(page, '[data-hook="am-desk"] [data-action="desk-close"]');
  const url = new URL(link.href);
  const rel = new Set(link.rel.split(/\s+/));
  c.add("open", link.text === "Перейти к монтажному столу ↗" && closeText === "Закрыть стол",
    `«${link.text}», «${closeText}»`);
  c.add("link", url.protocol === "http:" && url.hostname === "127.0.0.1" && rel.has("noopener")
    && rel.has("noreferrer") && link.target === "_blank", `${url.origin}, rel="${link.rel}"`);
  c.data.deskUrl = link.href;
  return link.href;
}

async function waitBanner(c, page, before) {
  await page.bringToFront(); // опрос экрана идёт, только пока вкладка видна
  const seen = await until(page, () => {
    const notice = document.querySelector('.am-notice[data-key="unrendered"]');
    return notice ? notice.textContent.trim() : "";
  }, null, { timeout: 15000 });
  c.add("dashboard.unrendered", (seen || "").startsWith("Есть несобранные правки"), seen || "плашки нет за 15 с");
  const end = await until(page, (was) => {
    const now = document.querySelector(".am-ruler span:last-child")?.textContent;
    return now && now !== was ? now : "";
  }, before, { timeout: 15000 });
  const moved = end ? seconds(end) - seconds(before) : 0; // клип 2 сдвинут на 0,5 с — ролик на столько же длиннее
  c.add("dashboard.schema_end", Math.abs(moved - SHIFT) <= 0.15,
    `конец схемы: ${before} → ${end || "не изменился"} (ждали +${SHIFT} с ± 0,15)`);
  await c.shot(page, "unrendered");
}

async function buildPrompt(c, page) {
  await c.step("build.prompt", async () => {
    const prompt = await promptOf(page, '[data-hook="am-main-actions"] [data-action="build"]');
    const need = ["montage diff", "montage render", "--by owner", "бесплатн"];
    const missing = need.filter((word) => !prompt.includes(word));
    const paid = prompt.includes("платное действие");
    return [!missing.length && !paid,
      missing.length ? `нет: ${missing.join(", ")}` : paid ? "есть «платное действие»" : "всё на месте"];
  });
}

export async function desk(c, cfg, { browser, page, state }) {
  const href = await openDesk(c, browser, page);
  await c.shot(page, "desk-open");
  const { studio, requests } = await openStudio(c, cfg, browser, href);
  await dragClip(c, cfg, studio);
  await c.shot(studio, "studio-after-drag");
  const outside = external(requests);
  c.add("studio.local_only", requests.length > 0 && outside.length === 0, outside.length
    ? `мимо 127.0.0.1: ${outside.slice(0, 5).join(", ")}` : `запросов Studio: ${requests.length}, все на 127.0.0.1`);
  await studio.close();
  await waitBanner(c, page, state.schemaEnd || "0:03.0");
  await buildPrompt(c, page);
}
