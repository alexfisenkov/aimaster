"""Что изменилось с версии: модель её снимка и строки diff — общее для сборки
(`render.py`) и `service.diff`. Потерянный снимок (state версию знает, папки
на диске нет) не блокирует ни сборку, ни diff: сравниваем «ни с чем» и прямо
говорим об этом."""

from __future__ import annotations

from typing import Mapping

from . import MontageError
from .model import Model
from .model_diff import diff_models
from .montage_format import clips_count, fmt_len
from .versions import read_version_model


def base_model(paths, version_id: str | None) -> tuple[Model | None, bool]:
    """(модель снимка версии, снимок потерян)."""

    if version_id is None:
        return None, False
    try:
        return read_version_model(paths, version_id), False
    except MontageError:
        return None, True


def changes_since(version_id: str | None, old: Model | None, lost: bool, model: Model,
                  names: Mapping[str, str]) -> list[str]:
    if lost:
        return [f"снимка прежней версии {version_id} нет на диске — изменения сравнить не с чем; "
                f"в монтаже {clips_count(len(model.clips))}, {fmt_len(model.duration)}"]
    return diff_models(old, model, names=names)
