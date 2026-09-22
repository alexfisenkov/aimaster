// node --test skills/aimaster/studio/static/ui/v2/decide.test.mjs
//
// Проверяется то, что уходит на сервер: чем адресуется вариант, какие
// шесть действий вообще предлагаются и что лежит в payload каждого.
// Фикстура — живой snapshot владельца (стадия `motion`).

import test from "node:test";
import assert from "node:assert/strict";

import {
  RESULT_STAGE_BY_COLLECTION,
  directActionRequest,
  directActionsFor,
  resultTargetId,
} from "./decide.js";
import { PROJECT, VIEW_STAGE } from "./snapshot.fixture.mjs";

const ALLOWED = VIEW_STAGE.allowed_actions;
const STAGE = VIEW_STAGE.current_stage;
const VIDEO = PROJECT.video_results[0];

test("адресуется версия, а группа — только при её отсутствии", () => {
  assert.equal(resultTargetId(VIDEO), "result:scene:cafe-open:video-v1");
  assert.equal(resultTargetId({ result_id: "result:ref:IMG_04" }), "result:ref:IMG_04");
  assert.equal(resultTargetId(null), null);
});

test("стадия решает, чьи карточки можно трогать", () => {
  assert.equal(RESULT_STAGE_BY_COLLECTION.video_results, "motion");
  const onMotion = directActionsFor({
    allowedActions: ALLOWED, currentStage: STAGE, collection: "video_results", version: VIDEO,
  });
  assert.deepEqual(onMotion, ["approve", "reject", "hide", "retire"]);
  const onFrames = directActionsFor({
    allowedActions: ALLOWED, currentStage: STAGE, collection: "image_results", version: PROJECT.image_results[0],
  });
  assert.deepEqual(onFrames, [], "кадры на стадии motion решениям не подлежат");
});

test("vary и regenerate не предлагаются никогда, хотя сервер их разрешает", () => {
  assert.ok(ALLOWED.includes("vary") && ALLOWED.includes("regenerate"));
  const actions = directActionsFor({
    allowedActions: ALLOWED, currentStage: STAGE, collection: "video_results", version: VIDEO,
  });
  assert.ok(!actions.includes("vary"));
  assert.ok(!actions.includes("regenerate"));
});

test("скрытому предлагают «показать», убранному — только «вернуть»", () => {
  const hidden = directActionsFor({
    allowedActions: ALLOWED, currentStage: STAGE, collection: "video_results",
    version: { ...VIDEO, hidden: true },
  });
  assert.deepEqual(hidden, ["approve", "reject", "unhide", "retire"]);
  const retired = directActionsFor({
    allowedActions: ALLOWED, currentStage: STAGE, collection: "video_results",
    version: { ...VIDEO, retired: true },
  });
  assert.deepEqual(retired, ["restore"]);
});

test("без варианта действий нет вовсе", () => {
  assert.deepEqual(directActionsFor({ allowedActions: ALLOWED, currentStage: STAGE, collection: "video_results" }), []);
});

test("payload шести прямых действий", () => {
  for (const actionType of ["approve", "hide", "unhide", "retire", "restore"]) {
    assert.deepEqual(directActionRequest(actionType, VIDEO, 62), {
      actionType,
      targetId: "result:scene:cafe-open:video-v1",
      payload: {},
      expectedRevision: 62,
    });
  }
  assert.deepEqual(directActionRequest("reject", VIDEO, 62, { comment: "  слишком темно  " }), {
    actionType: "reject",
    targetId: "result:scene:cafe-open:video-v1",
    payload: { comment: "слишком темно" },
    expectedRevision: 62,
  });
  assert.deepEqual(directActionRequest("reject", VIDEO, 62).payload, { comment: "" });
});
