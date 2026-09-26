"""Вывод чужих программ (ffprobe, HyperFrames, лог монтажного стола) в отказе
человеку — без абсолютных путей: известные папки заменяются короткими метками,
домашняя — «~». Отказ показывают в дашборде и в чате; путь с именем
пользователя и устройством папок туда не нужен."""

from __future__ import annotations

import os
from pathlib import Path


def _variants(path) -> set[str]:
    text = str(path)
    found = {text, text.replace("\\", "/")}
    try:
        real = os.path.realpath(text)
        found |= {real, real.replace("\\", "/")}
    except (OSError, ValueError):
        pass
    return {value for value in found if len(value.strip("/\\")) > 1}


def short_paths(text: str, known: dict | None = None) -> str:
    """`known` — {папка: метка}; длинные пути заменяются первыми, чтобы
    вложенная папка не распалась на «метку родителя» и хвост."""

    pairs = [(value, label) for path, label in (known or {}).items() if path
             for value in _variants(path)]
    try:
        pairs += [(value, "~") for value in _variants(Path.home())]
    except (RuntimeError, OSError):
        pass
    for value, label in sorted(pairs, key=lambda pair: -len(pair[0])):
        text = text.replace(value, label)
    return text
