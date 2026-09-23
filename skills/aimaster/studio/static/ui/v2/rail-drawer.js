// Панель проектов в v2 (редизайн 2026-09-23). Список внутри рисует v1
// (`ui/rail.js`), здесь — только где панель стоит и как открывается:
//
// - десктоп (≥ 760px): панель 256px стоит слева в сетке, липкая на всю
//   высоту. Кнопка «‹» в ней сворачивает панель, тогда в шапке
//   появляется «☰», который возвращает её. Выбор запоминается.
// - телефон (< 760px): выдвижная панель поверх страницы, затемнение,
//   `Esc`, ловушка Tab; «☰» открывает, «✕» и фон закрывают.
//
// Скрытая панель не просто уезжает за край: ей ставится `inert`, иначе
// её поиск и кнопки остаются в порядке обхода Tab и в дереве доступности.

import { isPhone, onViewportChange } from "./responsive.js";

const FOCUSABLE = 'button:not([disabled]), a[href], input:not([disabled]), [tabindex="0"]';
const COLLAPSED_KEY = "aimaster.v2.railCollapsed";

function readCollapsed() {
  try {
    return window.localStorage.getItem(COLLAPSED_KEY) === "1";
  } catch {
    return false;
  }
}

function writeCollapsed(value) {
  try {
    window.localStorage.setItem(COLLAPSED_KEY, value ? "1" : "0");
  } catch {
    // Память — удобство, а не условие работы.
  }
}

/**
 * @returns {{open: () => void, close: () => void, toggle: () => void,
 *            isOpen: () => boolean}} `isOpen` — открыта ли выдвижная
 *   панель телефона; стоящая в сетке десктопная панель «открытой» не
 *   считается: выбор проекта её не убирает.
 */
export function createRailDrawer() {
  const root = document.querySelector('[data-hook="project-rail"]');
  const toggle = document.querySelector('[data-hook="rail-toggle"]');
  const label = toggle?.querySelector(".visually-hidden");
  const backdrop = document.querySelector('[data-hook="rail-backdrop"]');
  let open = false;
  let collapsed = readCollapsed();
  let phone = isPhone();

  function paint() {
    document.body.dataset.rail = phone ? (open ? "open" : "closed") : (collapsed ? "collapsed" : "docked");
    if (!root) return;
    const overlayOpen = phone && open;
    if (overlayOpen) {
      root.setAttribute("data-open", "true");
      backdrop?.setAttribute("data-open", "true");
    } else {
      root.removeAttribute("data-open");
      backdrop?.removeAttribute("data-open");
    }
    const visible = phone ? open : !collapsed;
    root.inert = !visible;
    if (phone) {
      toggle?.setAttribute("aria-expanded", String(open));
      if (label) label.textContent = open ? "Закрыть панель проектов" : "Открыть панель проектов";
    } else {
      toggle?.setAttribute("aria-expanded", String(!collapsed));
      if (label) label.textContent = "Показать панель проектов";
    }
  }

  function focusRail() {
    root?.querySelector("input, button")?.focus();
  }

  function openRail() {
    if (phone) open = true;
    else {
      collapsed = false;
      writeCollapsed(false);
    }
    paint();
    focusRail();
  }

  /** Закрыть выдвижную панель телефона; стоящую в сетке не трогаем. */
  function closeRail() {
    if (!phone) return;
    open = false;
    paint();
  }

  /** «‹» на десктопе, «✕» на телефоне. */
  function hideRail() {
    if (phone) {
      closeRail();
    } else {
      collapsed = true;
      writeCollapsed(true);
      paint();
    }
    toggle?.focus();
  }

  toggle?.addEventListener("click", () => {
    if (phone && open) {
      closeRail();
      toggle.focus();
    } else {
      openRail();
    }
  });
  backdrop?.addEventListener("click", () => {
    closeRail();
    toggle?.focus();
  });
  document.addEventListener("studio:rail-hide", hideRail);
  document.addEventListener("keydown", (event) => {
    if (!phone || !open || !root) return;
    if (event.key === "Escape") {
      event.preventDefault();
      closeRail();
      toggle?.focus();
      return;
    }
    if (event.key !== "Tab") return;
    const nodes = [...root.querySelectorAll(FOCUSABLE)].filter((node) => !node.hidden && node.offsetParent !== null);
    if (!nodes.length) {
      event.preventDefault();
      return;
    }
    const [first] = nodes;
    const last = nodes.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
  onViewportChange((next) => {
    phone = next;
    open = false;
    paint();
  });

  // Первая отрисовка: скрытая панель обязана быть `inert` сразу, а не
  // после первого клика.
  paint();
  return {
    open: openRail,
    close: closeRail,
    toggle: () => (phone && open ? closeRail() : openRail()),
    isOpen: () => phone && open,
  };
}
