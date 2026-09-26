"""Кэш модели монтажа: montage/.cache/model-<ключ>.json.

Разбор `timeline --json` дорог, а index.html меняется редко — модель кэшируется
по его тексту и версии движка. Имя кэша предсказуемо, а папку проекта могли
собрать чужими руками, поэтому запись принимается, только если это обычный
файл (не симлинк) и в ней записаны версия движка и sha256 ровно того текста
index.html, из которого она собрана, — и оба совпали с сегодняшними. Иначе —
промах: модель собирается заново и кэш перезаписывается своим файлом.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import MontageError
from .index_io import write_text_atomic
from .replace_target import regular_stat


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def cache_file(cache_dir: Path, version: str, html_text: str) -> Path:
    key = hashlib.sha256(f"{version}\0{html_text}".encode("utf-8")).hexdigest()[:24]
    return Path(cache_dir) / f"model-{key}.json"


def load(cache_dir: Path, version: str, html_text: str) -> dict | None:
    """Словарь модели из своего кэша или None (нет, чужой, битый, симлинк)."""

    path = cache_file(cache_dir, version, html_text)
    try:
        if regular_stat(path) is None:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return None
    if (isinstance(data, dict) and data.get("engine_version") == version
            and data.get("index_sha256") == _sha256(html_text) and isinstance(data.get("model"), dict)):
        return data["model"]
    return None


def save(cache_dir: Path, version: str, html_text: str, model: dict) -> None:
    """Кэш — только ускорение: не записался — не беда (атомарно, не по ссылке)."""

    record = {"engine_version": version, "index_sha256": _sha256(html_text), "model": model}
    try:
        write_text_atomic(cache_file(cache_dir, version, html_text), json.dumps(record, ensure_ascii=False))
    except MontageError:
        pass
