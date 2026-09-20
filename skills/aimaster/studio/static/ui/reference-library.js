// Pure presentation model for the project-level reference library on step 2.
// Local (one-scene) references belong to task 37's scene cards and never leak
// into this surface.

export const REFERENCE_GROUPS = Object.freeze([
  Object.freeze({ kind: "character", title: "Персонажи", subtitle: "постоянные лица проекта, у каждого может быть голос", addLabel: "+ Добавить персонажа", requestLabel: "персонажа" }),
  Object.freeze({ kind: "product", title: "Продукты", subtitle: "предметы, которые должны выглядеть одинаково", addLabel: "+ Добавить продукт или предмет", requestLabel: "продукт или предмет" }),
  Object.freeze({ kind: "location", title: "Локации", subtitle: "места, в которых идёт действие", addLabel: "+ Добавить локацию", requestLabel: "локацию" }),
  Object.freeze({ kind: "style", title: "Стиль", subtitle: "общая картинка: свет, цвет, оптика", addLabel: "+ Добавить стиль", requestLabel: "стиль" }),
]);

const SOURCE_LABELS = Object.freeze({
  upload: "Загружу сам",
  generate: "Сгенерировать на шаге изображений",
});

export function resolveReferencePrompt(project, reference) {
  const versionId = reference?.links?.image_prompt_version_id;
  if (typeof versionId !== "string" || !versionId) return null;
  const matches = (Array.isArray(project?.image_prompts) ? project.image_prompts : []).filter(
    (prompt) => prompt?.version_id === versionId,
  );
  return matches.length === 1 ? matches[0] : null;
}

function membershipCounts(scenes, referenceId) {
  const list = Array.isArray(scenes) ? scenes : [];
  return {
    includedSceneCount: list.filter(
      (scene) => Array.isArray(scene?.links?.reference_ids) && scene.links.reference_ids.includes(referenceId),
    ).length,
    sceneCount: list.length,
  };
}

function assetCaption(reference) {
  if (reference?.source === "generate") return "будет сгенерирован";
  return reference?.has_asset === true ? "ваш файл" : "нужен файл";
}

function referenceItem(project, reference, { readOnly, canEditReference, canEditPrompt, canRefreshPrompt, actions }) {
  if (!reference || reference.local === true || !SOURCE_LABELS[reference.source]) return null;
  if (!REFERENCE_GROUPS.some((group) => group.kind === reference.kind)) return null;
  const prompt = resolveReferencePrompt(project, reference);
  const voice = reference.kind === "character"
    ? {
        enabled: reference.voice?.enabled === true,
        tag: typeof reference.voice?.tag === "string" ? reference.voice.tag : "",
        hasAsset: typeof reference.voice?.asset_url === "string" && Boolean(reference.voice.asset_url),
      }
    : null;
  return {
    referenceId: reference.reference_id,
    kind: reference.kind,
    tag: reference.tag,
    name: typeof reference.label === "string" ? reference.label : "",
    source: reference.source,
    sourceLabel: SOURCE_LABELS[reference.source],
    hasAsset: reference.has_asset === true,
    assetUrl: typeof reference.asset_url === "string" ? reference.asset_url : null,
    assetCaption: assetCaption(reference),
    voice,
    prompt,
    canEditReference,
    canEditPrompt,
    canRefreshPrompt,
    actions,
    readOnly,
    ...membershipCounts(project.scenes, reference.reference_id),
  };
}

export function referenceGroups(
  snapshot,
  {
    readOnly = false,
    canEditReference = !readOnly,
    canEditPrompt = !readOnly,
    canRefreshPrompt = !readOnly,
    actions = [],
  } = {},
) {
  const project = snapshot?.active_project;
  const references = Array.isArray(project?.references) ? project.references : [];
  return REFERENCE_GROUPS.map((group) => ({
    ...group,
    items: references
      .filter((reference) => reference?.kind === group.kind)
      .map((reference) => referenceItem(project, reference, {
        readOnly,
        canEditReference,
        canEditPrompt,
        canRefreshPrompt,
        actions,
      }))
      .filter(Boolean),
  }));
}
