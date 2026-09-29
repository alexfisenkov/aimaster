// Фаза «desktop», 1400×900, v1 собрана агентом, стол закрыт: превью 9:16 и
// пилюли, карточка «Ролик v1» («Скачать», «Показать в папке», короткий путь,
// абсолютных путей на странице нет), скачивание и Range (fetch узла),
// листалка версий, схема (6 дорожек, 2 блока видео ≈ 2:1, нажатие — «Клип: …»),
// «Показать в папке»: с --reveal — настоящее нажатие, без — кнопка есть,
// а запрос без CSRF отклонён (403).

import { SCHEMA_WAIT, absoluteIn, click, openProject, text, until } from "./lib.mjs";

function filename(disposition) {
  const star = /filename\*=UTF-8''([^;]+)/i.exec(disposition || "");
  return star ? decodeURIComponent(star[1]) : null;
}

async function download(c, cfg, href) {
  const url = new URL(href, cfg.baseUrl).href;
  await c.step("download.full", async () => {
    const response = await fetch(url);
    const body = Buffer.from(await response.arrayBuffer());
    const name = filename(response.headers.get("content-disposition"));
    const want = `${cfg.title}-v001.mp4`;
    return [response.status === 200 && name === want && body.length > 0,
      `HTTP ${response.status}, имя «${name}» (ждали «${want}»), ${body.length} байт`];
  });
  await c.step("download.range", async () => {
    const response = await fetch(url, { headers: { Range: "bytes=0-99" } });
    const body = Buffer.from(await response.arrayBuffer());
    return [response.status === 206 && body.length === 100, `HTTP ${response.status}, ${body.length} байт`];
  });
}

async function reveal(c, cfg, page) {
  const button = '[data-hook="am-file"] [data-action="reveal"]';
  const status = await (await fetch(`${cfg.baseUrl}/api/projects/${encodeURIComponent(cfg.projectId)}/montage`)).json();
  const width = await page.$eval(button, (node) => node.getBoundingClientRect().width).catch(() => 0);
  // Нечем открыть папку (Linux без xdg-open) — сервер говорит reveal: false, кнопки быть не должно.
  const can = status.reveal === true;
  c.add("reveal.button", can ? width > 0 : width === 0, can
    ? (width > 0 ? "«Показать в папке» видна на 1400 px" : "кнопки «Показать в папке» нет")
    : `нечем открыть папку (reveal: false) — кнопки ${width ? "есть, а быть не должно" : "нет, как и должно"}`);
  if (!cfg.reveal) { // запрос — узлом, не страницей: отказ 403 в консоли страницы был бы шумом
    await c.step("reveal.csrf", async () => {
      const url = `${cfg.baseUrl}/api/projects/${encodeURIComponent(cfg.projectId)}/montage/reveal`;
      const response = await fetch(url, { method: "POST", body: "{}",
        headers: { "Content-Type": "application/json", Origin: cfg.baseUrl } });
      const code = (await response.json().catch(() => ({})))?.error?.code;
      return [response.status === 403 && code === "forbidden", `POST …/montage/reveal без CSRF → HTTP ${response.status}, ${code}`];
    });
    return;
  }
  await c.step("reveal.click", async () => {
    const answer = page.waitForResponse((r) => r.url().endsWith("/montage/reveal"), { timeout: 20000 });
    await click(page, button);
    const response = await answer;
    await until(page, (sel) => !document.querySelector(sel)?.disabled, button);
    const note = await page.$eval(button, (node) => node.parentElement.textContent.replace("Показать в папке", "").trim());
    return [response.status() === 200 && !note, `HTTP ${response.status()}${note ? `, отказ: ${note}` : ""}`];
  });
}

async function schema(c, page, state) {
  await c.step("schema.lanes", async () => {
    const lanes = await page.$$eval('[data-hook="am-layers"] .am-track', (rows) => rows.map((row) => row.dataset.layer));
    const widths = await page.$$eval('.am-track[data-layer="video"] [data-part="am-block"]',
      (blocks) => blocks.map((block) => block.getBoundingClientRect().width));
    const ratio = widths.length === 2 ? widths[0] / widths[1] : 0;
    return [lanes.length === 6 && widths.length === 2 && ratio > 1.8 && ratio < 2.2,
      `дорожки: ${lanes.join(", ")}; блоки видео: ${widths.map(Math.round).join(" : ")}`];
  });
  await c.step("schema.detail", async () => {
    await click(page, '.am-track[data-layer="video"] [data-part="am-block"]');
    const detail = await text(page, ".am-layer-detail");
    return [/^Клип: /.test(detail || ""), detail];
  });
  state.schemaEnd = await text(page, ".am-ruler span:last-child");
}

export async function desktop(c, cfg, { page, state }) {
  await openProject(page, cfg);
  await until(page, () => document.querySelector('[data-hook="am-layers"] .am-track'), null, { timeout: SCHEMA_WAIT });
  await c.shot(page, "top");
  await c.step("preview", async () => {
    const view = await page.$eval('[data-part="v2-final-slot"]', (slot) => {
      const rect = slot.getBoundingClientRect();
      return { orientation: slot.dataset.orientation, ratio: rect.height / rect.width,
        status: slot.querySelector(".v2-final-status")?.textContent,
        duration: slot.querySelector(".v2-final-duration")?.textContent };
    });
    return [view.orientation === "portrait" && Math.abs(view.ratio - 16 / 9) <= 0.05
      && view.status === "текущая v1" && view.duration === "00:03", JSON.stringify(view)];
  });
  await c.step("file.card", async () => {
    const title = await text(page, '[data-hook="am-file"] .v2-card-title');
    const download = await text(page, '[data-part="am-download"]');
    return [title === "Ролик v1" && download === "Скачать", `«${title}», «${download}»`];
  });
  await c.step("file.path", async () => {
    const shown = await text(page, '[data-part="am-file-path"]');
    const page_ = await page.evaluate(() => `${document.body.innerText}\n${document.documentElement.outerHTML}`);
    const hits = absoluteIn(page_, [cfg.workspace]);
    return [/^рабочая папка\/media\/.+\/v001\.mp4$/.test(shown || "") && !hits.length,
      `путь «${shown}»${hits.length ? `; на странице: ${hits.join(", ")}` : ""}`];
  });
  await download(c, cfg, await page.$eval('[data-part="am-download"]', (link) => link.getAttribute("href")));
  await c.step("versions", async () => {
    const rows = await page.$$eval('[data-hook="am-version"]', (items) => items.map((item) => ({
      label: item.querySelector(".am-version-label")?.textContent, current: item.dataset.current,
      badge: item.querySelector(".am-version-top")?.textContent })));
    return [rows.length === 1 && rows[0].label === "v1" && rows[0].current === "true"
      && rows[0].badge.includes("текущая"), JSON.stringify(rows)];
  });
  await schema(c, page, state);
  await reveal(c, cfg, page);
}
