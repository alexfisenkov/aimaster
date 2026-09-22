// Модель вариантов и версий поверх готового snapshot (спецификация
// перестройки дашборда §5). Только чистые функции: ни `document`, ни
// `fetch`, ни импортов из v1 — этот модуль импортируют тесты напрямую.
//
// Словарь: «группа» — все записи с одним `result_id` (или `prompt_id`);
// «версия» — одна запись группы со своим `version_id`. Порядок внутри
// группы задаёт цепочка `parent_version_id`, а не порядок в массиве.

/** Ссылка сцены на выбранный результат — по слоту. */
const SCENE_SLOT_LINKS = Object.freeze({
  first: "first_frame_result_id",
  last: "last_frame_result_id",
  video: "video_result_id",
  image: "image_result_id",
});

/**
 * Упорядочить записи одной группы по цепочке `parent_version_id`.
 *
 * @param {object[]} records записи одной группы (порядок массива — «порядок появления»)
 * @param {string} [idField="version_id"] поле идентификатора версии
 * @returns {object[]} корни (запись без `parent_version_id`) в порядке
 *   появления, за каждым — его потомки вглубь; затем сироты (родитель
 *   назван, но такой записи в группе нет) и разорванные циклы — тоже в
 *   порядке появления. Возвращаются те же объекты, без копирования.
 */
export function orderByParent(records, idField = "version_id") {
  const list = (Array.isArray(records) ? records : []).filter(
    (item) => item && typeof item === "object",
  );
  const known = new Set();
  for (const item of list) {
    const id = item[idField];
    if (typeof id === "string" && id) known.add(id);
  }
  const childrenOf = new Map();
  for (const item of list) {
    const parent = item.parent_version_id;
    if (typeof parent !== "string" || !parent) continue;
    if (!known.has(parent) || parent === item[idField]) continue;
    if (!childrenOf.has(parent)) childrenOf.set(parent, []);
    childrenOf.get(parent).push(item);
  }
  const seen = new Set();
  const ordered = [];
  const walk = (item) => {
    if (seen.has(item)) return;
    seen.add(item);
    ordered.push(item);
    for (const child of childrenOf.get(item[idField]) || []) walk(child);
  };
  for (const item of list) {
    const parent = item.parent_version_id;
    if (typeof parent !== "string" || !parent) walk(item);
  }
  for (const item of list) walk(item);
  return ordered;
}

function group(records, key, idField) {
  const groups = new Map();
  for (const item of Array.isArray(records) ? records : []) {
    if (!item || typeof item !== "object") continue;
    const id = item[key];
    if (typeof id !== "string" || !id) continue;
    if (!groups.has(id)) groups.set(id, []);
    groups.get(id).push(item);
  }
  for (const [id, items] of groups) groups.set(id, orderByParent(items, idField));
  return groups;
}

/**
 * @param {object[]} records например `active_project.image_results`
 * @returns {Map<string, object[]>} `result_id` → его версии по порядку цепочки
 */
export function resultGroups(records) {
  return group(records, "result_id", "version_id");
}

/**
 * @param {object[]} records например `active_project.image_prompts`
 * @returns {Map<string, object[]>} `prompt_id` → его версии по порядку цепочки
 */
export function promptGroups(records) {
  return group(records, "prompt_id", "version_id");
}

function findVersion(records, versionId) {
  if (typeof versionId !== "string" || !versionId) return null;
  const matches = (Array.isArray(records) ? records : []).filter(
    (item) => item && (item.version_id === versionId || item.result_id === versionId),
  );
  return matches.length === 1 ? matches[0] : null;
}

/**
 * Какая версия результата выбрана сейчас. «Выбран» — это тот
 * `version_id`, на который указывает ссылка владельца: `scene.links`,
 * `oneshot.links`, `reference.links` или `audio_layers[].links`.
 * Позиция (`positions[]`) хранит только группу и потому выбора не
 * задаёт: пока ссылки нет, выбора нет.
 *
 * @param {object} project `snapshot.active_project`
 * @param {{sceneId?: string, slot?: "first"|"last"|"video"|"image",
 *          referenceId?: string, layer?: string}} target
 * @returns {object|null} запись версии результата или `null`
 */
export function selectedResultVersion(project, target = {}) {
  if (!project || typeof project !== "object") return null;
  const { sceneId, slot, referenceId, layer } = target;
  if (referenceId) {
    const reference = (project.references || []).find((item) => item?.reference_id === referenceId);
    return findVersion(project.image_results, reference?.links?.image_result_id);
  }
  if (layer) {
    const owner = (project.audio_layers || []).find((item) => item?.layer === layer);
    return findVersion(project.audio_results, owner?.links?.audio_result_id);
  }
  const linkKey = SCENE_SLOT_LINKS[slot] || SCENE_SLOT_LINKS.image;
  const collection = slot === "video" ? project.video_results : project.image_results;
  if (!sceneId || sceneId === "oneshot") {
    return findVersion(project.video_results, project.oneshot?.links?.video_result_id);
  }
  const scene = (project.scenes || []).find((item) => item?.scene_id === sceneId);
  return findVersion(collection, scene?.links?.[linkKey]);
}

/**
 * Пометка версии для плёнки вариантов. Порядок проверок важен: убранное
 * из работы и скрытое перекрывают решение по нему.
 *
 * @param {object} version запись результата
 * @returns {"retired"|"hidden"|"rejected"|"selected"|"new"}
 */
export function variantState(version) {
  if (!version || typeof version !== "object") return "new";
  if (version.retired === true) return "retired";
  if (version.hidden === true) return "hidden";
  if (version.decision === "rejected") return "rejected";
  if (version.decision === "approved") return "selected";
  return "new";
}

/**
 * Какие варианты сделаны по конкретной версии промпта.
 *
 * Внимание: текущая проекция (`projection._RESULT_KEYS`) такой связи не
 * отдаёт вовсе — у результата есть только `result_id`, `version_id` и
 * `parent_version_id` (цепочка результат→результат, к промпту отношения
 * не имеющая). Поэтому здесь читаются только явные ссылки на промпт, а
 * на живых данных функция честно возвращает пустой список: просмотрщик в
 * этом случае показывает версии промпта без строки «по нему варианты»
 * (спецификация §5).
 *
 * @param {string} promptVersionId `version_id` версии промпта
 * @param {object[]} results записи результатов
 * @returns {object[]} версии результатов, явно связанные с этой версией промпта
 */
export function versionsMadeBy(promptVersionId, results) {
  if (typeof promptVersionId !== "string" || !promptVersionId) return [];
  return (Array.isArray(results) ? results : []).filter((item) => {
    if (!item || typeof item !== "object") return false;
    const links = item.links && typeof item.links === "object" ? item.links : item;
    const list = links.prompt_version_ids;
    if (Array.isArray(list) && list.includes(promptVersionId)) return true;
    return Object.entries(links).some(
      ([key, value]) => key.endsWith("prompt_version_id") && value === promptVersionId,
    );
  });
}
