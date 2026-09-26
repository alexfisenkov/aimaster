"""Версии монтажа: что такое версия, её номер, чтение, возврат к снимку.

Снимок на диске (резервация, замок сборки, публикация) — в
`version_staging.py`: с round-fix-3/5 (один замок на сборку вместо
резерваций с проверкой возраста) staging больше не влияет на номер версии,
поэтому `next_version_id` здесь больше не знает о `version_staging.py`
вовсе — обратной зависимости, которая была в round-fix-2/5, больше нет.

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

from ..platform_compat import IS_WINDOWS, replace_file
from . import MontageError
from .model import Model
from .paths import VERSION_ID, MontagePaths, version_name, version_number

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


def next_version_id(paths: MontagePaths, *, recorded_ids: Iterable[str]) -> str:
    """Следующий свободный vNNN — максимум среди опубликованных на диске и
    записанных в `state["montage"]["versions"]`, плюс один. `recorded_ids`
    — обязательный именованный аргумент (не «пусто по умолчанию», как было
    в round-fix-1/5): вызывающий обязан явно передать то, что знает state,
    а не тихо забыть про него.

    Staging здесь не участвует вовсе (round-fix-3/5): вызывающий держит
    `build_lock` и уже прогнал `version_staging.settle_orphans` — к этому
    моменту `.vNNN.staging` попросту неоткуда взяться."""

    numbers = [version_number(name) for name in _published(paths)]
    numbers += [version_number(rid) for rid in recorded_ids if VERSION_ID.fullmatch(str(rid))]
    return version_name(max(numbers, default=0) + 1)


def read_meta(paths: MontagePaths, version_id: str) -> VersionMeta:
    try:
        data = json.loads((paths.version_dir(version_id) / "meta.json").read_text(encoding="utf-8"))
        return VersionMeta.from_dict(data)
    except (OSError, ValueError, KeyError) as error:
        raise MontageError(f"нет версии {version_id}") from error


def list_versions(paths: MontagePaths) -> list[VersionMeta]:
    """Все читаемые версии; повреждённая meta.json одной версии не роняет список."""

    found = []
    for name in _published(paths):
        try:
            found.append(read_meta(paths, name))
        except MontageError:
            continue
    return found


def current_meta(paths: MontagePaths, version_id: str | None) -> VersionMeta | None:
    """meta.json текущей версии; нет версии или снимок не читается — None."""

    try:
        return read_meta(paths, version_id) if version_id else None
    except (MontageError, ValueError):
        return None


def read_version_model(paths: MontagePaths, version_id: str) -> Model:
    try:
        data = json.loads((paths.version_dir(version_id) / "model.json").read_text(encoding="utf-8"))
        return Model.from_dict(data)
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise MontageError(f"у версии {version_id} нет модели монтажа") from error


def _backup_copy(source: Path, target: Path, *, attempts: int = 20, delay: float = 0.05) -> None:
    """Windows: пока другой процесс или поток подменяет index.html, открыть его
    на чтение нельзя (WinError 32) — мгновение, как у replace_file, не отказ."""

    for attempt in range(attempts):
        try:
            shutil.copy2(source, target)
            return
        except PermissionError:
            if not IS_WINDOWS or attempt + 1 == attempts:
                raise
            time.sleep(delay)


def restore_files(paths: MontagePaths, version_id: str) -> Path | None:
    """Кладёт снимок версии в current/index.html; прежний current — в .undo/."""

    source = paths.version_dir(version_id) / "index.html"
    if not source.is_file():
        raise MontageError(f"нет версии {version_id}")
    backup = None
    if paths.index.is_file():
        backup = paths.undo / (f"before-restore-{time.strftime('%Y%m%d-%H%M%S')}"
                               f"-{time.time_ns() % 1_000_000_000:09d}.html")
        try:
            paths.undo.mkdir(parents=True, exist_ok=True)
            _backup_copy(paths.index, backup)
        except OSError as error:
            raise MontageError(f"не удалось сохранить текущий монтаж перед возвратом к {version_id}"
                               ) from error
    # mkstemp, не фиксированное имя: два параллельных restore или недобитый
    # временный файл прошлой попытки не столкнутся на одном имени.
    temporary = None
    try:
        descriptor, temp_name = tempfile.mkstemp(
            dir=paths.index.parent, prefix=f".{paths.index.name}.", suffix=".restore.tmp")
        os.close(descriptor)
        temporary = Path(temp_name)
        shutil.copy2(source, temporary)
        replace_file(temporary, paths.index)
    except OSError as error:
        # Текст OSError (по-английски, с путями) — только в цепочке исключения.
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise MontageError(f"не удалось восстановить версию {version_id}") from error
    return backup


def has_unrendered_changes(current_hash: str | None, current: VersionMeta | None) -> bool:
    return current is None or current_hash != current.model_hash
