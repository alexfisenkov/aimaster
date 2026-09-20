import { requestAgentPrompt } from "./chat-prompt-dialog.js";

export function questionCountLabel(count) {
  const n = Number.isFinite(count) && count >= 0 ? Math.floor(count) : 0;
  const lastTwo = n % 100;
  const last = n % 10;
  const word = lastTwo >= 11 && lastTwo <= 14
    ? "уточнений"
    : last === 1
      ? "уточнение"
      : last >= 2 && last <= 4
        ? "уточнения"
        : "уточнений";
  return `${n} ${word}`;
}

export function renderNeedAnswer(root, { project, questions = [], blocked = false } = {}) {
  if (!root) throw new TypeError("root is required");
  const list = Array.isArray(questions) ? questions : [];
  if (list.length === 0 && !blocked) return false;

  const card = document.createElement("section");
  card.className = "need-answer";
  card.dataset.hook = "need-answer";
  const heading = document.createElement("div");
  heading.className = "need-answer-heading";
  const title = document.createElement("h2");
  title.textContent = "Нужен ответ";
  const count = document.createElement("span");
  count.className = "need-answer-count";
  count.textContent = questionCountLabel(list.length);
  heading.append(title, count);
  const text = document.createElement("p");
  text.textContent = "Агент разбирается с замыслом и ждёт ваших уточнений. Вопросы он задаёт там, где вы с ним работаете — здесь, в дашборде, переписки нет.";

  const controls = document.createElement("div");
  controls.className = "need-answer-controls";
  const refresh = document.createElement("button");
  refresh.type = "button";
  refresh.className = "need-answer-refresh";
  refresh.textContent = "Я ответил — обновить";
  refresh.addEventListener("click", () => {
    const projectId = project?.id;
    document.dispatchEvent(new CustomEvent("studio:refresh-snapshot", {
      bubbles: true,
      detail: { projectId },
    }));
  });
  const chat = document.createElement("button");
  chat.type = "button";
  chat.className = "need-answer-chat";
  chat.textContent = "Скопировать запрос агенту";
  chat.addEventListener("click", () => {
    const titleText = typeof project?.title === "string" && project.title.trim()
      ? project.title.trim()
      : "Без названия";
    requestAgentPrompt({
      title: "Ответить агенту в чате",
      prompt: `Продолжи проект «${titleText}» (ID: ${project?.id || "не указан"}). Покажи мне только вопросы, которые сейчас блокируют проект, и дождись моих ответов. После ответа обнови состояние проекта.`,
    }, chat);
  });
  controls.append(refresh, chat);
  card.append(heading, text, controls);
  root.append(card);
  return true;
}
