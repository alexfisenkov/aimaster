#!/usr/bin/env node
// Браузерные фазы проверки экрана «Сборка». Запускает оркестратор
// `check_assembly_screen.py` — узлом движка, с настройками в JSON-файле:
//
//   node check_assembly_screen.mjs <настройки.json>
//
// Настройки: phases (по порядку, в одном браузере: desktop, desk, after,
// noengine, phone, exit), phaseBudgetMs (срок одной фазы), baseUrl,
// projectId, title, workspace, indexPath, enginePrefix, shots, profile,
// pidFile, modules (node_modules движка — оттуда puppeteer-core), browser
// (chrome-headless-shell из записи движка), reveal. Ответ — строка JSON в
// stdout на каждую законченную фазу: {phase, checks: [{id, ok, detail,
// required?}], shots, data}. Упавшая фаза — проверка «<фаза>.crash», дальше
// идут следующие; не уложилась в срок — «<фаза>.timeout», и узел выходит
// (фаза держит страницу — следующим её не отдать). Браузер закрывается всегда:
// не закрылся за 10 с — процесс браузера останавливается, узел всё равно выходит.

import fs from "node:fs";
import { Checks, launch, sleep } from "./assembly_check/lib.mjs";
import { after } from "./assembly_check/phase_after.mjs";
import { desk } from "./assembly_check/phase_desk.mjs";
import { desktop } from "./assembly_check/phase_desktop.mjs";
import { exit } from "./assembly_check/phase_exit.mjs";
import { noengine } from "./assembly_check/phase_noengine.mjs";
import { PHONE, phone } from "./assembly_check/phase_phone.mjs";

const DESKTOP = { width: 1400, height: 900 };
const CLOSE_WAIT = 10000;
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

function emit(name, c) {
  process.stdout.write(`${JSON.stringify({ phase: name, checks: c.checks, shots: c.shots, data: c.data })}\n`);
}

/** Фаза в пределах срока: "done" или "timeout". */
async function within(ms, work) {
  let timer;
  const late = new Promise((resolve) => { timer = setTimeout(() => resolve("timeout"), ms); });
  try {
    return await Promise.race([work.then(() => "done"), late]);
  } finally {
    clearTimeout(timer);
  }
}

async function runPhase(name, cfg, session) {
  const c = new Checks(cfg, name);
  session.current = c;
  let outcome = "done";
  try {
    await pageFor(session, name === "phone" ? PHONE : DESKTOP);
    if (!PHASES[name]) throw new Error(`нет такой фазы: ${name}`);
    outcome = await within(cfg.phaseBudgetMs || 150000, PHASES[name](c, cfg, session));
    if (outcome === "timeout") c.add("timeout", false, `фаза не уложилась в ${(cfg.phaseBudgetMs || 150000) / 1000} с`);
  } catch (error) {
    c.add("crash", false, error?.stack || String(error));
    if (session.page) await c.shot(session.page, "crash");
  }
  c.add("console", c.errors.length === 0, c.errors.length ? c.errors.slice(0, 5).join(" | ")
    : "ошибок в консоли нет");
  emit(name, c);
  return outcome;
}

async function main() {
  const cfg = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
  const browser = await launch(cfg, DESKTOP);
  const session = { browser, page: null, viewport: null, state: {} };
  try {
    for (const name of cfg.phases) {
      if (await runPhase(name, cfg, session) === "timeout") {
        process.exitCode = 1;
        break;
      }
    }
  } finally {
    // Зависшая фаза может подвесить и закрытие браузера: ждём его не дольше
    // CLOSE_WAIT, потом останавливаем процесс браузера сами и выходим.
    const closed = await Promise.race([browser.close().then(() => true, () => false),
      sleep(CLOSE_WAIT).then(() => false)]);
    if (!closed) browser.process()?.kill("SIGKILL");
  }
}

main().catch((error) => {
  process.stderr.write(`${error?.stack || error}\n`); // фазы без строки оркестратор отметит сам
  process.exitCode = 1;
}).finally(() => process.exit());
