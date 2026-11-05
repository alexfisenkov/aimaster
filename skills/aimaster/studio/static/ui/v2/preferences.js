// Presentation preferences only. Canonical project content stays on the server.
import { postJson } from "../actions.js";
const KEY = "aimaster.family.preferences.v1";
let pending = {}, saving = false, localRevision = 0;
async function persist(change) {
  pending = { ...pending, ...change };
  if (saving) return;
  saving = true;
  try {
    while (Object.keys(pending).length) {
      const value = pending; pending = {};
      await postJson("/api/preferences", value, 200);
    }
  } finally { saving = false; }
}
export function saveRailPreference(collapsed) {
  localRevision++;
  void persist({ rail: collapsed ? "collapsed" : "docked" });
}
export async function loadWorkspacePreference() {
  const revision = localRevision;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 4000);
  try {
    const response = await fetch("/api/preferences", { signal: controller.signal, headers: { Accept: "application/json" } });
    if (!response.ok) return;
    const value = await response.json();
    if (revision !== localRevision || !value || typeof value !== "object" || !Object.keys(value).length) return;
    saveFamilyPreference({ ...readFamilyPreference(), ...value }, false);
    if (["collapsed", "docked"].includes(value.rail)) {
      try { localStorage.setItem("aimaster.v2.railCollapsed", value.rail === "collapsed" ? "1" : "0"); } catch { /* optional fallback */ }
      document.dispatchEvent(new CustomEvent("studio:rail-preference", { detail: { collapsed: value.rail === "collapsed" } }));
    }
    document.dispatchEvent(new Event("studio:family-preference"));
  } catch { /* origin-local first paint remains usable offline */ }
  finally { clearTimeout(timer); }
}
const LABELS = {
  stages: ["Этапы", "Stages"], overview: ["Весь проект", "Entire project"],
  language: ["Язык", "Language"], theme: ["Тема", "Theme"],
  system: ["Системная", "System"], light: ["Светлая", "Light"], dark: ["Тёмная", "Dark"],
  library: ["Библиотека", "Library"], operator: ["Исполнитель", "Executor"],
  unavailable: ["Исполнитель остановлен. Продолжите в чате.", "Executor is offline. Continue in chat."],
};

export function familyPreference(input = {}, fallbackLocale = "ru") {
  return {
    view: ["stages", "overview"].includes(input.view) ? input.view : "stages",
    theme: ["system", "light", "dark"].includes(input.theme) ? input.theme : "system",
    locale: ["ru", "en"].includes(input.locale || input.language) ? input.locale || input.language : fallbackLocale,
  };
}
export function familyLabel(key, language = "ru") {
  return LABELS[key]?.[language === "en" ? 1 : 0] || key;
}
export function readFamilyPreference() {
  const fallback = /^ru(?:-|$)/i.test(navigator.language || "") ? "ru" : "en";
  try { return familyPreference(JSON.parse(localStorage.getItem(KEY) || "{}"), fallback); }
  catch { return familyPreference({}, fallback); }
}
export function saveFamilyPreference(value, remote = true) {
  const next = familyPreference(value);
  try { localStorage.setItem(KEY, JSON.stringify(next)); } catch { /* storage is optional */ }
  applyFamilyPreference(next);
  if (remote) { localRevision++; void persist(next); }
  return next;
}
export function applyFamilyPreference(value) {
  const next = familyPreference(value);
  document.documentElement.lang = next.locale;
  document.documentElement.dataset.theme = next.theme;
  document.documentElement.dataset.view = next.view;
  return next;
}
