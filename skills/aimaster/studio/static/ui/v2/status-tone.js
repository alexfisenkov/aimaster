// Цвет статуса места (хэндофф 2026-09-23, «Поведение и состояние»): у
// плитки, слота, клипа и слоя одна точка, и её цвет читается по тем же
// правилам, что и слова `variantStatus`. Чистые функции, без DOM: цвет
// ставит CSS по `data-tone`.
//
//   none — вариантов нет («не задан»), серая точка;
//   warn — варианты есть, ничего не выбрано («выберите из N»);
//   ok   — выбран вариант («выбран K из N»);
//   own  — свой файл владельца («ваш файл»).

/**
 * @param {{total?: number, selected?: object|null}} counts из `variantCounts`
 * @param {{source?: string, hasAsset?: boolean}} [own] «своё» вместо генерации
 * @returns {"none"|"warn"|"ok"|"own"}
 */
export function statusTone({ total = 0, selected = null } = {}, { source, hasAsset } = {}) {
  if (source === "upload") return hasAsset ? "own" : "none";
  if (selected) return "ok";
  if (total > 0) return "warn";
  return "none";
}

/**
 * Бейдж строки сцены на «Кадрах»: готовы ли все запланированные кадры.
 * @param {{total: number, selected: object|null}[]} slots счёт по каждому слоту
 * @returns {{text: string, tone: "ok"|"warn"}|null} `null` — кадров не запланировано
 */
export function framesBadge(slots) {
  const list = Array.isArray(slots) ? slots : [];
  if (!list.length) return null;
  return list.every((counts) => Boolean(counts?.selected))
    ? { text: "кадры готовы", tone: "ok" }
    : { text: "нужно выбрать", tone: "warn" };
}

/**
 * Бейдж строки сцены на «Видео».
 * @param {{total: number, selected: object|null}} clip `clipStatus(project, scene)`
 * @returns {{text: string, tone: "ok"|"warn"|"none"}}
 */
export function clipBadge({ total = 0, selected = null } = {}) {
  if (selected) return { text: "клип выбран", tone: "ok" };
  if (total > 0) return { text: "нужно выбрать", tone: "warn" };
  return { text: "клипа нет", tone: "none" };
}
