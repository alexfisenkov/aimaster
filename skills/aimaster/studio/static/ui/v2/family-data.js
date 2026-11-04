// Read-only family context; no second creative store.
const cache = new Map();
async function json(path) {
  try { const response = await fetch(path, { headers: { Accept: "application/json" } }); return response.ok ? await response.json() : null; }
  catch { return null; }
}
export async function loadFamilyData(projectId) {
  const result = await Promise.all([
    json("/api/operator"), json("/api/library"),
    json(`/api/projects/${encodeURIComponent(projectId)}/routes`),
  ]);
  cache.set(projectId, { operator: result[0], library: result[1], routes: result[2] });
  document.dispatchEvent(new CustomEvent("studio:family-data", { detail: { projectId } }));
}
export function familyData(projectId) { return cache.get(projectId) || {}; }
