#!/usr/bin/env node
// Браузерные фазы проверки экрана «Сборка». Запускает оркестратор
// `check_assembly_screen.py` — узлом движка, с настройками в JSON-файле:
//
//   node check_assembly_screen.mjs <настройки.json>
//
// Настройки: phases (по порядку, в одном браузере: desktop, desk, after,
// noengine, phone, exit), baseUrl, projectId, title, workspace, indexPath,
// enginePrefix, shots, profile, pidFile, modules (node_modules движка —
// оттуда puppeteer-core), browser (chrome-headless-shell из записи движка),
// reveal. Ответ — одна строка JSON в stdout: {checks: [{id, ok, detail}],
// shots: [...], data: {...}}. Упавшая фаза — проверка «<фаза>.crash»,
// следующие фазы идут дальше. Браузер закрывается всегда.

import fs from "node:fs";
import { Checks, launch } from "./assembly_check/lib.mjs";
import { after } from "./assembly_check/phase_after.mjs";
import { desk } from "./assembly_check/phase_desk.mjs";
import { desktop } from "./assembly_check/phase_desktop.mjs";
import { exit } from "./assembly_check/phase_exit.mjs";
import { noengine } from "./assembly_check/phase_noengine.mjs";
import { PHONE, phone } from "./assembly_check/phase_phone.mjs";

const DESKTOP = { width: 1400, height: 900 };
const PHASES = { desktop, desk, after, noengine, phone, exit };

/** Страница дашборда под нужную ширину; ошибки её консоли — в текущую фазу. */
async function pageFor(session, viewport) {
  if (session.page && session.viewport === viewport) return session.page;
  await session.page?.close().catch(() => null);
  const page = await session.browser.newPage();
  await page.setViewport(viewport);
  page.on("console", (message) => {
    if (message.type() === "error") session.current?.errors.push(`дашборд: ${message.text()}`);
  });
  page.on("pageerror", (error) => session.current?.errors.push(`дашборд: ${error?.message || error}`));
  session.page = page;
  session.viewport = viewport;
  return page;
}

async function main() {
  const cfg = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
  const result = { checks: [], shots: [], data: {} };
  const browser = await launch(cfg, DESKTOP);
  const session = { browser, page: null, viewport: null, state: {} };
  try {
    for (const name of cfg.phases) {
      const c = new Checks(cfg, name);
      session.current = c;
      try {
        await pageFor(session, name === "phone" ? PHONE : DESKTOP);
        if (!PHASES[name]) throw new Error(`нет такой фазы: ${name}`);
        await PHASES[name](c, cfg, session);
      } catch (error) {
        c.add("crash", false, error?.stack || String(error));
        if (session.page) await c.shot(session.page, "crash");
      }
      c.add("console", c.errors.length === 0, c.errors.length ? c.errors.slice(0, 5).join(" | ")
        : "ошибок в консоли нет");
      result.checks.push(...c.checks);
      result.shots.push(...c.shots);
      result.data[name] = c.data;
    }
  } finally {
    await browser.close().catch(() => null);
  }
  process.stdout.write(`${JSON.stringify(result)}\n`);
}

main().catch((error) => {
  process.stdout.write(`${JSON.stringify({ checks: [{ id: "browser.crash", ok: false,
    detail: error?.stack || String(error) }], shots: [], data: {} })}\n`);
  process.exitCode = 1;
});
