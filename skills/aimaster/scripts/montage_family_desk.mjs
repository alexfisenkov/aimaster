// Synthetic local-only desk acceptance; reuse the repository's browser harness.
import fs from "node:fs";
import { Checks, launch, sleep, until } from "./assembly_check/lib.mjs";
import { dragClip, external, openStudio } from "./assembly_check/studio.mjs";

const cfg = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const checks = new Checks(cfg, "family-desk");
checks.shot = async () => {}; // This check needs persisted bytes, not screenshots.
const browser = await launch(cfg, { width: 1400, height: 900 });

async function dragOverlay(studio) {
  const selector = 'button[aria-label^="O 1,"]';
  await studio.waitForSelector(selector, { timeout: 15000 });
  const box = await (await studio.$(selector)).boundingBox();
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  const shift = box.width * .5 / 1.5;
  await studio.mouse.move(x, y);
  await studio.mouse.down();
  for (let i = 1; i <= 10; i += 1) {
    await studio.mouse.move(x + shift * i / 10, y);
    await sleep(40);
  }
  await studio.mouse.up();
  const moved = await until(studio, (sel) => document.querySelector(sel)?.getAttribute("aria-label")
    .startsWith("O 1, 0.5 to"), selector);
  let saved = false;
  for (let i = 0; i < 40 && !saved; i += 1) {
    saved = /id="o-1"[^>]*data-start="0.5"/.test(fs.readFileSync(cfg.indexPath, "utf8"));
    if (!saved) await sleep(250);
  }
  checks.add("overlay-drag-save", moved && saved, "o-1 moved from 0 to 0.5 seconds and saved");
}

try {
  const { studio, requests } = await openStudio(checks, cfg, browser, cfg.href);
  if (cfg.overlay) await dragOverlay(studio);
  else await dragClip(checks, cfg, studio);
  checks.add("local-only", external(requests).length === 0, "Studio requests stay on loopback");
  await studio.close();
  const reopened = await openStudio(checks, cfg, browser, cfg.href);
  const selector = cfg.overlay ? 'button[aria-label^="O 1,"]' : 'button[aria-label^="V 2,"]';
  const label = await reopened.studio.$eval(selector,
    (element) => element.getAttribute("aria-label"));
  checks.add("saved-after-reopen", label.startsWith(cfg.overlay ? "O 1, 0.5 to" : "V 2, 2.5 to"), label);
  process.stdout.write(JSON.stringify(checks.checks) + "\n");
  if (checks.checks.some((check) => check.required !== false && !check.ok)) process.exitCode = 1;
} finally {
  await browser.close();
}
