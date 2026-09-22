// Тексты запросов агенту (спецификация §6): всё, что стоит денег или
// требует работы агента, уходит в чат готовым промптом, в котором уже
// названы проект, сцена, версия промпта и выбранный вариант. Чистые
// функции: возвращают `{title, prompt, attachmentHint}` и ничего не
// открывают — диалог показывает `ui/chat-prompt-dialog.js`.

const KIND_WORDS = Object.freeze({
  character: "персонажа",
  location: "локацию",
  product: "реквизит",
  style: "стиль",
  other: "что-то своё, без категории",
  video: "видеореференс",
});

const SLOT_WORDS = Object.freeze({
  first: "первый кадр",
  last: "последний кадр",
  video: "клип",
  image: "изображение",
});

/** «проект «Название» (project_id «id», snapshot revision 62)» */
export function projectRef(project, revision) {
  const parts = [`project_id «${project?.id ?? "—"}»`];
  if (Number.isFinite(revision)) parts.push(`snapshot revision ${revision}`);
  return `проект «${project?.title || project?.id || "—"}» (${parts.join(", ")})`;
}

/** «сцена 2 «Скептик» (scene_id «skeptic-online»)» */
export function sceneRef(project, sceneId) {
  const scenes = [...(project?.scenes || [])].sort((left, right) => (left?.order || 0) - (right?.order || 0));
  const index = scenes.findIndex((scene) => scene?.scene_id === sceneId);
  if (index < 0) return "";
  const scene = scenes[index];
  const title = scene.title ? ` «${scene.title}»` : "";
  return `сцена ${index + 1}${title} (scene_id «${sceneId}»)`;
}

function opening(project, sceneId, revision) {
  const scene = sceneId ? sceneRef(project, sceneId) : "";
  return `Открой ${projectRef(project, revision)}${scene ? `, ${scene}` : ""}.`;
}

function promptRef(promptVersion) {
  if (!promptVersion) return "версии промпта нет";
  return `версия промпта version_id «${promptVersion.version_id}»`;
}

/**
 * «＋» в группе полки референсов.
 * @param {string} kind character|location|product|style|other|video
 * @param {object} project `snapshot.active_project`
 * @param {number} [revision]
 * @param {{sceneId?: string}} [options] для референса «только этой сцены»
 */
export function addReference(kind, project, revision, { sceneId } = {}) {
  const known = Object.prototype.hasOwnProperty.call(KIND_WORDS, kind);
  const word = known ? KIND_WORDS[kind] : "референс";
  const video = kind === "video";
  const scoped = sceneId ? " только этой сцены" : video ? " сцены" : " проекта";
  return {
    title: `Добавить ${word}`,
    prompt: `${opening(project, sceneId, revision)} Я хочу добавить ${word} в референсы${scoped}. `
      + `Спроси, прикреплю ли я готовый файл или нужно сгенерировать. Если файл уже приложен, считай это выбором upload: `
      + `проверь вложение, найди подходящий существующий placeholder и обнови его, не создавая дубликат; повторно генерировать приложенное не предлагай. `
      + `${video
        ? "Видеореференс бывает только из файла; спроси назначение: reference, motion, continue или edit. "
        : known ? `Вид референса — kind «${kind}». ` : "Спроси, какой это вид референса. "}`
      + `Если выбран generate, создай референс с source=generate и его промпт, но провайдера не вызывай: внешний запуск разрешён только когда текущей стадией станет image_results. `
      + `После записи назови reference_id и следующий допустимый шаг.`,
    attachmentHint: video
      ? "Прикрепите видео к сообщению в чате. Вложение не входит в скопированный текст."
      : "Если файл уже есть, прикрепите изображение к сообщению в чате. Вложение не входит в скопированный текст.",
  };
}

/**
 * «＋ Ещё вариант» в просмотрщике.
 * @param {{project: object, revision?: number, sceneId?: string, referenceId?: string,
 *          slot?: string, promptVersion?: object, selectedVariant?: object}} context
 */
export function moreVariants({ project, revision, sceneId, referenceId, slot, promptVersion, selectedVariant } = {}) {
  const what = referenceId ? `референс «${referenceId}»` : SLOT_WORDS[slot] || "результат";
  const chosen = selectedVariant
    ? `Сейчас выбран вариант result_id «${selectedVariant.result_id}», version_id «${selectedVariant.version_id}».`
    : "Выбранного варианта пока нет.";
  return {
    title: `Ещё вариант: ${what}`,
    prompt: `${opening(project, sceneId, revision)} Нужен ещё один вариант: ${what}. Делай по ${promptRef(promptVersion)}, текст не меняя. `
      + `${chosen} Перед запуском покажи, что именно и каким провайдером собираешься сгенерировать, и дождись моего подтверждения — это платное действие. `
      + `После генерации добавь новую версию результата в ту же группу и сообщи её version_id.`,
  };
}

/**
 * «Загрузить свой файл» вместо генерации.
 * @param {{project: object, revision?: number, sceneId?: string, slot?: string}} context
 */
export function uploadFrame({ project, revision, sceneId, slot } = {}) {
  const what = SLOT_WORDS[slot] || "кадр";
  return {
    title: `Загрузить ${what}`,
    prompt: `${opening(project, sceneId, revision)} Я прикреплю готовый файл на ${what}. `
      + `Сначала проверь вложение, зарегистрируй его как asset и добавь версию результата в группу этого слота штатной командой Creator Studio. `
      + `Ничего не генерируй и не предлагай генерацию: файл уже есть. После записи назови version_id и что стало выбранным.`,
    attachmentHint: "Прикрепите файл к сообщению в чате. Вложение не входит в скопированный текст.",
  };
}

/**
 * «Изменить промпт → чат».
 * @param {{project: object, revision?: number, sceneId?: string, referenceId?: string,
 *          promptVersion?: object, what?: string}} context
 */
export function editPrompt({ project, revision, sceneId, referenceId, promptVersion, what } = {}) {
  const subject = what || (referenceId ? `референса «${referenceId}»` : "этой сцены");
  return {
    title: "Изменить промпт",
    prompt: `${opening(project, sceneId, revision)} Нужно изменить промпт ${subject}. Текущая ${promptRef(promptVersion)}. `
      + `Спроси, что именно поправить, покажи новый текст целиком и после моего подтверждения добавь новую версию промпта с понятной причиной. `
      + `Генерацию не запускай: сначала я посмотрю текст.`,
  };
}

/**
 * Включить или выключить общий референс в одной сцене (команда
 * `scene reference`, в дашборде остаётся через чат — спецификация §4).
 * @param {{project: object, revision?: number, sceneId?: string,
 *          reference?: object, include?: boolean}} context
 */
export function toggleSceneReference({ project, revision, sceneId, reference, include = true } = {}) {
  const name = reference?.label || reference?.reference_id || "референс";
  const verb = include ? "включи" : "выключи";
  return {
    title: include ? `Добавить «${name}» в кадр` : `Убрать «${name}» из кадра`,
    prompt: `${opening(project, sceneId, revision)} ${verb[0].toUpperCase()}${verb.slice(1)} референс «${name}» `
      + `(reference_id «${reference?.reference_id ?? "—"}») в этой сцене штатной командой Creator Studio. `
      + `Это одна галочка: других сцен и промптов не трогай, ничего не генерируй. После записи покажи, какие референсы теперь в этой сцене.`,
  };
}
