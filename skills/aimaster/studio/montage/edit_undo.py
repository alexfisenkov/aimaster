"""Откат правок агента: снимок index.html до правки и отметка после неё.

Перед каждой правкой current/index.html копируется в .undo/edit-<время>.html,
после неё рядом пишется .json с хэшем получившегося файла. `undo` возвращает
последний снимок, только если файл с тех пор не меняли (например, мышью в
монтажном столе). Откатить можно `UNDO_DEPTH` последних правок: более старые
снимки с отметками удаляются."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from . import MontageError
from .index_io import read_index, write_index
from .paths import MontagePaths

UNDO_DEPTH = 50


def _sha(path: Path) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError as error:
        raise MontageError(f"не удалось прочитать {Path(path).name} монтажа") from error


def snapshot_before(paths: MontagePaths) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{time.time_ns() % 1_000_000_000:09d}"
    target = paths.undo / f"edit-{stamp}.html"
    try:
        paths.undo.mkdir(parents=True, exist_ok=True)
        target.write_bytes(paths.index.read_bytes())
    except OSError as error:
        target.unlink(missing_ok=True)
        raise MontageError("не удалось сохранить снимок для отката в montage/.undo (нет доступа "
                           "или диск занят) — правка не сделана") from error
    return target


def write_note(paths: MontagePaths, snapshot: Path, op: str) -> None:
    """Отметка «каким стал index.html после правки». Без неё undo откажет,
    поэтому не записалась — правка возвращается назад."""

    try:
        snapshot.with_suffix(".json").write_text(
            json.dumps({"after": _sha(paths.index), "op": op}), encoding="utf-8")
    except (OSError, MontageError) as error:
        write_index(paths.index, read_index(snapshot))
        snapshot.unlink(missing_ok=True)
        raise MontageError("не удалось записать отметку для отката в montage/.undo — правка "
                           "отменена, монтаж прежний") from error


def _edit_snapshots(paths: MontagePaths) -> list[Path]:
    """Снимки правок по порядку: имя начинается со времени создания."""

    return sorted(paths.undo.glob("edit-*.html")) if paths.undo.is_dir() else []


def prune_snapshots(paths: MontagePaths) -> None:
    """Снимки старше UNDO_DEPTH последних — вместе с отметками. Последний, по
    которому работает undo, всегда в числе оставленных."""

    for old in _edit_snapshots(paths)[:-UNDO_DEPTH]:
        for path in (old, old.with_suffix(".json")):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass  # уборка не мешает правке, которая уже сделана


def undo_last(paths: MontagePaths) -> dict:
    snapshots = _edit_snapshots(paths)
    if not snapshots:
        raise MontageError("отменять нечего")
    latest, note = snapshots[-1], snapshots[-1].with_suffix(".json")
    # Нет отметки или она повреждена — нельзя проверить, что монтаж с тех пор
    # не трогали (например, мышью в столе): отказ, а не откат наугад.
    try:
        data = json.loads(note.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise MontageError("нет отметки о состоянии после последней правки — откат мог бы "
                           "стереть чужие изменения, поэтому отменён") from None
    # Валидный JSON, но не объект (список, число, строка, null) — тоже повреждена.
    after = data.get("after") if isinstance(data, dict) else None
    if not isinstance(after, str) or not after:
        raise MontageError("отметка о последней правке повреждена — откат мог бы стереть "
                           "чужие изменения, поэтому отменён")
    if after != _sha(paths.index):
        raise MontageError("после этой правки монтаж меняли (например, в монтажном столе) — "
                           "откат стёр бы и те изменения")
    write_index(paths.index, read_index(latest))
    try:
        note.unlink(missing_ok=True)
        latest.unlink()
    except OSError as error:
        raise MontageError(f"монтаж возвращён к снимку, но сам снимок {latest.name} в montage/.undo "
                           "удалить не удалось (нет доступа или файл занят)") from error
    return {"ok": True, "restored": latest.name}
