// Самый маленький DOM для node-тестов блоков экрана «Сборка»
// (montage-screen.test.mjs): узлы, `dataset`, атрибуты, обработчики, CSSOM
// `style.setProperty`, `isConnected`. Раскладки, стилей и фокуса нет — вид
// проверяется в браузере (задача 20). Имя не *.test.mjs: node --test этот
// файл сам не запускает.

class FakeStyle {
  constructor() {
    this.values = new Map();
  }

  setProperty(name, value) {
    this.values.set(name, String(value));
  }

  getPropertyValue(name) {
    return this.values.get(name) ?? "";
  }
}

const ATTRIBUTE = /\[([\w-]+)="([^"]*)"\]/g;

/** `.класс[атрибут="значение"]…` — чего хватает модулям экрана. */
function matches(node, selector) {
  const classes = (selector.replace(ATTRIBUTE, "").match(/\.[\w-]+/g) || []).map((part) => part.slice(1));
  const own = node.className.split(/\s+/);
  if (!classes.every((name) => own.includes(name))) return false;
  for (const [, name, value] of selector.matchAll(ATTRIBUTE)) {
    const actual = name.startsWith("data-")
      ? node.dataset[name.slice(5).replace(/-(\w)/g, (_, letter) => letter.toUpperCase())]
      : node.getAttribute(name);
    if (actual !== value) return false;
  }
  return true;
}

export class FakeElement {
  constructor(tag, doc) {
    this.tagName = tag.toUpperCase();
    this.ownerDocument = doc;
    this.children = [];
    this.parentNode = null;
    this.dataset = {};
    this.attributes = new Map();
    this.listeners = new Map();
    this.style = new FakeStyle();
    this.className = "";
    this.ownText = "";
    this.disabled = false;
    this.hidden = false;
    this.open = false;
    this.scrollLeft = 0;
  }

  get textContent() {
    return this.ownText + this.children.map((child) => child.textContent).join("");
  }

  set textContent(value) {
    for (const child of this.children) child.parentNode = null;
    this.children = [];
    this.ownText = value === null || value === undefined ? "" : String(value);
  }

  append(...nodes) {
    for (const item of nodes) {
      const node = typeof item === "string" ? this.ownerDocument.createText(item) : item;
      node.remove();
      node.parentNode = this;
      this.children.push(node);
    }
  }

  prepend(...nodes) {
    const rest = this.children;
    this.children = [];
    this.append(...nodes);
    this.children.push(...rest);
  }

  remove() {
    if (!this.parentNode) return;
    this.parentNode.children = this.parentNode.children.filter((child) => child !== this);
    this.parentNode = null;
  }

  get childElementCount() {
    return this.children.filter((child) => child.tagName !== "#TEXT").length;
  }

  get isConnected() {
    let node = this;
    while (node.parentNode) node = node.parentNode;
    return node === this.ownerDocument.body;
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  getAttribute(name) {
    return this.attributes.has(name) ? this.attributes.get(name) : null;
  }

  removeAttribute(name) {
    this.attributes.delete(name);
  }

  addEventListener(type, listener) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(listener);
  }

  /** Позвать обработчики `type` и дождаться их (async-обработчики кнопок). */
  async fire(type) {
    await Promise.all((this.listeners.get(type) || []).map((listener) => listener({ type, target: this })));
  }

  focus() {}

  /** Все узлы ниже этого, по порядку. */
  descendants() {
    return this.children.flatMap((child) => [child, ...child.descendants()]);
  }

  querySelectorAll(selector) {
    return this.descendants().filter((node) => node.tagName !== "#TEXT" && matches(node, selector));
  }

  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }
}

/** Поставить `globalThis.document`; вернуть его и `restore()`. События
 * документа (`studio:montage-updated`, `studio:refresh-snapshot`, …) — в
 * `doc.events`. */
export function installFakeDom() {
  const saved = globalThis.document;
  const doc = {
    events: [],
    createElement: (tag) => new FakeElement(tag, doc),
    createText(text) {
      const node = new FakeElement("#text", doc);
      node.ownText = text;
      return node;
    },
    dispatchEvent(event) {
      doc.events.push({ type: event.type, detail: event.detail });
      return true;
    },
    addEventListener() {},
    querySelector: () => null,
  };
  doc.body = new FakeElement("body", doc);
  globalThis.document = doc;
  return { doc, restore: () => { globalThis.document = saved; } };
}

/** Узлы с этим `data-action` (метка фокуса `markControlHooks`). */
export function byAction(root, action) {
  return root.descendants().filter((node) => node.dataset?.action === action);
}
