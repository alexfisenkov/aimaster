"""Правка монтажа агентом: снимок для отката, проверка «монтаж не менялся», undo.

Перед каждой правкой current/index.html копируется в .undo/, после неё рядом
пишется хэш получившегося файла. `undo` возвращает последний снимок, только если
файл с тех пор не меняли (например, мышью в монтажном столе)."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

from . import MontageError
from .edit_ops import CLIP_OPS, need, title_add
from .engine import Engine
from .engine_cli import EngineRunner
from .index_io import read_index, write_index
from .model import model_hash, read_model
from .paths import MontagePaths

OPS = ("move", "trim-start", "trim-end", "split", "delete", "volume", "fade", "title-add",
       "title-text", "undo")


@dataclass(frozen=True)
class EditRequest:
    op: str
    clip: str | None = None
    at: float | None = None        # move — новое начало; split — момент; title-add — начало
    seconds: float | None = None   # trim-start — сколько срезать с начала (минус — вернуть)
    duration: float | None = None  # trim-end — новая длина; title-add — длина
    value: float | None = None     # volume — 0…3.98
    fade_in: float | None = None
    fade_out: float | None = None
    text: str | None = None


@dataclass(frozen=True)
class EditContext:
    engine: Engine
    paths: MontagePaths
    runner: object


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _snapshot(paths: MontagePaths) -> Path:
    paths.undo.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{time.time_ns() % 1_000_000_000:09d}"
    target = paths.undo / f"edit-{stamp}.html"
    target.write_bytes(paths.index.read_bytes())
    return target


def undo_last(paths: MontagePaths) -> dict:
    snapshots = sorted(paths.undo.glob("edit-*.html")) if paths.undo.is_dir() else []
    if not snapshots:
        raise MontageError("отменять нечего")
    latest, note = snapshots[-1], snapshots[-1].with_suffix(".json")
    # Гвардия — по умолчанию закрыта (round-fix-1/5, item 3): нет отметки или
    # она повреждена — значит нельзя проверить, что монтаж с тех пор не
    # трогали (например, мышью в столе); раньше это молча пропускало
    # проверку и стирало чужую правку, теперь — явный отказ.
    try:
        data = json.loads(note.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise MontageError("нет отметки о состоянии после последней правки — откат мог бы "
                           "стереть чужие изменения, поэтому отменён") from None
    # round-fix-2/5, item 6: валидный JSON, но не объект (список, число,
    # строка, null) — .get() на нём падал бы AttributeError'ом мимо отказа.
    after = data.get("after") if isinstance(data, dict) else None
    if not isinstance(after, str) or not after:
        raise MontageError("отметка о последней правке повреждена — откат мог бы стереть "
                           "чужие изменения, поэтому отменён")
    if after != _sha(paths.index):
        raise MontageError("после этой правки монтаж меняли (например, в монтажном столе) — "
                           "откат стёр бы и те изменения")
    write_index(paths.index, read_index(latest))
    latest.unlink()
    note.unlink(missing_ok=True)
    return {"ok": True, "restored": latest.name}


def apply_edit(engine: Engine, paths: MontagePaths, request: EditRequest, *,
               expected_model_hash: str | None = None, runner=None) -> dict:
    if request.op not in OPS:
        raise MontageError(f"неизвестная правка {request.op}; можно: {', '.join(OPS)}")
    if not paths.index.is_file():
        raise MontageError("черновика ещё нет: сначала montage draft")
    if request.op == "undo":
        return {"op": "undo", **undo_last(paths)}
    ctx = EditContext(engine, paths, runner or EngineRunner())
    model = read_model(engine, paths.current, cache_dir=paths.cache, runner=ctx.runner)
    before = model_hash(model)
    if expected_model_hash and expected_model_hash != before:
        raise MontageError("монтаж изменился с тех пор, как вы его читали (например, в монтажном "
                           "столе): прочитайте montage status и повторите")
    clip = None if request.op == "title-add" else model.clip(need(request.clip, "clip", request.op))
    snapshot = _snapshot(paths)
    try:
        receipt = title_add(ctx, request) if clip is None else CLIP_OPS[request.op](ctx, clip, request)
    except BaseException:
        write_index(paths.index, read_index(snapshot))
        snapshot.unlink(missing_ok=True)
        raise
    snapshot.with_suffix(".json").write_text(
        json.dumps({"after": _sha(paths.index), "op": request.op}), encoding="utf-8")
    after = read_model(engine, paths.current, cache_dir=paths.cache, runner=ctx.runner)
    return {"op": request.op, "clip": request.clip, "model_hash_before": before,
            "model_hash": model_hash(after), "duration": after.duration, "receipt": receipt}
