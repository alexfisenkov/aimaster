"""Что изменилось с версии: модель её снимка и строки diff — общее для сборки
(`render.py`) и `service.diff`. Потерянный или повреждённый снимок (state
версию знает, а на диске модели нет или она не читается) не блокирует ни
сборку, ни diff: сравниваем «ни с чем» и прямо говорим, что случилось."""

from __future__ import annotations

from typing import Mapping

from . import MontageError
from .model import Model
from .model_diff import diff_models
from .montage_format import clips_count, fmt_len
from .paths import VERSION_ID
from .versions import read_version_model

MISSING, CORRUPT = "missing", "corrupt"


def base_model(paths, version_id: str | None) -> tuple[Model | None, str | None]:
    """(модель снимка версии, беда со снимком: None | MISSING | CORRUPT)."""

    if version_id is None:
        return None, None
    if not VERSION_ID.fullmatch(str(version_id)):
        return None, CORRUPT
    if not (paths.version_dir(version_id) / "model.json").is_file():
        return None, MISSING
    try:
        return read_version_model(paths, version_id), None
    except MontageError:
        return None, CORRUPT


def changes_since(version_id: str | None, old: Model | None, problem: str | None, model: Model,
                  names: Mapping[str, str]) -> list[str]:
    if problem is None:
        return diff_models(old, model, names=names)
    what = (f"снимка прежней версии {version_id} нет на диске" if problem == MISSING
            else f"снимок прежней версии {version_id} повреждён")
    return [f"{what} — изменения сравнить не с чем; "
            f"в монтаже {clips_count(len(model.clips))}, {fmt_len(model.duration)}"]
