import test from "node:test";
import assert from "node:assert/strict";
import { recoveryRequest, postRecovery, renderRecovery, safePreviewUrl } from "./recovery.js";
import { _resetCsrfTokenForTests } from "../actions.js";
import { loadFamilyData } from "./family-data.js";
import { installFakeDom } from "./montage-fake-dom.mjs";

test("recovery accepts only bounded operations and carries project and revision", () => {
  const id = "action-" + "a".repeat(32);
  assert.deepEqual(recoveryRequest("project", id, "keep", 7), { path: `/api/projects/project/recovery/${id}`, body: { operation: "keep", expected_revision: 7 } });
  assert.equal(recoveryRequest("project", id, "https://example.invalid", 7), null);
  assert.equal(recoveryRequest("project", "../bad", "retry", 7), null);
  assert.equal(recoveryRequest("project", id, "adopt", -1), null);
});

test("conflict offers verified media and explicit decisions", async () => {
  const { restore } = installFakeDom();
  const saved = globalThis.fetch, id = "action-" + "c".repeat(32);
  globalThis.fetch = async (path) => ({ ok: true, json: async () => path.endsWith("/routes")
    ? { collections: [{ action_id: id, phase: "conflict", position_id: "pos:scene:s1:video", can_keep: true, can_adopt: true, preview: { url: "/assets/asset-" + "a".repeat(32), mime_type: "video/mp4" } }] } : {} });
  try {
    await loadFamilyData("recovery-test", { force: true });
    const panel = renderRecovery({ revision: 5, active_project: { id: "recovery-test" } });
    assert.ok(panel.querySelector('[data-hook="recovery-adopt"]'));
    assert.ok(panel.querySelector('[data-hook="recovery-keep"]'));
    assert.equal(panel.textContent.includes(id), false);
    assert.equal(panel.textContent.includes("Провайдер"), false);
  } finally { globalThis.fetch = saved; restore(); }
});

test("preview permits only local opaque asset URLs and Mini App tickets", () => {
  const path = "/assets/asset-" + "a".repeat(32);
  assert.equal(safePreviewUrl(path), true);
  assert.equal(safePreviewUrl(path + "?e=123&t=" + "f".repeat(64)), true);
  assert.equal(safePreviewUrl("https://example.invalid/video.mp4"), false);
  assert.equal(safePreviewUrl(path + "?url=evil"), false);
});

test("a previously applied adoption offers completion without another choice", async () => {
  const { restore } = installFakeDom();
  const saved = globalThis.fetch, id = "action-" + "d".repeat(32);
  globalThis.fetch = async (path) => ({ ok: true, json: async () => path.endsWith("/routes")
    ? { collections: [{ action_id:id, phase:"conflict", can_adopt:true, can_keep:false, resume_applied:true,
      preview:{url:"/assets/asset-" + "a".repeat(32),mime_type:"image/png"} }] } : {} });
  try {
    await loadFamilyData("recovery-resume", { force:true });
    const panel = renderRecovery({ revision:8, active_project:{id:"recovery-resume"} });
    assert.ok(panel.textContent.includes("Завершить восстановление"));
    assert.ok(panel.querySelector('[data-hook="recovery-adopt"]'));
    assert.equal(panel.querySelector('[data-hook="recovery-keep"]'), null);
  } finally { globalThis.fetch = saved; restore(); }
});

test("recovery sends a CSRF-protected request and no locator", async () => {
  const original = globalThis.fetch, calls = [];
  _resetCsrfTokenForTests();
  globalThis.fetch = async (path, options) => {
    calls.push({ path, options });
    return path === "/api/session" ? { ok: true, json: async () => ({ csrf_token: "token" }) } : { ok: true };
  };
  try {
    assert.deepEqual(await postRecovery("p", "action-" + "b".repeat(32), "retry", 4), { ok: true });
    assert.equal(calls[1].options.headers["X-CSRF-Token"], "token");
    assert.deepEqual(JSON.parse(calls[1].options.body), { operation: "retry", expected_revision: 4 });
  } finally { globalThis.fetch = original; _resetCsrfTokenForTests(); }
});
