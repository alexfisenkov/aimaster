// Экран «Сборка» монтажа — чистые правила без DOM (их проверяет
// montage-model.test.mjs): строки версий, что показать и что спрятать,
// плашки, сторона кадра, длина. Данные — снимок проекта (`project.montage`:
// версии с `asset_url`, текущая, `canvas`) и ответы
// `GET /api/projects/<id>/montage` (движок, стол, файл, `index_key`) и
// `…/montage/model` (схема, несобранные правки, ошибки движка).

const WHO = Object.freeze({ owner: "Вы", agent: "Агент", autopilot: "Автопилот" });

/** Монтаж — у видео и смешанных проектов; фото собирается картинкой. */
export function montageApplies(project) {
  return project?.type === "video" || project?.type === "mixed";
}

/** Монтажная раскладка экрана: монтаж уже есть — или итога ещё нет. Старый
 * итог, собранный до монтажа (`assembly set`), показывается как раньше. */
export function montageScreen(project) {
  if (!montageApplies(project)) return false;
  return Boolean(project?.montage) || typeof project?.assembly?.asset_url !== "string";
}

/** «v003» → «v3». */
export function versionLabel(id) {
  const match = /^v0*(\d+)$/.exec(typeof id === "string" ? id : "");
  return match ? `v${match[1]}` : String(id || "");
}

/** «28.09, 14:05» по времени компьютера; не дата — пустая строка. */
export function whenText(iso) {
  const date = new Date(typeof iso === "string" ? iso : Number.NaN);
  if (Number.isNaN(date.getTime())) return "";
  const two = (value) => String(value).padStart(2, "0");
  return `${two(date.getDate())}.${two(date.getMonth() + 1)}, ${two(date.getHours())}:${two(date.getMinutes())}`;
}

/** Версии новыми сверху: номер, кто собрал, когда, что изменилось, текущая ли. */
export function versionRows(project) {
  const montage = project?.montage;
  const list = Array.isArray(montage?.versions) ? montage.versions : [];
  return list.map((item) => ({
    id: item.id,
    label: versionLabel(item.id),
    who: WHO[item.by] || WHO.agent,
    when: whenText(item.created_at),
    summary: typeof item.summary === "string" && item.summary.trim() ? item.summary.trim() : "без описания",
    current: item.id === montage.current_version,
    assetUrl: typeof item.asset_url === "string" && item.asset_url.startsWith("/assets/") ? item.asset_url : null,
  })).reverse();
}

/** «Скачать»: тот же файл с `download=1` (в Mini App у адреса уже есть билет `?e=…&t=…`). */
export function downloadHref(url) {
  if (typeof url !== "string" || !url.startsWith("/assets/")) return null;
  return `${url}${url.includes("?") ? "&" : "?"}download=1`;
}

function engineState(status) {
  const state = status?.engine?.state;
  return state === "installed" || state === "missing" ? state : "unknown";
}

/**
 * Что можно делать на экране. Стол и «Показать в папке» — только на компьютере
 * (не телефон, не Telegram); после принятия ролика монтаж не меняется.
 *
 * `deskLinkMissing`: сервер прислал `desk: {"state": "open"}` без `url`
 * (`montage/service_screen.py:desk_view` — адрес стола не 127.0.0.1/localhost/
 * [::1], запись `.desk.json` могла устареть или её подменили). Стол открыт,
 * но перейти по нему нельзя; отдельный флаг — чтобы это не путалось с
 * обычным «закрыт» (`deskUrl` в обоих случаях `null`).
 */
export function screenFlags({ status = null, finished = false, phone = false, telegram = false } = {}) {
  const engine = engineState(status);
  const local = !phone && !telegram;
  const deskPossible = !finished && status?.exists === true && engine === "installed";
  const state = status?.desk?.state;
  const desk = local && deskPossible ? (state === "open" || state === "busy" ? state : "closed") : "hidden";
  const deskUrl = desk === "open" && typeof status?.desk?.url === "string" ? status.desk.url : null;
  return {
    engine,
    desk,
    deskUrl,
    deskLinkMissing: desk === "open" && deskUrl === null,
    deskHint: !local && deskPossible,
    reveal: local && status?.reveal === true && typeof status?.file?.shown === "string",
    restore: !finished,
    build: !finished,
  };
}

/** Три исхода `stale_clips` (`studio/montage/stale.py`): `reason: null` —
 * обновит `montage draft --refresh`; `reason: "нужен --rebuild"` (`cause`
 * заполнен) — структурная перемена, точечно не поправить; `reason: "нет
 * принятого"` — заменить нечем, менять решение — на человеке. Одна плашка
 * на исход, а не одна на всё: текст должен сразу сказать, что предстоит. */
function staleNotices(clips) {
  const refreshable = clips.filter((clip) => !clip.reason);
  const structural = clips.filter((clip) => clip.cause);
  const unaccepted = clips.filter((clip) => clip.reason === "нет принятого");
  const list = [];
  if (refreshable.length) {
    list.push({ key: "stale", tone: "warn", action: "refresh",
      text: `После черновика в проекте выбрали другие клипы или звук — устарело: ${refreshable.length}.` });
  }
  if (structural.length) {
    list.push({ key: "stale-rebuild", tone: "warn", action: "refresh",
      text: "Проект изменился (сцены или режим показа) — нужен новый черновик монтажа." });
  }
  if (unaccepted.length) {
    list.push({ key: "stale-unaccepted", tone: "warn", action: "refresh",
      text: `Нет принятого результата — таких клипов в монтаже: ${unaccepted.length}.` });
  }
  return list;
}

/** Плашки над экраном — тексты сервера (по-русски, без путей) и свои. */
export function notices({ status = null, model = null, feedError = null } = {}) {
  const list = [];
  if (feedError) list.push({ key: "feed", tone: "error", text: feedError });
  if (!status || status.applicable === false) return list;
  const fresh = Boolean(model && model.index_key && model.index_key === status.index_key);
  // status.unrendered_changes — из дешёвого опроса, пересчитывается на
  // каждый тик; модель может отстать от текущей версии (сборка не трогает
  // index.html, index_key не меняется — b4-review/stale-after-render.mjs),
  // поэтому её unrendered_changes доверяем только когда у статуса вообще
  // нет ответа на этот вопрос (null — нет попадания в кэш модели).
  const unrendered = typeof status.unrendered_changes === "boolean"
    ? status.unrendered_changes
    : (fresh ? model.unrendered_changes : null);
  if (status.current_version && unrendered === true) {
    list.push({ key: "unrendered", tone: "warn", action: "build",
      text: "Есть несобранные правки: монтаж менялся после последней сборки." });
  }
  if (status.current_version && status.file && !status.file.shown) {
    list.push({ key: "file", tone: "error", action: "build",
      text: `Файла ролика ${versionLabel(status.current_version)} нет на месте — соберите ролик заново.` });
  }
  for (const key of ["model_error", "stale_error"]) {
    if (fresh && typeof model[key] === "string" && model[key]) list.push({ key, tone: "error", text: model[key] });
  }
  if (fresh && Array.isArray(model.stale_clips) && model.stale_clips.length) {
    list.push(...staleNotices(model.stale_clips));
  }
  for (const key of ["note", "forgotten"]) {
    const text = status.desk?.[key];
    if (typeof text === "string" && text) list.push({ key: `desk-${key}`, tone: "info", text });
  }
  if (status.desk?.state === "open" && status.desk.telemetry_off === false) {
    list.push({ key: "telemetry", tone: "info",
      text: "Монтажный стол открыт без отключения аналитики Studio: его адрес не распознан." });
  }
  return list;
}

/** Сторона кадра превью: вертикальный ролик не сжимается в полосу 16:9. */
export function orientation(canvas) {
  const width = Number(canvas?.width);
  const height = Number(canvas?.height);
  if (!(width > 0 && height > 0)) return "landscape";
  if (height > width) return "portrait";
  return width > height ? "landscape" : "square";
}

function mmss(seconds) {
  const total = Math.max(0, Math.round(seconds));
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

/** Длина текущей версии: из схемы, когда несобранных правок нет; иначе — по сценам.
 * «Несобранных правок нет» решаем как в `notices` — по дешёвому
 * `status.unrendered_changes`, когда он известен (модель могла отстать от
 * версии: сборка не трогает index.html), иначе по модели. `model.duration`
 * всё равно берём только у модели с тем же `index_key` — она зависит от
 * содержимого index.html, а не от того, какая версия текущая. */
export function durationText({ status = null, model = null, project = null } = {}) {
  const fresh = Boolean(model && status && model.index_key === status.index_key);
  const unrendered = typeof status?.unrendered_changes === "boolean"
    ? status.unrendered_changes
    : (fresh ? model.unrendered_changes : null);
  const settled = fresh && unrendered === false;
  if (settled && Number(model.duration) > 0) return mmss(Number(model.duration));
  const ends = (project?.scenes || []).map((scene) => scene?.end_ms).filter(Number.isFinite);
  return ends.length ? mmss(Math.max(...ends) / 1000) : "";
}
