// node --test skills/aimaster/studio/static/ui/v2/decide.test.mjs
//
// Проверяется то, что уходит на сервер: чем адресуется вариант, какие
// шесть действий вообще предлагаются и что лежит в payload каждого.
// Фикстура — живой snapshot владельца (стадия `motion`).

import test from "node:test";
import assert from "node:assert/strict";

import {
  RESULT_STAGE_BY_COLLECTION,
  SUBMITTING_TEXT,
  decideDraftKeys,
  directActionRequest,
  directActionsFor,
  isSubmitting,
  resultTargetId,
} from "./decide.js";
import { footerMode } from "./footer.js";
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


test("пока запрос в полёте, просмотрщик считается занятым", () => {
  assert.equal(isSubmitting(SUBMITTING_TEXT), true);
  assert.equal(isSubmitting("Решение отправлено."), false);
  assert.equal(isSubmitting("Исход не подтверждён. Обновите страницу."), false);
  assert.equal(isSubmitting(""), false);
  assert.equal(isSubmitting(undefined), false);
});

test("ключи черновиков ряда решений — свои для каждого варианта", () => {
  assert.deepEqual(decideDraftKeys("dashboard-dialogue", VIDEO), [
    "dashboard-dialogue::v2-viewer::result:scene:cafe-open:video-v1",
    "dashboard-dialogue::more-menu::v2-viewer:result:scene:cafe-open:video-v1",
  ]);
  assert.deepEqual(decideDraftKeys("dashboard-dialogue", { asset_url: "/assets/x" }), [], "у файла без версии черновиков нет");
  assert.deepEqual(decideDraftKeys("", VIDEO), []);
});

test("подвал: одобренная сборка не показывает кнопку вовсе", () => {
  const onAssembly = (gateStatus) => ({
    revision: 70,
    active_project: { ...PROJECT, stage: "assembly" },
    view_stage: { current_stage: "assembly", gate_status: gateStatus, allowed_actions: ["approve", "reject"] },
  });
  assert.equal(footerMode(onAssembly("draft"), { screen: "assembly", stage: "assembly" }), "decide");
  assert.equal(footerMode(onAssembly("approved"), { screen: "assembly", stage: "assembly" }), "done");
});

test("подвал: пройденный шаг и шаг без прямого действия", () => {
  const snapshot = {
    revision: 64,
    active_project: PROJECT,
    view_stage: { current_stage: "motion", gate_status: "draft", allowed_actions: VIEW_STAGE.allowed_actions },
  };
  assert.equal(footerMode(snapshot, { screen: "frames", stage: "motion" }), "past");
  assert.equal(footerMode(snapshot, { screen: "video", stage: "motion" }), "decide");
  const blocked = { ...snapshot, view_stage: { ...snapshot.view_stage, allowed_actions: ["continue-in-chat"] } };
  assert.equal(footerMode(blocked, { screen: "video", stage: "motion" }), "chat");
});

test("текст тоста по действию и материалу", async () => {
  const { outcomeToast } = await import("./decide.js");
  assert.equal(outcomeToast("approve", "кадр"), "Кадр принят");
  assert.equal(outcomeToast("approve", "картинка"), "Картинка принята");
  assert.equal(outcomeToast("approve", "клип"), "Клип принят");
  assert.equal(outcomeToast("approve", "звук"), "Звук принят");
  assert.equal(outcomeToast("reject"), "Вариант отклонён");
  assert.equal(outcomeToast("hide"), "Вариант скрыт");
  assert.equal(outcomeToast(""), "");
});

test("строка «в полёте» — одна на ряд и card-forms", async () => {
  const forms = await import("../card-forms.js");
  assert.equal(SUBMITTING_TEXT, forms.SUBMITTING_TEXT);
  assert.equal(forms.isConfirmedSuccess({ ok: true, confirmed: true }), true);
  assert.equal(forms.isConfirmedSuccess({ ok: true, confirmed: false }), false);
  assert.equal(forms.isConfirmedSuccess({ ok: false, code: "action_failed" }), false);
});

test("подвал: ключ одобрения — проект и стадия; без запроса в полёте — свободно", async () => {
  const { footerFlightKey, footerInFlight } = await import("./footer.js");
  assert.equal(footerFlightKey("p", "motion"), "p::motion");
  assert.notEqual(footerFlightKey("p", "motion"), footerFlightKey("q", "motion"));
  assert.equal(footerInFlight(footerFlightKey("p", "motion")), false);
});
