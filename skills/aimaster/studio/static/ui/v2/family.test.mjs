import test from "node:test";
import assert from "node:assert/strict";
import { familyPreference, familyLabel } from "./family.js";
import { overlayFromDrag, pointInCanvas } from "./overlay-editor.js";
import { selectedSpending, canDirectAction } from "./family-actions.js";

test("family preferences reject unknown values and translate only interface copy", () => {
  assert.deepEqual(familyPreference({ view: "overview", theme: "dark", locale: "en" }), { view: "overview", theme: "dark", locale: "en" });
  assert.deepEqual(familyPreference({ view: "broken", theme: "purple", locale: "fr" }), { view: "stages", theme: "system", locale: "ru" });
  assert.equal(familyLabel("overview", "en"), "Entire project");
});

test("overlay drag uses model canvas pixels across a resized preview", () => {
  const bounds = { left: 30, top: 20, width: 320, height: 180 };
  const canvas = { width: 1920, height: 1080 };
  assert.deepEqual(pointInCanvas({ clientX: 190, clientY: 110 }, bounds, canvas), [960, 540]);
  const shape = overlayFromDrag("rect", [300, 200], [900, 800], canvas);
  assert.deepEqual(shape.geometry, { x: 300, y: 200, width: 600, height: 600 });
  assert.deepEqual(shape.canvas, canvas);
});

test("paid action uses exact saved route and only live operator", () => {
  const route = { status: "selected", route_id: "route-1", provider: "vendor", model: "model", position_id: "scene-1" };
  assert.deepEqual(selectedSpending(route), { confirmed: true, route_id: "route-1", provider: "vendor", model: "model" });
  assert.equal(selectedSpending({ ...route, status: "needs_setup" }), null);
  assert.equal(canDirectAction({ available: true }, ["generate"], "generate", selectedSpending(route)), true);
  assert.equal(canDirectAction({ available: false }, ["generate"], "generate", selectedSpending(route)), false);
  assert.equal(canDirectAction({ available: true }, ["generate"], "generate", null), false);
});
