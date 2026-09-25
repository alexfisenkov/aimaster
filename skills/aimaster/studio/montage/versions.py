"""Версии монтажа: неизменяемые снимки versions/vNNN/{index.html, meta.json, model.json}.

Снимок готовится в скрытой .vNNN.staging рядом и публикуется переименованием
только после того, как версия записана в state, — видимая версия всегда
согласована с разделом montage проекта. Версии не удаляются и не перезаписываются.
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

BY_VALUES = ("agent", "owner", "autopilot")
# Дольше часа со свежей .vNNN.staging — не параллельная сборка, а брошенная
# попытка (тот же час, что и temp_sweep.MIN_AGE_SECONDS для прочих служебных
# временных папок навыка).
STAGING_MAX_AGE = 3600


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


def _staged(paths: MontagePaths) -> list[str]:
    """Номера версий, для которых уже начата (но не обязательно кончена)
    сборка: `.vNNN.staging` рядом с опубликованными — участвует в подсчёте
    следующего номера, чтобы вторая параллельная сборка не попала на тот же."""

    if not paths.versions.is_dir():
        return []
    names = []
    for item in paths.versions.iterdir():
        if item.is_dir() and item.name.startswith(".") and item.name.endswith(".staging"):
            inner = item.name[1:-len(".staging")]
            if VERSION_ID.fullmatch(inner):
                names.append(inner)
    return names


def next_version_id(paths: MontagePaths, recorded_ids: Iterable[str] = ()) -> str:
    """Следующий свободный vNNN — по трём источникам сразу: опубликованные на
    диске, начатые сборки на диске и версии, уже записанные в `state["montage"]`
    (round-fix-1/5, item 2б: без учёта state счётчик застревал, когда версия
    была принята в state, а её файлы на диске почему-то отставали)."""

    numbers = [version_number(name) for name in (*_published(paths), *_staged(paths))]
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


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _reserve_staging(paths: MontagePaths, version: str) -> Path:
    """Атомарная резервация `.vNNN.staging`: `mkdir` без `exist_ok` — та самая
    проверка-и-действие одним системным вызовом (round-fix-1/5, item 2а: было
    check-then-act — «есть, снести, создать» — два параллельных `montage
    build` одной версии затирали друг друга). Папка свежее часа — чужая
    сборка ещё идёт, отказ; часовая и старше — брошенная попытка, сносим и
    пробуем снова."""

    staging = paths.versions / f".{version}.staging"
    try:
        staging.mkdir(parents=True)
        return staging
    except FileExistsError:
        pass
    try:
        age = time.time() - staging.stat().st_mtime
    except OSError:
        age = None  # папка исчезла между попытками — не наша забота, пробуем создать снова
    if age is not None and age < STAGING_MAX_AGE:
        raise MontageError(f"сборка версии {version} уже идёт")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    return staging


def stage_version(paths: MontagePaths, meta: VersionMeta, model: Model) -> Path:
    if paths.version_dir(meta.version).exists():
        raise MontageError(f"версия {meta.version} уже есть — версии не перезаписываются")
    staging = _reserve_staging(paths, meta.version)
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
