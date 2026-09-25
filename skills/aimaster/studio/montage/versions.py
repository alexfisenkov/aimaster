"""Версии монтажа: неизменяемые снимки versions/vNNN/{index.html, meta.json, model.json}.

Снимок готовится в скрытой .vNNN.staging рядом и публикуется переименованием
только после того, как версия записана в state, — видимая версия всегда
согласована с разделом montage проекта. Версии не удаляются и не перезаписываются.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from ..platform_compat import replace_file
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


def next_version_id(paths: MontagePaths) -> str:
    return version_name(max((version_number(name) for name in _published(paths)), default=0) + 1)


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


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def stage_version(paths: MontagePaths, meta: VersionMeta, model: Model) -> Path:
    if paths.version_dir(meta.version).exists():
        raise MontageError(f"версия {meta.version} уже есть — версии не перезаписываются")
    staging = paths.versions / f".{meta.version}.staging"
    if staging.exists():
        shutil.rmtree(staging)  # недоделанная прошлая попытка той же версии
    staging.mkdir(parents=True)
    shutil.copy2(paths.index, staging / "index.html")
    _write_json(staging / "meta.json", meta.to_dict())
    _write_json(staging / "model.json", model.to_dict())
    return staging


def publish_version(paths: MontagePaths, staging: Path, version_id: str) -> Path:
    final = paths.version_dir(version_id)
    os.rename(staging, final)
    return final


def discard_staging(staging: Path) -> None:
    shutil.rmtree(staging, ignore_errors=True)


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
    temporary = paths.index.with_name(".index.restore.tmp")
    shutil.copy2(source, temporary)
    replace_file(temporary, paths.index)
    return backup


def has_unrendered_changes(current_hash: str | None, current: VersionMeta | None) -> bool:
    return current is None or current_hash != current.model_hash
