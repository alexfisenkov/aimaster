// Выдвижная панель проектов в v2: кнопка ☰, затемнение, `Esc` и ловушка
// Tab. Список внутри панели рисует v1 (`ui/rail.js`) — здесь только
// «открыть и закрыть», как это делает старая оболочка (`static/app-v1.js`).
//
// Закрытая панель не просто уезжает за край: ей ставится `inert`, иначе
// её поиск и кнопки остаются в порядке обхода Tab и в дереве доступности,
// хотя на экране ничего нет.

const FOCUSABLE = 'button:not([disabled]), a[href], input:not([disabled]), [tabindex="0"]';

/**
 * @returns {{open: () => void, close: () => void, toggle: () => void,
 *            isOpen: () => boolean}}
 */
export function createRailDrawer() {
  const root = document.querySelector('[data-hook="project-rail"]');
  const toggle = document.querySelector('[data-hook="rail-toggle"]');
  const label = toggle?.querySelector(".visually-hidden");
  const backdrop = document.querySelector('[data-hook="rail-backdrop"]');
  let open = false;

  function set(next) {
    open = next === true;
    if (!root) return;
    if (open) {
      root.setAttribute("data-open", "true");
      backdrop?.setAttribute("data-open", "true");
    } else {
      root.removeAttribute("data-open");
      backdrop?.removeAttribute("data-open");
    }
    root.inert = !open;
    toggle?.setAttribute("aria-expanded", String(open));
    if (label) label.textContent = open ? "Закрыть панель проектов" : "Открыть панель проектов";
  }

  function openRail() {
    set(true);
    root?.querySelector("input, button")?.focus();
  }

  function closeRail() {
    set(false);
  }

  toggle?.addEventListener("click", () => {
    if (open) {
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
  document.addEventListener("keydown", (event) => {
    if (!open || !root) return;
    if (event.key === "Escape") {
      event.preventDefault();
      closeRail();
      toggle?.focus();
      return;
    }
    if (event.key !== "Tab") return;
    const nodes = [...root.querySelectorAll(FOCUSABLE)].filter((node) => !node.hidden);
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

  // Первая отрисовка: закрытая панель обязана быть `inert` сразу, а не
  // после первого клика.
  set(false);
  return { open: openRail, close: closeRail, toggle: () => (open ? closeRail() : openRail()), isOpen: () => open };
}
