// Модель экрана «Звук» (спецификация §3.4): четыре слоя, у каждого своя
// плитка. Порядок здесь человеческий — голос, музыка, эффекты,
// атмосфера, — а не алфавитный порядок сервера (`AUDIO_LAYERS`).
// Чистые функции, без DOM.

import { variantCounts, variantStatus } from "./counts.js";
import { statusTone } from "./status-tone.js";

export const AUDIO_LAYERS = Object.freeze([
  Object.freeze({ layer: "voice", name: "Голос", hint: "реплики героев" }),
  Object.freeze({ layer: "music", name: "Музыка", hint: "подложка на весь ролик" }),
  Object.freeze({ layer: "fx", name: "Эффекты", hint: "звуки в кадре" }),
  Object.freeze({ layer: "atmos", name: "Атмосфера", hint: "фон и пространство" }),
]);

/**
 * Четыре плитки слоёв звука.
 *
 * @param {object} project `snapshot.active_project`
 * @returns {{layer: string, name: string, hint: string, total: number,
 *            index: number, selected: object|null, status: string,
 *            tone: "ok"|"warn"|"none", wave: number[], hasPrompt: boolean}[]}
 */
export function audioTiles(project) {
  const layers = project?.audio_layers || [];
  return AUDIO_LAYERS.map((meta, order) => {
    const counts = variantCounts(project, { layer: meta.layer });
    const owner = layers.find((item) => item?.layer === meta.layer);
    return {
      ...meta,
      total: counts.total,
      index: counts.index,
      selected: counts.selected,
      // Пустой слой ничего не держит: аудио-позиция становится
      // обязательной, только когда у неё появился результат
      // (`domain_positions._position_required`). Так и подписываем —
      // человек должен видеть, что звук можно просто пропустить.
      status: counts.total === 0 && !counts.selected ? "не нужен — можно пропустить" : variantStatus(counts),
      tone: statusTone(counts),
      wave: waveHeights(order, counts.total > 0 || Boolean(counts.selected)),
      hasPrompt: typeof owner?.links?.audio_prompt_version_id === "string"
        && Boolean(owner.links.audio_prompt_version_id),
    };
  });
}

/**
 * Высоты столбиков волны на плитке слоя — рисунок, а не звук: настоящей
 * огибающей у снимка нет. Детерминированно от номера слоя, чтобы плитка
 * не «дышала» при каждой перерисовке. Пустой слой — ровная низкая черта.
 *
 * @param {number} seed номер слоя
 * @param {boolean} filled есть ли у слоя варианты
 * @param {number} [count] сколько столбиков
 * @returns {number[]} доли высоты 0..1
 */
export function waveHeights(seed, filled, count = 28) {
  return Array.from({ length: count }, (_, index) => (filled
    ? 0.18 + Math.round(70 * Math.abs(Math.sin(index * 0.9 + seed) * Math.cos(index * 0.31))) / 100
    : 0.08));
}
