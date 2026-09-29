// Общее браузерных фаз проверки экрана «Сборка»: puppeteer-core из папки
// движка (не из npm проекта), браузер — chrome-headless-shell из записи
// установщика (не системный Chrome), свой профиль во временной папке.
// Номер процесса браузера сразу пишется в файл учёта (`pidFile`): даже если
// фаза упадёт, оркестратор найдёт и остановит этот браузер. Проверки — в
// `Checks`: `{id: "<фаза>.<имя>", ok, detail}`; снимки экрана — в `shots`.

import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { pathToFileURL } from "node:url";

export const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Схему слоёв сервер считает движком (до 120 с по его пределу); первый раз
 * после сборки — из кэша, но медленная машина CI думает дольше. */
export const SCHEMA_WAIT = 120000;

/** Абсолютные пути, которых не должно быть на странице (и в запросах агенту). */
export const ABSOLUTE = [/\/Users\//, /\/private\//, /\/home\//, /\/tmp\//, /[A-Za-z]:\\/];

export function absoluteIn(text, extra = []) {
  const hits = ABSOLUTE.filter((pattern) => pattern.test(text)).map(String);
  return hits.concat(extra.filter((item) => item && text.includes(item)));
}

export async function launch(cfg, viewport) {
  const require = createRequire(path.join(cfg.modules, "noop.js"));
  const puppeteer = (await import(pathToFileURL(require.resolve("puppeteer-core")).href)).default;
  const args = ["--no-first-run", "--no-default-browser-check", "--disable-extensions"];
  if (process.platform === "linux") args.push("--no-sandbox"); // как у рендера HyperFrames на Linux
  const browser = await puppeteer.launch({
    executablePath: cfg.browser, headless: true, userDataDir: cfg.profile,
    defaultViewport: viewport, args, protocolTimeout: 120000,
  });
  const pid = browser.process()?.pid;
  if (pid) fs.appendFileSync(cfg.pidFile, `${pid}\n`);
  return browser;
}

export class Checks {
  constructor(cfg, phase) {
    this.cfg = cfg;
    this.phase = phase;
    this.checks = [];
    this.shots = [];
    this.data = {};
    this.errors = [];
  }

  add(id, ok, detail = "") {
    this.checks.push({ id: `${this.phase}.${id}`, ok: Boolean(ok), detail: String(detail) });
    return Boolean(ok);
  }

  /** Проверка, которая бросила исключение, — тоже провал, фаза идёт дальше. */
  async step(id, fn) {
    try {
      const [ok, detail] = await fn();
      return this.add(id, ok, detail);
    } catch (error) {
      return this.add(id, false, `ошибка: ${error?.message || error}`);
    }
  }

  async shot(page, name, options = {}) {
    const file = path.join(this.cfg.shots, `${this.phase}-${name}.png`);
    try {
      await page.screenshot({ path: file, ...options });
      this.shots.push(file);
    } catch (error) {
      this.errors.push(`снимок ${name}: ${error?.message || error}`);
    }
  }

  /** Ошибки консоли и страницы — копятся, проверяются в конце фазы. */
  watch(page, label) {
    page.on("console", (message) => {
      if (message.type() === "error") this.errors.push(`${label}: ${message.text()}`);
    });
    page.on("pageerror", (error) => this.errors.push(`${label}: ${error?.message || error}`));
  }
}

/** Ждать, пока `fn()` (в странице) вернёт истину; вернуть последнее значение. */
export async function until(page, fn, arg, { timeout = 15000, every = 250 } = {}) {
  const deadline = Date.now() + timeout;
  let value;
  do {
    value = await page.evaluate(fn, arg).catch(() => undefined);
    if (value) return value;
    await sleep(every);
  } while (Date.now() < deadline);
  return value;
}

/** Нажатие, которое переживает перерисовку: опрос монтажа перерисовывает
 * «Сборку» целиком, и найденная кнопка может уйти со страницы между поиском
 * и нажатием — тогда она ищется заново (не больше `tries` раз). */
export async function click(page, selector, { tap = false, tries = 6 } = {}) {
  for (let attempt = 1; ; attempt += 1) {
    try {
      await (tap ? page.tap(selector) : page.click(selector));
      return;
    } catch (error) {
      const gone = /detached|not clickable|not an Element|No element found/i.test(String(error?.message));
      if (!gone || attempt >= tries) throw error;
      await sleep(250);
    }
  }
}

export const text = (page, selector) => page.$eval(selector, (node) => node.textContent.trim()).catch(() => null);

export async function openProject(page, cfg) {
  await page.goto(`${cfg.baseUrl}/?project=${encodeURIComponent(cfg.projectId)}`, { waitUntil: "load" });
  await page.waitForSelector('[data-part="v2-final-slot"]', { timeout: 30000 });
}

/** Окно «Запрос для агента» по кнопке: текст запроса; окно закрывается. */
export async function promptOf(page, selector) {
  await click(page, selector);
  await page.waitForSelector('dialog[data-hook="chat-prompt-dialog"][open]', { timeout: 10000 });
  const value = await page.$eval('dialog[data-hook="chat-prompt-dialog"] textarea', (area) => area.value);
  await click(page, 'dialog[data-hook="chat-prompt-dialog"] .chat-prompt-close');
  return value;
}

/** «Открыть монтажный стол» на экране: ссылка «Перейти к монтажному столу ↗»
 * или null. Вкладку, которую экран открыл сам по нажатию, закрываем —
 * ссылку проверка открывает в своей новой странице. */
export async function openDeskFromScreen(browser, page, timeout = 90000) {
  const popup = new Promise((resolve) => browser.once("targetcreated", resolve));
  await click(page, '[data-hook="am-desk"] [data-action="desk-open"]');
  const link = await page.waitForSelector('[data-part="am-desk-go"]', { timeout })
    .then(() => page.$eval('[data-part="am-desk-go"]', (a) => ({
      href: a.href, rel: a.rel, target: a.target, text: a.textContent.trim() })))
    .catch(() => null);
  const target = await Promise.race([popup, sleep(5000).then(() => null)]);
  const tab = target ? await target.page().catch(() => null) : null;
  await tab?.close().catch(() => null);
  return link;
}
