// Accessible overflow menu for card actions. Its open state lives in the
// shared draft map so an eight-second snapshot repaint can rebuild the card
// without silently closing the menu.

import { draftKey, getDraft, setDraft } from "./card-drafts.js";

let outsideListenerDocument = null;

function setMenuOpen(root, open, { focusTrigger = false, focusFirst = false } = {}) {
  const trigger = root.querySelector('[data-more-hook="trigger"]');
  const popup = root.querySelector('[data-hook="more-menu-popup"]');
  if (!trigger || !popup) {
    return;
  }
  const resolved = open === true;
  trigger.setAttribute("aria-expanded", String(resolved));
  popup.hidden = !resolved;
  root.dataset.open = String(resolved);
  setDraft(root.dataset.draftKey, { open: resolved });
  if (focusFirst && resolved) {
    popup.querySelector('[data-more-hook="item"]')?.focus();
  } else if (focusTrigger) {
    trigger.focus();
  }
}

function closeEveryOpenMenu() {
  for (const root of document.querySelectorAll('[data-hook="more-menu"][data-open="true"]')) {
    setMenuOpen(root, false);
  }
}

function ensureOutsideListener() {
  if (outsideListenerDocument === document) {
    return;
  }
  outsideListenerDocument = document;
  document.addEventListener("click", (event) => {
    if (event.target?.closest?.('[data-hook="more-menu"]')) {
      return;
    }
    closeEveryOpenMenu();
  });
}

function moveItemFocus(root, direction) {
  const items = [...root.querySelectorAll('[data-more-hook="item"]')].filter(
    (item) => !item.disabled,
  );
  if (items.length === 0) {
    return;
  }
  const current = items.indexOf(document.activeElement);
  const next = current < 0 ? 0 : (current + direction + items.length) % items.length;
  items[next].focus();
}

export function appendMoreMenuContent(root, content) {
  const popup = root?.querySelector('[data-hook="more-menu-popup"]');
  if (!popup || !content || content.nodeType !== 1) {
    return false;
  }
  let controls =
    content.tagName === "BUTTON"
      ? [content]
      : [...content.childNodes].filter((node) => node?.tagName === "BUTTON");
  if (controls.length === 0) {
    const nestedTrigger = content.querySelector("button");
    controls = nestedTrigger ? [nestedTrigger] : [];
  }
  for (const control of controls) {
    control.dataset.moreHook = "item";
    control.setAttribute("role", "menuitem");
  }
  popup.append(content);
  return true;
}

export function buildMoreMenu({ projectId, targetId, items }) {
  if (typeof projectId !== "string" || !projectId || typeof targetId !== "string" || !targetId) {
    throw new TypeError("buildMoreMenu requires projectId and targetId");
  }
  if (!Array.isArray(items) || items.length === 0) {
    throw new TypeError("buildMoreMenu requires at least one item");
  }
  ensureOutsideListener();

  const key = draftKey(projectId, "more-menu", targetId);
  const root = document.createElement("div");
  root.className = "more-menu";
  root.dataset.hook = "more-menu";
  root.dataset.draftKey = key;
  root.addEventListener("click", (event) => event.stopPropagation());

  const trigger = document.createElement("button");
  trigger.type = "button";
  trigger.className = "more-menu-trigger";
  trigger.dataset.hook = "card-control";
  trigger.dataset.moreHook = "trigger";
  trigger.dataset.targetId = targetId;
  trigger.dataset.action = "more";
  trigger.setAttribute("aria-haspopup", "menu");
  trigger.textContent = "Ещё";

  const popup = document.createElement("div");
  popup.className = "more-menu-popup";
  popup.dataset.hook = "more-menu-popup";
  popup.setAttribute("role", "menu");
  root.append(trigger, popup);

  for (const item of items) {
    if (!item || typeof item.id !== "string" || !item.id) {
      throw new TypeError("every more-menu item requires id, label and onSelect");
    }
    if (item.content && item.content.nodeType === 1) {
      appendMoreMenuContent(root, item.content);
      continue;
    }
    if (typeof item.label !== "string" || !item.label || typeof item.onSelect !== "function") {
      throw new TypeError("every more-menu item requires id, label and onSelect");
    }
    const button = document.createElement("button");
    button.type = "button";
    button.className = "more-menu-item";
    button.dataset.hook = "card-control";
    button.dataset.moreHook = "item";
    button.dataset.targetId = targetId;
    button.dataset.action = `more:${item.id}`;
    button.setAttribute("role", "menuitem");
    button.disabled = item.disabled === true;
    button.textContent = item.label;
    button.addEventListener("click", () => {
      item.onSelect();
      setMenuOpen(root, false, { focusTrigger: true });
    });
    popup.append(button);
  }

  trigger.addEventListener("click", () => {
    const open = trigger.getAttribute("aria-expanded") !== "true";
    if (open) {
      closeEveryOpenMenu();
    }
    setMenuOpen(root, open);
  });
  trigger.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      setMenuOpen(root, true, { focusFirst: true });
    }
  });
  root.addEventListener("keydown", (event) => {
    const editingTarget =
      ["INPUT", "TEXTAREA", "SELECT"].includes(event.target?.tagName) ||
      event.target?.isContentEditable === true;
    if (editingTarget && event.key !== "Escape") {
      return;
    }
    if (event.target === trigger && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      setMenuOpen(root, false, { focusTrigger: true });
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      moveItemFocus(root, 1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      moveItemFocus(root, -1);
    } else if (event.key === "Home") {
      event.preventDefault();
      root.querySelector('[data-more-hook="item"]')?.focus();
    } else if (event.key === "End") {
      event.preventDefault();
      const enabled = [...root.querySelectorAll('[data-more-hook="item"]')].filter(
        (item) => !item.disabled,
      );
      enabled[enabled.length - 1]?.focus();
    }
  });

  setMenuOpen(root, getDraft(key)?.open === true);
  return root;
}
