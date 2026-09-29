// Монтажный стол глазами человека: HyperFrames Studio 0.8.75 в новой странице
// по ссылке дашборда (страница-переходник выключает аналитику и уводит на
// #project/current) и правка мышью. Клип на дорожке Studio — кнопка с
// aria-label «V 2, 2.0 to 3.0 seconds». Дорожку увеличиваем кнопкой
// «Zoom in», пока клип 2 целиком виден с запасом на сдвиг; потом — нажать
// в середине клипа, вести мышь вправо шагами на 0,5 с (ширина клипа 1 —
// 2 с), отпустить. Studio пишет правку в current/index.html сама.

import fs from "node:fs";
import { sleep, until } from "./lib.mjs";

const CLIP = 'button[aria-label^="V 2,"]';
const LOOPBACK = /^https?:\/\/127\.0\.0\.1(:\d+)?\//;
const LOCAL = /^(data|blob|about|chrome|devtools):/;

export async function openStudio(c, cfg, browser, href) {
  const studio = await browser.newPage();
  c.watch(studio, "Studio");
  const requests = [];
  studio.on("request", (request) => requests.push(request.url()));
  await studio.goto(href, { waitUntil: "load" });
  await studio.waitForSelector(CLIP, { timeout: 60000 });
  const view = await studio.evaluate(() => ({
    hash: window.location.hash,
    telemetry: window.localStorage.getItem("hyperframes-studio:telemetryDisabled"),
  }));
  c.add("studio.opened", view.hash.startsWith("#project/current") && view.telemetry === "1",
    `адрес ${view.hash}, telemetryDisabled=${view.telemetry}`);
  await c.shot(studio, "studio-open");
  return { studio, requests };
}

/** Запросы Studio мимо 127.0.0.1 (data:, blob:, about: — не сеть). */
export function external(requests) {
  return requests.filter((url) => !LOOPBACK.test(url) && !LOCAL.test(url));
}

async function zoomToClip(studio) {
  const fits = () => studio.evaluate((sel) => {
    const clip = document.querySelector(sel);
    const view = document.querySelector('[aria-label="Timeline track view"]')?.getBoundingClientRect();
    if (!clip || !view) return 0;
    const rect = clip.getBoundingClientRect();
    return rect.right + rect.width < view.right - 20 ? rect.width : 0;
  }, CLIP);
  for (let step = 0; step < 8; step += 1) {
    const width = await fits();
    if (!width || width > 250) break;
    await studio.click('button[aria-label="Zoom in"]');
    await sleep(300);
  }
  if (!(await fits())) {
    await studio.click('button[aria-label="Zoom out"]');
    await sleep(300);
  }
  return fits();
}

export async function dragClip(c, cfg, studio) {
  const before = fs.readFileSync(cfg.indexPath, "utf8");
  const width = await zoomToClip(studio);
  const box = await (await studio.$(CLIP))?.boundingBox();
  if (!width || !box) {
    c.add("studio.drag", false, "клип 2 не удалось показать целиком на дорожке");
    return;
  }
  const label = await studio.$eval(CLIP, (node) => node.getAttribute("aria-label"));
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  const shift = box.width * 0.5; // клип 2 длится 1 с — полширины = 0,5 с
  await studio.mouse.move(x, y);
  await studio.mouse.down();
  for (let i = 1; i <= 10; i += 1) {
    await studio.mouse.move(x + (shift * i) / 10, y);
    await sleep(40);
  }
  await studio.mouse.up();
  const moved = await until(studio, (sel) => document.querySelector(sel)?.getAttribute("aria-label")
    .startsWith("V 2, 2.5 to") && document.querySelector(sel).getAttribute("aria-label"), CLIP, { timeout: 10000 });
  let changed = false;
  for (let i = 0; i < 40 && !changed; i += 1) {
    changed = fs.readFileSync(cfg.indexPath, "utf8") !== before;
    if (!changed) await sleep(250);
  }
  const start = /id="v-2"[^>]*data-start="([\d.]+)"/.exec(fs.readFileSync(cfg.indexPath, "utf8"))?.[1];
  c.add("studio.drag", Boolean(moved) && changed && start === "2.5",
    `«${label}» → «${moved || "не сдвинулся"}»; index.html ${changed ? "изменён" : "не изменён"}, data-start=${start}`);
}
