"""Команда одной строкой — для показа человеку и для запуска в оболочке.

Список аргументов (`engine.install_argv`) надёжнее всего; строка нужна там,
где агент выполняет команду в оболочке. На Windows у разных агентов разные
оболочки: Claude Code — Git Bash, Codex — PowerShell."""

from __future__ import annotations

import re
import shlex

# Слово, которое Git Bash и PowerShell читают одинаково и без кавычек: буквы
# (и кириллица), цифры и «_ . / : + % -». Всё прочее — пробел, скобки
# «Program Files (x86)», «&», «,», «;», «'», «#», «~» — берётся в кавычки.
_PLAIN_WORD = re.compile(r"[\w./:+%-]+")


def _windows_word(text: str) -> str:
    """Двойные кавычки понимают обе оболочки одинаково, пока внутри нет «$» и
    «`» (обе там подставляют переменные); с ними — одинарные, в них обе
    оболочки ничего не подставляют. Кавычки в имени файла Windows не бывает."""

    text = text.replace("\\", "/")  # «/» понимают и bash, и PowerShell, и Windows
    if _PLAIN_WORD.fullmatch(text):
        return text
    if ("$" in text or "`" in text) and "'" not in text:
        return f"'{text}'"
    return f'"{text}"'


def command_line(argv, *, windows: bool) -> str:
    """Строка команды для показа и для запуска в оболочке. POSIX — shlex.
    Windows — пути с «/» и кавычками только где нужно: строку без кавычек у
    программы выполняют и Git Bash (оболочка Claude Code на Windows), и
    PowerShell; в кавычках программу bash выполнит как есть, а PowerShell —
    только с оператором вызова: `& "C:/…/python.exe" …`. Сам «&» в строку не
    входит — в bash это запуск в фоне и ошибка разбора в начале строки."""

    if not windows:
        return shlex.join(str(part) for part in argv)
    return " ".join(_windows_word(str(part)) for part in argv)
