"""Строка summary версии монтажа. Она уходит в state (montage.versions[].summary
и assembly.summary), а там `projection._safe_system_text` не пускает служебные
подстроки (mcp, model, cost, token, path, …) — даже внутри обычных слов
(«Costa Rica»). Правило одно — `projection.forbidden_system_word`; здесь —
что делать, если оно сработало: свою подпись (`--summary`) отклоняем до
сборки, автоматическую заменяем нейтральной (подробности остаются в
`changes` meta.json)."""

from __future__ import annotations

from ..projection import forbidden_system_word
from . import MontageError


def changes_label(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return f"{count} изменение"
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return f"{count} изменения"
    return f"{count} изменений"


def auto_summary(base: str | None, changes: list[str]) -> str:
    if base is None:
        return "Черновой монтаж"
    if not changes:
        return "Пересборка без изменений"
    more = f" и ещё {len(changes) - 3}" if len(changes) > 3 else ""
    text = "; ".join(changes[:3]) + more
    return f"Пересборка: {changes_label(len(changes))}" if forbidden_system_word(text) else text


def checked_summary(summary: str | None) -> str | None:
    """Подпись версии от человека или агента — до всякой работы: иначе рендер
    прошёл бы зря, а запись state отказала бы в самом конце."""

    fragment = forbidden_system_word(summary or "")
    if fragment is None:
        return summary or None
    word = next((token for token in summary.split() if fragment.lower() in token.lower()), fragment)
    raise MontageError(f"--summary: дашборд не показывает текст с «{fragment}» (в «{word}») — "
                       "служебные слова вроде model, cost, token, path под запретом; "
                       "перефразируйте подпись")
