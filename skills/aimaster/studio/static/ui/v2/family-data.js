// Read-only family context; no second creative store.
const cache = new Map();
const checked = new Map();
let flight = null, requested = null;
async function json(path) {
  try { const response = await fetch(path, { headers: { Accept: "application/json" } }); return response.ok ? await response.json() : null; }
  catch { return null; }
}
export function loadFamilyData(projectId, { force = false } = {}) {
  if (!projectId) return Promise.resolve();
  requested = projectId;
  if (flight) {
    if (flight.projectId === projectId) return flight.task;
    return flight.task.then(() => requested === projectId ? loadFamilyData(projectId, { force }) : undefined);
  }
  if (!force && Date.now() - (checked.get(projectId) || 0) < 4000) return Promise.resolve();
  const task = Promise.all([
    json("/api/operator"), json("/api/library"),
    json(`/api/projects/${encodeURIComponent(projectId)}/routes`),
  ]).then((result) => {
    const next = { operator: result[0], library: result[1], routes: result[2] };
    if (JSON.stringify(cache.get(projectId)) !== JSON.stringify(next)) {
      if (!cache.has(projectId) && cache.size >= 32) { const oldest = cache.keys().next().value; cache.delete(oldest); checked.delete(oldest); }
      cache.set(projectId, next);
      document.dispatchEvent(new CustomEvent("studio:family-data", { detail: { projectId } }));
    }
  }).finally(() => { checked.set(projectId, Date.now()); flight = null; });
  flight = { projectId, task }; return task;
}
export function familyData(projectId) { return cache.get(projectId) || {}; }
