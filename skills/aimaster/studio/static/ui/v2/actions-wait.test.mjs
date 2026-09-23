// node --test skills/aimaster/studio/static/ui/v2/actions-wait.test.mjs
//
// Прямое решение подтверждается статусом своего `action_id`, а не любым
// сдвигом ревизии проекта (`ui/actions.js`, `requireActionSuccess`).

import test from "node:test";
import assert from "node:assert/strict";

import { setActiveProject, submitAction } from "../actions.js";

function mockServer({ revisionAfter, actions }) {
  const calls = [];
  globalThis.fetch = async (path, init = {}) => {
    calls.push([init.method || "GET", String(path)]);
    const json = (body, status = 200) => ({ ok: status < 400, status, json: async () => body });
    if (path === "/api/session") return json({ csrf_token: "t" });
    if (path === "/api/actions") return json({ action_id: "a-1", revision: 5, status: "queued" }, 202);
    return json({ revision: revisionAfter, actions });
  };
  return calls;
}

const FAST = { budgetMs: 200, initialMs: 5, maxMs: 10 };

test("ревизия сдвинулась, а своё действие провалилось — не успех", async () => {
  setActiveProject("p");
  mockServer({ revisionAfter: 6, actions: [{ action_id: "a-1", status: "failed" }] });
  const controls = [{ disabled: false }];
  const result = await submitAction({
    actionType: "approve", targetId: "v", payload: {}, expectedRevision: 5,
    controls, waitOptions: FAST, requireActionSuccess: true,
  });
  assert.equal(result.ok, false);
  assert.equal(result.code, "action_failed");
  assert.equal(controls[0].disabled, false, "кнопка снова доступна");
});

test("ревизия сдвинулась чужой записью, своё действие ещё не видно — не подтверждено", async () => {
  setActiveProject("p");
  mockServer({ revisionAfter: 6, actions: [{ action_id: "other", status: "succeeded" }] });
  const result = await submitAction({
    actionType: "approve", targetId: "v", payload: {}, expectedRevision: 5,
    waitOptions: FAST, requireActionSuccess: true,
  });
  assert.equal(result.ok, true);
  assert.equal(result.confirmed, false);
});

test("своё действие succeeded — подтверждено", async () => {
  setActiveProject("p");
  const calls = mockServer({ revisionAfter: 6, actions: [{ action_id: "a-1", status: "succeeded" }] });
  const result = await submitAction({
    actionType: "approve", targetId: "v", payload: {}, expectedRevision: 5,
    waitOptions: FAST, requireActionSuccess: true,
  });
  assert.equal(result.confirmed, true);
  assert.equal(calls.filter(([method]) => method === "POST").length, 1, "один POST на клик");
});
