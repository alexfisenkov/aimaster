// Presentation preferences only. Canonical project content stays on the server.
const KEY = "aimaster.family.preferences.v1";
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
export function saveFamilyPreference(value) {
  const next = familyPreference(value);
  try { localStorage.setItem(KEY, JSON.stringify(next)); } catch { /* storage is optional */ }
  applyFamilyPreference(next);
  return next;
}
export function applyFamilyPreference(value) {
  const next = familyPreference(value);
  document.documentElement.lang = next.locale;
  document.documentElement.dataset.theme = next.theme;
  document.documentElement.dataset.view = next.view;
  return next;
}
