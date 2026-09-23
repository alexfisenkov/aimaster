// node --test skills/aimaster/studio/static/ui/v2/responsive.test.mjs

import test from "node:test";
import assert from "node:assert/strict";

import { PHONE_QUERY, isPhone, onViewportChange } from "./responsive.js";

test("без window телефон не угадываем, отписка всё равно функция", () => {
  assert.equal(isPhone(), false);
  const off = onViewportChange(() => {});
  assert.equal(typeof off, "function");
  off();
});

test("брейкпойнт тот же, что в CSS, и слушатель снимается", () => {
  const listeners = new Set();
  const list = {
    matches: true,
    addEventListener: (_type, fn) => listeners.add(fn),
    removeEventListener: (_type, fn) => listeners.delete(fn),
  };
  let asked = null;
  globalThis.window = { matchMedia: (query) => { asked = query; return list; } };
  try {
    assert.equal(isPhone(), true);
    assert.equal(asked, PHONE_QUERY);
    assert.equal(PHONE_QUERY, "(max-width: 759px)");
    const seen = [];
    const off = onViewportChange((phone) => seen.push(phone));
    for (const fn of listeners) fn({ matches: false });
    assert.deepEqual(seen, [false]);
    off();
    assert.equal(listeners.size, 0);
  } finally {
    delete globalThis.window;
  }
});
