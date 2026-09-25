"""Один замок на сборку монтажа, снимок версии на диске, публикация.

Round-fix-3/5, ruling: сборка версии больше не пытается разруливать гонку
резервациями с проверкой возраста — вместо этого один процесс за раз держит
`build_lock` на всё время сборки; внутри него `.vNNN.staging` может быть
только своя (чужому сборщику взяться неоткуда — замок один на проект).

Поток задачи 15 (документируется здесь, а не там, — это модуль, который его
обеспечивает):

    with build_lock(paths):
        settle_orphans(paths, recorded_ids=<state["montage"]["versions"] ids>)
        vid = next_version_id(paths, recorded_ids=<те же id>)
        # ... рендер в current/ ...
        staging = stage_version(paths, meta, model)
        montage_state.record_version(...)   # запись в state — граница правды
        publish_version(paths, staging, vid)

Инвариант: **публикуется только после записи в state**, не раньше. Если
процесс упадёт между `stage_version` и `record_version`, `.vNNN.staging`
останется валяться, а `state` о версии ничего не знает — следующий
`build_lock` найдёт эту папку в `settle_orphans` и снесёт (`recorded_ids` её
не назовёт, раз state не в курсе). Если упадёт МЕЖДУ `record_version` и
`publish_version` — `settle_orphans` следующего захода увидит: state знает,
снимок цел — опубликует его без пересборки.
"""

from __future__ import annotations

import json
import os
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable

from ..platform_compat import LockBusyError, file_lock
from . import MontageError
from .model import Model
from .paths import VERSION_ID, MontagePaths
from .versions import VersionMeta


def _staging_dir(paths: MontagePaths, version: str) -> Path:
    return paths.versions / f".{version}.staging"


@contextmanager
def build_lock(paths: MontagePaths):
    """Один замок на весь `montage build` — держит его от начала (`settle_
    orphans`) до конца (`publish_version`). Не блокирует: если кто-то уже
    строит этот же монтаж, отказ сразу, а не ожидание — вторая параллельная
    сборка того же проекта не имеет смысла ждать своей очереди, у неё нет
    более новых данных, чем у первой. ОС снимает замок сама, если держатель
    умер (аварийно или штатно) — специальной чистки не нужно."""

    paths.root.mkdir(parents=True, exist_ok=True)
    lock_path = paths.root / ".build.lock"
    with lock_path.open("a+", encoding="utf-8") as handle:
        try:
            with file_lock(handle, blocking=False):
                yield
        except LockBusyError:
            raise MontageError("сборка этого монтажа уже идёт") from None


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
    """Разбирает КАЖДУЮ `.vNNN.staging` на диске — первым делом внутри
    `build_lock`, до выбора номера новой версии. Раз замок один на проект,
    чужому сборщику взяться неоткуда: любая найденная — либо от своего же
    прошлого захода (упал между `stage_version` и `publish_version`), либо
    от недоделанной попытки (упал раньше). Полный снимок версии, уже
    записанной в `state` (`meta.json` целиком разбирается `VersionMeta.
    from_dict` и его `version` совпадает с именем папки, `model.json`
    разбирается, `index.html` на месте), — публикуется без пересборки; всё
    остальное сносится. `versions/vNNN` (уже опубликованные) и подкаталоги
    не по маске `.vNNN.staging` не трогает.

    Возвращает id версий, которые пришлось восстановить публикацией — для
    журнала вызывающего, не для его решений: `next_version_id` staging не
    считает вовсе, ей уже неоткуда взяться к моменту её вызова."""

    if not paths.versions.is_dir():
        return []
    recorded = set(recorded_ids)
    recovered = []
    for item in sorted(paths.versions.iterdir()):
        if not (item.is_dir() and item.name.startswith(".") and item.name.endswith(".staging")):
            continue
        version_id = item.name[1:-len(".staging")]
        if not VERSION_ID.fullmatch(version_id):
            continue
        if _complete_snapshot(item, version_id, recorded):
            publish_version(paths, item, version_id)
            recovered.append(version_id)
        else:
            shutil.rmtree(item, ignore_errors=True)
    return recovered


def stage_version(paths: MontagePaths, meta: VersionMeta, model: Model) -> Path:
    """Снимок версии в `.vNNN.staging`. Вызывающий держит `build_lock` и уже
    прогнал `settle_orphans` в начале той же сборки — коллизии `mkdir` здесь
    быть неоткуда; если она всё же случилась (внутренняя ошибка вызова, не
    гонка процессов — замок один), отказ по-русски, не голое исключение."""

    if paths.version_dir(meta.version).exists():
        raise MontageError(f"версия {meta.version} уже есть — версии не перезаписываются")
    staging = _staging_dir(paths, meta.version)
    try:
        staging.mkdir(parents=True)
    except FileExistsError as error:
        raise MontageError(f"версия {meta.version} уже собирается") from error
    try:
        shutil.copy2(paths.index, staging / "index.html")
        _write_json(staging / "meta.json", meta.to_dict())
        _write_json(staging / "model.json", model.to_dict())
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
