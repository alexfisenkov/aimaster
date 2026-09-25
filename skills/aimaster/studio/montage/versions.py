"""Версии монтажа: неизменяемые снимки versions/vNNN/{index.html, meta.json, model.json}.

Место снимка на диске (резервация `.vNNN.staging`, публикация переименованием,
`reserve_version`) — в `version_staging.py`; здесь — что такое версия и её
номер. Публичные имена оттуда переимпортированы: `from .versions import
stage_version` (и `publish_version`/`discard_staging`/`STAGING_MAX_AGE`)
по-прежнему работает, хотя тело живёт в другом файле.

Версии не удаляются и не перезаписываются.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from ..platform_compat import replace_file
from . import MontageError
from .model import Model
from .paths import VERSION_ID, MontagePaths, version_name, version_number
from .version_staging import (  # noqa: F401 — переимпорт: прежние имена этого модуля
    STAGING_MAX_AGE, discard_staging, fresh_staged_numbers, publish_version,
    recover_published_from_staging, reserve_version, stage_version)

BY_VALUES = ("agent", "owner", "autopilot")


@dataclass(frozen=True)
class VersionMeta:
    version: str
    created_at: str
    by: str
    based_on: str | None
    summary: str
    changes: tuple[str, ...]
    asset_id: str
    model_hash: str

    def to_dict(self) -> dict:
        data = asdict(self)
        data["changes"] = list(self.changes)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "VersionMeta":
        return cls(version=data["version"], created_at=data["created_at"], by=data["by"],
                   based_on=data.get("based_on"), summary=data.get("summary", ""),
                   changes=tuple(data.get("changes", [])), asset_id=data["asset_id"],
                   model_hash=data["model_hash"])


def _published(paths: MontagePaths) -> list[str]:
    if not paths.versions.is_dir():
        return []
    names = [item.name for item in paths.versions.iterdir()
             if item.is_dir() and VERSION_ID.fullmatch(item.name) and (item / "meta.json").is_file()]
    return sorted(names, key=version_number)


def next_version_id(paths: MontagePaths, recorded_ids: Iterable[str] = ()) -> str:
    """Следующий свободный vNNN — по трём источникам сразу: опубликованные на
    диске, начатые (и ещё не брошенные) сборки на диске и версии, уже
    записанные в `state["montage"]` (round-fix-1/5, item 2б: без учёта state
    счётчик застревал, когда версия была принята в state, а её файлы на диске
    почему-то отставали). Брошенная `.vNNN.staging` (час и старше) не
    считается вовсе — иначе номер оставался бы занятым навсегда, даже после
    того как её давно вымели бы (round-fix-2/5, item 4)."""

    numbers = [version_number(name) for name in _published(paths)]
    numbers += fresh_staged_numbers(paths)
    numbers += [version_number(rid) for rid in recorded_ids if VERSION_ID.fullmatch(str(rid))]
    return version_name(max(numbers, default=0) + 1)


def read_meta(paths: MontagePaths, version_id: str) -> VersionMeta:
    try:
        data = json.loads((paths.version_dir(version_id) / "meta.json").read_text(encoding="utf-8"))
        return VersionMeta.from_dict(data)
    except (OSError, ValueError, KeyError) as error:
        raise MontageError(f"нет версии {version_id}") from error


def list_versions(paths: MontagePaths) -> list[VersionMeta]:
    return [read_meta(paths, name) for name in _published(paths)]


def read_version_model(paths: MontagePaths, version_id: str) -> Model:
    try:
        data = json.loads((paths.version_dir(version_id) / "model.json").read_text(encoding="utf-8"))
        return Model.from_dict(data)
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise MontageError(f"у версии {version_id} нет модели монтажа") from error


def restore_files(paths: MontagePaths, version_id: str) -> Path | None:
    """Кладёт снимок версии в current/index.html; прежний current — в .undo/."""

    source = paths.version_dir(version_id) / "index.html"
    if not source.is_file():
        raise MontageError(f"нет версии {version_id}")
    backup = None
    if paths.index.is_file():
        paths.undo.mkdir(parents=True, exist_ok=True)
        backup = paths.undo / (f"before-restore-{time.strftime('%Y%m%d-%H%M%S')}"
                               f"-{time.time_ns() % 1_000_000_000:09d}.html")
        shutil.copy2(paths.index, backup)
    # mkstemp — не голое фиксированное имя (round-fix-1/5, item 11): два
    # параллельных restore (или недобитый временный файл прошлой попытки)
    # раньше коллизировали на одном ".index.restore.tmp".
    descriptor, temp_name = tempfile.mkstemp(
        dir=paths.index.parent, prefix=f".{paths.index.name}.", suffix=".restore.tmp")
    os.close(descriptor)
    temporary = Path(temp_name)
    try:
        shutil.copy2(source, temporary)
        replace_file(temporary, paths.index)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise MontageError(f"не удалось восстановить версию {version_id}: {error}") from error
    return backup


def has_unrendered_changes(current_hash: str | None, current: VersionMeta | None) -> bool:
    return current is None or current_hash != current.model_hash
