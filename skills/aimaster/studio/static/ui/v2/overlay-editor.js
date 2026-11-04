// Typed drawing geometry in the montage model's own canvas pixels.
import { el } from "./dom.js";
import { postMontage, refusalText } from "./montage-api.js";
import { refreshMontage } from "./montage-feed.js";
import { t } from "./locale.js";
const SVG = "http://www.w3.org/2000/svg";
const TYPES = { rect: "Рамка", ellipse: "Эллипс", arrow: "Стрелка", stroke: "Штрих" };
const drafts = new Map();
const round = (number) => Math.round(number * 100) / 100;
export function pointInCanvas(event, bounds, canvas) {
  const x = Math.max(0, Math.min(canvas.width, (event.clientX - bounds.left) * canvas.width / bounds.width));
  const y = Math.max(0, Math.min(canvas.height, (event.clientY - bounds.top) * canvas.height / bounds.height));
  return [round(x), round(y)];
}
export function overlayFromDrag(type, start, end, canvas, points = []) {
  let geometry;
  if (type === "rect" || type === "ellipse") geometry = {
    x: Math.min(start[0], end[0]), y: Math.min(start[1], end[1]),
    width: Math.abs(end[0] - start[0]), height: Math.abs(end[1] - start[1]),
  };
  else if (type === "arrow") geometry = { x1: start[0], y1: start[1], x2: end[0], y2: end[1] };
  else geometry = { points: points.length > 1 ? points.slice(0, 1024) : [start, end] };
  return { type, canvas, geometry, color: "#36C66B", stroke_width: 6, opacity: 1, draw_on: 0, scene_id: null };
}
function shapeNode(data) {
  const g = data.geometry || {};
  const node = document.createElementNS(SVG, data.type === "rect" ? "rect" : data.type === "ellipse" ? "ellipse" : "path");
  if (data.type === "rect") for (const key of ["x", "y", "width", "height"]) node.setAttribute(key, String(g[key]));
  if (data.type === "ellipse") {
    node.setAttribute("cx", String(g.x + g.width / 2)); node.setAttribute("cy", String(g.y + g.height / 2));
    node.setAttribute("rx", String(g.width / 2)); node.setAttribute("ry", String(g.height / 2));
  }
  if (data.type === "arrow") node.setAttribute("d", `M ${g.x1} ${g.y1} L ${g.x2} ${g.y2}`);
  if (data.type === "stroke") node.setAttribute("d", (g.points || []).map((p, i) => `${i ? "L" : "M"} ${p[0]} ${p[1]}`).join(" "));
  node.setAttribute("fill", data.type === "rect" || data.type === "ellipse" ? "transparent" : "none");
  node.setAttribute("pointer-events", "all"); node.setAttribute("stroke", data.color);
  node.setAttribute("stroke-width", String(data.stroke_width)); node.setAttribute("opacity", String(data.opacity));
  node.setAttribute("vector-effect", "non-scaling-stroke");
  if (data.type === "arrow") {
    const angle = Math.atan2(g.y2 - g.y1, g.x2 - g.x1), size = Math.max(12, data.stroke_width * 4);
    const wing = document.createElementNS(SVG, "path");
    wing.setAttribute("d", `M ${g.x2 - size * Math.cos(angle - .5)} ${g.y2 - size * Math.sin(angle - .5)} L ${g.x2} ${g.y2} L ${g.x2 - size * Math.cos(angle + .5)} ${g.y2 - size * Math.sin(angle + .5)}`);
    wing.setAttribute("fill", "none"); wing.setAttribute("stroke", data.color); wing.setAttribute("stroke-width", String(data.stroke_width));
    const group = document.createElementNS(SVG, "g"); group.append(node, wing); return group;
  }
  return node;
}
export function renderOverlayEditor({ project, snapshot, model, status }) {
  const canvas = status?.canvas || project?.montage?.canvas;
  if (!model?.model_hash || !canvas?.width || !canvas?.height || !status?.exists) return null;
  const section = el("section", "v2-card am-overlay-editor");
  section.dataset.hook = "am-overlay-editor";
  section.append(el("h2", "v2-card-title", t("Пометки на кадре")));
  const hint = el("p", "v2-section-hint", t("Выберите инструмент и проведите по кадру. Сохранённая пометка попадёт в монтаж."));
  const tools = el("div", "am-overlay-tools");
  const savedDraft = drafts.get(project.id)?.hash === model.model_hash ? drafts.get(project.id) : null;
  const mode = el("select", "am-overlay-select"); mode.setAttribute("aria-label", t("Инструмент"));
  for (const [value, label] of Object.entries(TYPES)) { const option = el("option", "", t(label)); option.value = value; mode.append(option); }
  const color = el("input", "am-overlay-color"); color.type = "color"; color.value = "#36c66b"; color.setAttribute("aria-label", t("Цвет пометки"));
  const width = el("input", "am-overlay-width"); width.type = "number"; width.min = "0.5"; width.max = "100"; width.step = "0.5"; width.value = "6"; width.setAttribute("aria-label", t("Толщина линии"));
  tools.append(mode, color, width);
  if (savedDraft) { mode.value = savedDraft.mode; color.value = savedDraft.color; width.value = String(savedDraft.width); }
  const updateStyle = () => { if (!draft) return; draft.color = color.value.toUpperCase(); draft.stroke_width = Number(width.value); paint(); };
  color.addEventListener("input", updateStyle); width.addEventListener("change", updateStyle);
  const stage = el("div", "am-overlay-stage"); stage.style.setProperty("--am-canvas-ratio", `${canvas.width} / ${canvas.height}`);
  const selected = project?.montage?.versions?.find((item) => item.id === project.montage.current_version);
  let video = null;
  if (selected?.asset_url?.startsWith("/assets/")) {
    video = el("video", "am-overlay-media"); video.src = selected.asset_url; video.controls = true; video.preload = "metadata"; video.playsInline = true; stage.append(video);
  }
  const svg = document.createElementNS(SVG, "svg"); svg.setAttribute("viewBox", `0 0 ${canvas.width} ${canvas.height}`);
  svg.setAttribute("aria-label", t("Холст пометок")); svg.setAttribute("role", "img"); svg.classList.add("am-overlay-canvas"); stage.append(svg);
  const statusLine = el("p", "am-overlay-status"); statusLine.setAttribute("role", "status");
  const existing = (model.layers || []).find((layer) => layer.layer === "overlays")?.clips || [];
  let chosen = existing.find((item) => item.id === savedDraft?.chosenId) || null;
  let draft = savedDraft?.draft || null; let start = null; let points = []; let moving = null;
  const draw = () => {
    svg.replaceChildren();
    for (const clip of existing) if (clip.overlay) {
      const node = shapeNode(clip.overlay); node.dataset.clip = clip.id; node.classList.add("am-overlay-existing");
      node.addEventListener("pointerdown", (event) => {
        event.stopPropagation(); event.preventDefault(); chosen = clip; draft = structuredClone(clip.overlay);
        moving = { origin: pointInCanvas(event, svg.getBoundingClientRect(), canvas), base: structuredClone(clip.overlay) };
        svg.setPointerCapture(event.pointerId); paint();
      });
      svg.append(node);
    }
    if (draft) { const node = shapeNode(draft); node.classList.add("am-overlay-draft"); svg.append(node); }
  };
  const paint = () => {
    draw(); save.disabled = !draft; remove.disabled = !chosen;
    statusLine.textContent = chosen ? t("Выбрана пометка {id}", { id: chosen.id }) : draft ? t("Новая пометка — сохраните её") : "";
    drafts.set(project.id, { hash: model.model_hash, chosenId: chosen?.id || null, draft, mode: mode.value, color: color.value, width: Number(width.value) });
  };
  svg.addEventListener("pointerdown", (event) => {
    event.preventDefault(); svg.setPointerCapture(event.pointerId); start = pointInCanvas(event, svg.getBoundingClientRect(), canvas); points = [start]; chosen = null;
  });
  svg.addEventListener("pointermove", (event) => {
    const end = pointInCanvas(event, svg.getBoundingClientRect(), canvas);
    if (moving) {
      const dx = end[0] - moving.origin[0], dy = end[1] - moving.origin[1];
      const base = moving.base.geometry; const geometry = structuredClone(base);
      if (draft.type === "rect" || draft.type === "ellipse") { geometry.x = Math.max(0, Math.min(canvas.width - geometry.width, base.x + dx)); geometry.y = Math.max(0, Math.min(canvas.height - geometry.height, base.y + dy)); }
      else if (draft.type === "arrow") { for (const key of ["x1", "x2"]) geometry[key] = Math.max(0, Math.min(canvas.width, base[key] + dx)); for (const key of ["y1", "y2"]) geometry[key] = Math.max(0, Math.min(canvas.height, base[key] + dy)); }
      else geometry.points = base.points.map(([x,y]) => [Math.max(0, Math.min(canvas.width, x + dx)), Math.max(0, Math.min(canvas.height, y + dy))]);
      draft.geometry = geometry; paint(); return;
    }
    if (!start) return;
    if (mode.value === "stroke") points.push(end);
    draft = overlayFromDrag(mode.value, start, end, canvas, points); draft.color = color.value.toUpperCase(); draft.stroke_width = Number(width.value); paint();
  });
  svg.addEventListener("pointerup", (event) => { if (!start && !moving) return; svg.releasePointerCapture(event.pointerId); start = null; moving = null; });
  const save = el("button", "v2-primary", t("Сохранить пометку")); save.type = "button"; save.disabled = true;
  save.addEventListener("click", async () => {
    save.disabled = true; statusLine.textContent = t("Сохраняю…");
    const at = Number.isFinite(video?.currentTime) ? video.currentTime : 0;
    const duration = Math.max(.1, Math.min(3, (model.duration || 3) - at));
    const edit = chosen ? { op: "overlay-update", clip: chosen.id, overlay: draft } : { op: "overlay-add", overlay: draft, at, duration };
    const result = await postMontage(project.id, "edit", { expected_revision: snapshot.revision, expected_model_hash: model.model_hash, edit });
    statusLine.textContent = result.ok ? t("Пометка сохранена") : refusalText(result);
    if (result.ok) { drafts.delete(project.id); document.dispatchEvent(new CustomEvent("studio:refresh-snapshot", { detail: { projectId: project.id } })); await refreshMontage(); }
    else save.disabled = false;
  });
  const remove = el("button", "am-link-button", t("Удалить выбранную")); remove.type = "button"; remove.disabled = true;
  remove.addEventListener("click", async () => {
    if (!chosen) return; remove.disabled = true; statusLine.textContent = t("Удаляю…");
    const result = await postMontage(project.id, "edit", { expected_revision: snapshot.revision, expected_model_hash: model.model_hash, edit: { op: "delete", clip: chosen.id } });
    statusLine.textContent = result.ok ? t("Пометка удалена") : refusalText(result);
    if (result.ok) { drafts.delete(project.id); document.dispatchEvent(new CustomEvent("studio:refresh-snapshot", { detail: { projectId: project.id } })); await refreshMontage(); }
    else remove.disabled = false;
  });
  paint(); section.append(hint, tools, stage, save, remove, statusLine); return section;
}
