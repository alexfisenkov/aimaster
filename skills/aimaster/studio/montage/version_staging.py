"""Один замок на сборку монтажа, снимок версии на диске, публикация.

Один процесс за раз держит `build_lock` на всю сборку; внутри него
`.vNNN.staging` может быть только своя. Поток сборки (`render.render_version`):

    with build_lock(paths):
        settle_orphans(paths, recorded_ids=<id версий из state>)
        vid = next_version_id(paths, recorded_ids=<те же id>)
        # ... рендер ...
        staging = stage_version(paths, meta, model, index_text=<собранный текст>)
        montage_state.record_version(...)   # запись в state — граница правды
        publish_version(paths, staging, vid)

Инвариант: **публикуется только после записи в state**. Упал до записи —
state о версии не знает, и следующий `settle_orphans` сносит staging; упал
между записью и публикацией — state знает, снимок цел, и следующий
`settle_orphans` публикует его без пересборки.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Iterable

from ..platform_compat import fsync_directory
from . import MontageError
from .locks import held_lock
from .model import Model
from .paths import VERSION_ID, MontagePaths
from .versions import VersionMeta


def _staging_dir(paths: MontagePaths, version: str) -> Path:
    return paths.versions / f".{version}.staging"


def build_lock(paths: MontagePaths):
    """Замок на всю сборку проекта; не ждёт — у второй параллельной сборки нет
    данных новее, чем у первой."""

    return held_lock(paths.root / ".build.lock", busy="сборка этого монтажа уже идёт")


def _write_durable(path: Path, text: str) -> None:
    # fsync: после сбоя питания записанная в state версия не останется с пустым снимком
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())


def _json(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def _complete_snapshot(staging: Path, version_id: str, recorded: set[str]) -> bool:
    if version_id not in recorded or not (staging / "index.html").is_file():
        return False
    try:
        meta = VersionMeta.from_dict(json.loads((staging / "meta.json").read_text(encoding="utf-8")))
        json.loads((staging / "model.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return meta.version == version_id


def settle_orphans(paths: MontagePaths, recorded_ids: Iterable[str]) -> list[str]:
    """Разбирает каждую `.vNNN.staging` — первым делом под `build_lock`, до
    выбора номера. Полный снимок версии, которую state уже знает, а на диске
    опубликованной нет, — публикуется; остальное (недоделанная попытка или
    лишний второй снимок опубликованной версии) сносится. Не вышло
    опубликовать — снимок ждёт следующей сборки, эта не блокируется.
    Возвращает id опубликованных — для журнала вызывающего."""

    if not paths.versions.is_dir():
        return []
    recorded = set(recorded_ids)
    recovered = []
    try:
        items = sorted(paths.versions.iterdir())
    except OSError as error:
        raise MontageError("не удалось прочитать папку montage/versions") from error
    for item in items:
        if not (item.is_dir() and item.name.startswith(".") and item.name.endswith(".staging")):
            continue
        version_id = item.name[1:-len(".staging")]
        if not VERSION_ID.fullmatch(version_id):
            continue
        if paths.version_dir(version_id).exists() or not _complete_snapshot(item, version_id, recorded):
            shutil.rmtree(item, ignore_errors=True)
            continue
        try:
            publish_version(paths, item, version_id)
        except OSError:
            continue
        recovered.append(version_id)
    return recovered


def stage_version(paths: MontagePaths, meta: VersionMeta, model: Model, *,
                  index_text: str | None = None) -> Path:
    """Снимок версии в `.vNNN.staging`, каждый файл с fsync. `index_text` —
    ровно тот текст, что собран в MP4 (Studio может записать current/ уже
    после сборки); без него — текущий current/index.html. Коллизия `mkdir`
    под `build_lock` — внутренняя ошибка вызова: отказ по-русски."""

    if paths.version_dir(meta.version).exists():
        raise MontageError(f"версия {meta.version} уже есть — версии не перезаписываются")
    staging = _staging_dir(paths, meta.version)
    try:
        staging.mkdir(parents=True)
    except FileExistsError as error:
        raise MontageError(f"версия {meta.version} уже собирается") from error
    except OSError as error:
        raise MontageError(f"не удалось создать снимок версии {meta.version}") from error
    try:
        if index_text is None:
            with paths.index.open(encoding="utf-8", newline="") as handle:
                index_text = handle.read()
        _write_durable(staging / "index.html", index_text)
        _write_durable(staging / "meta.json", _json(meta.to_dict()))
        _write_durable(staging / "model.json", _json(model.to_dict()))
        fsync_directory(staging)
    except OSError as error:
        shutil.rmtree(staging, ignore_errors=True)
        raise MontageError(f"не удалось записать снимок версии {meta.version}") from error
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return staging


def publish_version(paths: MontagePaths, staging: Path, version_id: str) -> Path:
    final = paths.version_dir(version_id)
    os.rename(staging, final)
    return final


def discard_staging(staging: Path) -> None:
    shutil.rmtree(staging, ignore_errors=True)
