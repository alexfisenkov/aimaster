// Тост: короткая строка снизу по центру на 2,6 с (хэндофф 2026-09-23,
// «Поведение и состояние»). Один на страницу: новый текст заменяет
// старый и продлевает показ. `role="status"` — экранный диктор прочтёт.

const SHOW_MS = 2600;

let node = null;
let timer = null;

function ensureNode() {
  if (node?.isConnected) return node;
  node = document.createElement("div");
  node.className = "v2-toast";
  node.dataset.hook = "v2-toast";
  node.setAttribute("role", "status");
  node.setAttribute("aria-live", "polite");
  node.hidden = true;
  document.body.append(node);
  return node;
}

/** Показать `text` на 2,6 с. Пустая строка ничего не показывает. */
export function showToast(text) {
  const value = typeof text === "string" ? text.trim() : "";
  if (!value) return;
  const toast = ensureNode();
  toast.textContent = value;
  toast.hidden = false;
  clearTimeout(timer);
  timer = setTimeout(() => {
    toast.hidden = true;
    toast.textContent = "";
  }, SHOW_MS);
}
