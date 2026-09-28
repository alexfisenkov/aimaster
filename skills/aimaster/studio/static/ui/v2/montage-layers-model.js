// Схема монтажа — чистые правила без DOM (montage-layers-model.test.mjs):
// шесть дорожек в постоянном порядке и блоки клипов по времени. Данные —
// `GET /api/projects/<id>/montage/model` → `layers` (время — секунды
// готового ролика, как в `montage status`). Подписи — как в строках
// `montage diff`: «0:03.3», «2,5 с».

const MIN_LEN = 1.2; // % ширины дорожки: короткий клип всё равно можно нажать

const round2 = (value) => Math.round(value * 100) / 100;

/** 3.25 → «0:03.3». */
export function fmtTime(seconds) {
  const tenths = Math.round(Math.max(0, Number(seconds) || 0) * 10);
  const minutes = Math.floor(tenths / 600);
  const rest = (tenths - minutes * 600) / 10;
  return `${minutes}:${rest.toFixed(1).padStart(4, "0")}`;
}

/** 2.5 → «2,5 с». */
export function fmtLen(seconds) {
  const tenths = Math.round(Math.max(0, Number(seconds) || 0) * 10);
  return `${(tenths / 10).toFixed(1).replace(".", ",")} с`;
}

/** Громкость в процентах; нет значения — как записано, 100 %. */
export function volumeText(volume) {
  return `${Math.round((Number.isFinite(volume) ? volume : 1) * 100)} %`;
}

/** {scene_id: {number, text: "сцена 2 «Скептик»"}} — по порядку сцен. */
export function sceneNames(project) {
  const scenes = (project?.scenes || []).filter((scene) => scene?.scene_id)
    .sort((left, right) => (left.order || 0) - (right.order || 0));
  return Object.fromEntries(scenes.map((scene, index) => [scene.scene_id,
    { number: index + 1, text: `сцена ${index + 1} «${scene.title || scene.scene_id}»` }]));
}

/** Что показать по нажатию: чей клип, где он в ролике, какой кусок исходника. */
export function clipDetail(clip, layer, label, names = {}) {
  const span = `${fmtTime(clip.start)}–${fmtTime(clip.start + clip.duration)} ролика`;
  if (layer === "titles") return `Титр «${clip.text || clip.id}» · ${span}`;
  const who = layer === "video" && names[clip.scene_id] ? `Клип: ${names[clip.scene_id].text}` : label;
  const parts = [who, span, `из исходника с ${fmtTime(clip.media_start)}, ${fmtLen(clip.duration)}`];
  if (layer !== "video" || Number.isFinite(clip.volume)) parts.push(`громкость ${volumeText(clip.volume)}`);
  return parts.join(" · ");
}

function blockText(layer, clip, names) {
  if (layer === "titles") return clip.text || "титр";
  if (layer === "video" && names[clip.scene_id]) return String(names[clip.scene_id].number);
  return "";
}

/** Дорожки и блоки: `at`/`len` — проценты ширины дорожки. */
export function layerRows(model, project) {
  const layers = Array.isArray(model?.layers) ? model.layers : [];
  const ends = layers.flatMap((layer) => (layer.clips || []).map((clip) => clip.start + clip.duration));
  const duration = Number(model?.duration) > 0 ? Number(model.duration) : Math.max(0, ...ends);
  const names = sceneNames(project);
  return layers.map((layer) => ({
    layer: layer.layer,
    label: layer.label,
    blocks: (layer.clips || []).map((clip) => {
      const at = duration > 0 ? Math.min(Math.max((clip.start / duration) * 100, 0), 100 - MIN_LEN) : 0;
      const len = duration > 0 ? Math.max(MIN_LEN, Math.min(100 - at, (clip.duration / duration) * 100)) : MIN_LEN;
      return { id: clip.id, at: round2(at), len: round2(len), text: blockText(layer.layer, clip, names),
        detail: clipDetail(clip, layer.layer, layer.label, names) };
    }),
  }));
}
