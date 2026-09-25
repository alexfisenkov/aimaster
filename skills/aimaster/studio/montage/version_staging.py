"""Место версии на диске: `.vNNN.staging` рядом с `versions/vNNN`.

Отдельно от `versions.py` (round-fix-2/5, item 4): там — смысл версии
(`VersionMeta`, счёт номеров, чтение), здесь — сама папка на диске и то, что
не даёт двум параллельным сборкам занять одно и то же место. `versions.py`
переимпортирует публичные имена отсюда — старые `from .versions import
stage_version` не ломаются.

`reserve_version` зовёт `next_version_id` из `versions.py` — оттуда сюда
идёт обратная зависимость (эта функция нужна и `versions.py` для подсчёта
номеров), поэтому импорт внутри функции: на верхнем уровне модуля это было
бы циклом.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

from . import MontageError
from .paths import VERSION_ID, MontagePaths, version_number

if TYPE_CHECKING:
    from .model import Model
    from .versions import VersionMeta

# Дольше часа со свежей .vNNN.staging — не параллельная сборка, а брошенная
# попытка (тот же час, что и temp_sweep.MIN_AGE_SECONDS для прочих служебных
# временных папок навыка).
STAGING_MAX_AGE = 3600


def _staging_dir(paths: MontagePaths, version: str) -> Path:
    return paths.versions / f".{version}.staging"


def _age(path: Path) -> float | None:
    try:
        return time.time() - path.stat().st_mtime
    except OSError:
        return None  # папка исчезла между попытками — не наша забота


def fresh_staged_numbers(paths: MontagePaths) -> list[int]:
    """Номера версий с начатой сборкой моложе часа. Брошенные (часовые и
    старше) не считаются: иначе номер оставался бы занятым навсегда, даже
    после того как `_reserve` давно вымела бы саму папку (round-fix-2/5,
    item 4: раньше `_staged()` в versions.py считал их все без разбора)."""

    if not paths.versions.is_dir():
        return []
    numbers = []
    for item in paths.versions.iterdir():
        if not (item.is_dir() and item.name.startswith(".") and item.name.endswith(".staging")):
            continue
        inner = item.name[1:-len(".staging")]
        if not VERSION_ID.fullmatch(inner):
            continue
        age = _age(item)
        if age is not None and age < STAGING_MAX_AGE:
            numbers.append(version_number(inner))
    return numbers


def _trash_name(staging: Path) -> Path:
    return staging.with_name(
        f"{staging.name}.trash-{os.getpid()}-{time.time_ns() % 1_000_000_000:09d}")


def _reserve(paths: MontagePaths, version: str) -> Path:
    """Атомарная резервация `.vNNN.staging`: голый `mkdir` без `exist_ok` —
    сама резервация, не проверка перед ней. Брошенная (часовая и старше)
    попытка сначала переименовывается в уникальное мусорное имя, только
    потом удаляется (round-fix-2/5: было прямое `rmtree` — два параллельных
    сборщика, наткнувшись на одну и ту же брошенную папку одновременно,
    сносили бы её вдвоём); `FileExistsError` повторного `mkdir` — никогда
    не наружу голым, всегда «сборка уже идёт»."""

    staging = _staging_dir(paths, version)
    try:
        staging.mkdir(parents=True)
        return staging
    except FileExistsError:
        pass
    age = _age(staging)
    if age is not None and age < STAGING_MAX_AGE:
        raise MontageError(f"сборка версии {version} уже идёт")
    trash = _trash_name(staging)
    try:
        os.rename(staging, trash)
    except OSError:
        pass  # кто-то другой уже сносит ту же брошенную попытку — не наша забота
    else:
        shutil.rmtree(trash, ignore_errors=True)
    try:
        staging.mkdir(parents=True)
    except FileExistsError as error:
        raise MontageError(f"сборка версии {version} уже идёт") from error
    return staging


def reserve_version(paths: MontagePaths, recorded_ids: Iterable[str] = ()) -> str:
    """Выбирает следующий свободный vNNN и сразу резервирует его одним
    вызовом — задача 15 зовёт это ДО рендера, не `next_version_id` и
    резервацию раздельно: иначе между выбором номера и резервацией мог
    вклиниться параллельный вызов и выбрать тот же номер. Если выбранный
    номер уже свежо зарезервирован кем-то другим — «сборка уже идёт», а не
    следующий номер: пропуски в нумерации нежелательны, и решать, кто был
    первым, не наша забота."""

    from .versions import next_version_id  # см. докстринг модуля — обратная зависимость

    version = next_version_id(paths, recorded_ids)
    _reserve(paths, version)
    return version


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def stage_version(paths: MontagePaths, meta: "VersionMeta", model: "Model") -> Path:
    if paths.version_dir(meta.version).exists():
        raise MontageError(f"версия {meta.version} уже есть — версии не перезаписываются")
    staging = _reserve(paths, meta.version)
    try:
        shutil.copy2(paths.index, staging / "index.html")
        _write_json(staging / "meta.json", meta.to_dict())
        _write_json(staging / "model.json", model.to_dict())
    except BaseException:
        # Резервация освобождается сразу, а не через час ожидания (round-fix-2/5,
        # item 4): повторный stage_version той же версии не должен спотыкаться о
        # обломок неудачной попытки.
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return staging


def publish_version(paths: MontagePaths, staging: Path, version_id: str) -> Path:
    final = paths.version_dir(version_id)
    os.rename(staging, final)
    return final


def discard_staging(staging: Path) -> None:
    shutil.rmtree(staging, ignore_errors=True)


def recover_published_from_staging(paths: MontagePaths, version_id: str) -> Path | None:
    """Если `state` уже знает о версии vNNN, а на диске есть только её
    `.vNNN.staging` со снимком, дописанным целиком (сборка не дожила до
    `publish_version` — процесс оборвался между записью снимка и
    переименованием), публикует его тем же переименованием, без пересборки.
    НЕполный снимок (упавшая на середине сборка) не публикует — возвращает
    `None`, ничего не трогая; уже опубликованную версию — тоже `None`.

    Куда звать: задача 15 — сразу после `montage build`, если сама сборка
    оборвалась до `publish_version`, и в начале `montage status`/`montage
    build` следующего запуска, на случай прошлого обрыва."""

    if paths.version_dir(version_id).is_dir():
        return None
    staging = _staging_dir(paths, version_id)
    if not all((staging / name).is_file() for name in ("index.html", "meta.json", "model.json")):
        return None
    return publish_version(paths, staging, version_id)
