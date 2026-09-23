// Телефон или нет — одно место на всю v2. Брейкпойнт тот же, что в CSS:
// `@media (max-width: 759px)`. Раскладку делает CSS; здесь только то,
// что CSS не умеет, — например, открыть шторку вместо выпадающего меню.

export const PHONE_QUERY = "(max-width: 759px)";

function query() {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia(PHONE_QUERY)
    : null;
}

/** Узкий экран (< 760px)? Без `matchMedia` (тесты, старый движок) — нет. */
export function isPhone() {
  return query()?.matches === true;
}

/**
 * Позвать `callback(isPhone)` при переходе через брейкпойнт.
 * @param {(phone: boolean) => void} callback
 * @returns {() => void} отписка
 */
export function onViewportChange(callback) {
  const list = query();
  if (!list || typeof callback !== "function") return () => {};
  const listener = (event) => callback(event.matches === true);
  list.addEventListener("change", listener);
  return () => list.removeEventListener("change", listener);
}
