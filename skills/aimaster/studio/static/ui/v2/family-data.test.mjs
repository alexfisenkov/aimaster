import test from "node:test";
import assert from "node:assert/strict";
import { loadFamilyData, familyData } from "./family-data.js";

test("family context refresh is bounded across project changes and independent of creative revision", async () => {
  const original = { fetch: globalThis.fetch, document: globalThis.document, CustomEvent: globalThis.CustomEvent };
  let active = 0, peak = 0, calls = 0, available = true;
  globalThis.document = { dispatchEvent() {} };
  globalThis.CustomEvent = class { constructor(type, options) { this.type = type; this.detail = options?.detail; } };
  globalThis.fetch = async (path) => {
    calls++; peak = Math.max(peak, ++active);
    await new Promise((resolve) => setTimeout(resolve, 20)); active--;
    const payload = path === "/api/operator" ? { available } : { path };
    return { ok: true, json: async () => payload };
  };
  try {
    await Promise.all([loadFamilyData("test-a"), loadFamilyData("test-b")]);
    assert.ok(peak <= 3, "more than one context refresh batch was in flight");
    assert.equal(familyData("test-b").routes.path, "/api/projects/test-b/routes");
    const before = calls; await loadFamilyData("test-b"); assert.equal(calls, before);
    available = false; await loadFamilyData("test-b", { force: true });
    assert.equal(familyData("test-b").operator.available, false);
    assert.equal(familyData("test-a").routes.path, "/api/projects/test-a/routes");
  } finally { Object.assign(globalThis, original); }
});
