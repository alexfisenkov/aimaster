// Длина ролика словами — одна на шапку («3,5 с») и пилюлю превью
// («00:03,5»), чтобы они не расходились: у короткого ролика (до 10 с)
// половина секунды заметна, поэтому одна цифра после запятой, если она не
// ноль; дальше — целые секунды. Чистые функции (length-text.test.mjs).

function tenthsOf(seconds) {
  return Math.round(Math.max(0, seconds) * 10);
}

const pad = (value) => String(value).padStart(2, "0");

/** 3.5 → «00:03,5», 3 → «00:03», 35.4 → «00:35», 65 → «01:05»; не число — «». */
export function lengthClock(seconds) {
  if (!Number.isFinite(seconds)) return "";
  const tenths = tenthsOf(seconds);
  if (tenths < 100 && tenths % 10) return `00:0${Math.floor(tenths / 10)},${tenths % 10}`;
  const total = Math.round(Math.max(0, seconds));
  return `${pad(Math.floor(total / 60))}:${pad(total % 60)}`;
}

/** 3.5 → «3,5 с», 3 → «3 с», 35.4 → «35 с»; не число — «». */
export function lengthWords(seconds) {
  if (!Number.isFinite(seconds)) return "";
  const tenths = tenthsOf(seconds);
  if (tenths < 100 && tenths % 10) return `${Math.floor(tenths / 10)},${tenths % 10} с`;
  return `${Math.round(Math.max(0, seconds))} с`;
}

/** Длина по плану сцен: конец последней сцены в секундах; сцен нет — null. */
export function sceneSeconds(project) {
  const ends = (project?.scenes || []).map((scene) => scene?.end_ms).filter(Number.isFinite);
  return ends.length ? Math.max(...ends) / 1000 : null;
}
