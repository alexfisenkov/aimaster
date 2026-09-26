"""Правка монтажа агентом: проверка «монтаж не менялся», одна операция, снимок
для отката до неё и отметка после (`edit_undo`)."""

from __future__ import annotations

from dataclasses import dataclass

from . import MontageError
from .edit_ops import CLIP_OPS, need, title_add
from .edit_undo import prune_snapshots, snapshot_before, undo_last, write_note
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
    snapshot = snapshot_before(paths)
    try:
        receipt = title_add(ctx, request) if clip is None else CLIP_OPS[request.op](ctx, clip, request)
    except BaseException:
        write_index(paths.index, read_index(snapshot))
        snapshot.unlink(missing_ok=True)
        raise
    write_note(paths, snapshot, request.op)
    prune_snapshots(paths)
    after = read_model(engine, paths.current, cache_dir=paths.cache, runner=ctx.runner)
    return {"op": request.op, "clip": request.clip, "model_hash_before": before,
            "model_hash": model_hash(after), "duration": after.duration, "receipt": receipt}
