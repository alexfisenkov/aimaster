// Runs before CSS to prevent a wrong-theme first frame. No user content is read.
try {
  const value = JSON.parse(localStorage.getItem("aimaster.family.preferences.v1") || "{}");
  document.documentElement.dataset.theme = ["system", "light", "dark"].includes(value.theme) ? value.theme : "system";
  const locale = value.locale || value.language;
  document.documentElement.lang = ["ru", "en"].includes(locale) ? locale
    : /^ru(?:-|$)/i.test(navigator.language || "") ? "ru" : "en";
  document.documentElement.dataset.view = value.view === "overview" ? "overview" : "stages";
} catch {
  document.documentElement.dataset.theme = "system";
}
