"""Операции правки поверх CLI HyperFrames, выровненные под Studio.

CLI и Studio расходятся (проба 0.8.75): `timeline trim --start` двигает начало
клипа, но не `data-media-start`, а Studio двигает и его; `move` за конец ролика
CLI отклоняет, а Studio удлиняет корень. Поэтому операция = вызов CLI + наша
точечная правка атрибутов с тем же результатом, что мышь в Studio.
"""

from __future__ import annotations

import re

from . import MontageError
from .draft_html import title_fragment
from .html_doc import (ROOT_ID, element_attrs, fmt_number as fmt, insert_before_root_end,
                       root_duration, set_attr, set_text)
from .index_io import read_index, write_index

CLI_TIMEOUT = 120
MAX_VOLUME = 3.98
_TITLE_ID = re.compile(r"t-(\d+)")


def need(value, flag: str, op: str):
    if value is None:
        raise MontageError(f"для правки {op} нужен --{flag}")
    return value


def cli(ctx, args) -> dict:
    return ctx.runner.json(ctx.engine, ["timeline", *args, "--dir", ".", "--json"],
                           cwd=ctx.paths.current, timeout=CLI_TIMEOUT)


def patch(ctx, change) -> None:
    write_index(ctx.paths.index, change(read_index(ctx.paths.index)))


def extend_root(ctx, end: float) -> None:
    patch(ctx, lambda text: set_attr(text, ROOT_ID, "data-duration", fmt(end))
          if end > root_duration(text) + 1e-6 else text)


def _sound_clip(clip, op: str) -> None:
    if clip.kind not in ("video", "audio"):
        raise MontageError(f"правка {op} — только для видео и звука, а {clip.id} — {clip.kind}")


def move(ctx, clip, req):
    at = need(req.at, "at", req.op)
    if at < 0:
        raise MontageError("начало клипа не может быть меньше нуля")
    extend_root(ctx, at + clip.duration)
    return cli(ctx, ["move", "#" + clip.id, fmt(at)])


def trim_start(ctx, clip, req):
    cut = need(req.seconds, "seconds", req.op)
    start, duration, media = clip.start + cut, clip.duration - cut, clip.media_start + cut
    if duration <= 0:
        raise MontageError("после обрезки от клипа ничего не останется")
    if start < 0 or (clip.kind in ("video", "audio") and media < 0):
        raise MontageError("вернуть больше, чем было срезано, нельзя")
    receipt = cli(ctx, ["trim", "#" + clip.id, "--start", fmt(start), "--duration", fmt(duration)])
    if clip.kind in ("video", "audio"):
        patch(ctx, lambda text: set_attr(text, clip.id, "data-media-start", fmt(media)))
    return receipt


def trim_end(ctx, clip, req):
    duration = need(req.duration, "duration", req.op)
    if duration <= 0:
        raise MontageError("длина клипа должна быть больше нуля")
    extend_root(ctx, clip.start + duration)
    return cli(ctx, ["trim", "#" + clip.id, "--duration", fmt(duration)])


def split(ctx, clip, req):
    at = need(req.at, "at", req.op)
    if not clip.start + 1e-3 < at < clip.end - 1e-3:
        raise MontageError(f"момент разреза должен быть внутри клипа ({clip.start}–{clip.end} с)")
    before = set(element_attrs(read_index(ctx.paths.index)))
    receipt = cli(ctx, ["split", "#" + clip.id, fmt(at)])
    after = element_attrs(read_index(ctx.paths.index))
    pieces = sorted(set(after) - before)
    for piece in pieces:
        classes = after[piece].get("class", "").split()
        if "am-fade-in" in classes:  # проявление нужно на стыке сцен, не на разрезе
            kept = " ".join(name for name in classes if name != "am-fade-in")
            patch(ctx, lambda text, p=piece, k=kept: set_attr(text, p, "class", k))
    return {**receipt, "new_clip": pieces[0] if pieces else None}


def delete(ctx, clip, req):
    return cli(ctx, ["delete", "#" + clip.id])


def volume(ctx, clip, req):
    value = need(req.value, "value", req.op)
    _sound_clip(clip, req.op)
    if not 0 <= value <= MAX_VOLUME:
        raise MontageError(f"громкость — от 0 до {MAX_VOLUME}")
    return cli(ctx, ["set", "#" + clip.id, f"volume={fmt(value)}"])


def fade(ctx, clip, req):
    _sound_clip(clip, req.op)
    if req.fade_in is None and req.fade_out is None:
        raise MontageError("для правки fade нужен --fade-in или --fade-out")
    for name, value in (("data-fade-in", req.fade_in), ("data-fade-out", req.fade_out)):
        if value is None:
            continue
        if not 0 <= value <= clip.duration:
            raise MontageError(f"плавный край — от 0 до длины клипа ({clip.duration} с)")
        patch(ctx, lambda text, n=name, v=value: set_attr(text, clip.id, n, fmt(v) if v > 0 else None))
    return {"ok": True}


def title_add(ctx, req):
    text = need(req.text, "text", req.op)
    start, duration = need(req.at, "at", req.op), need(req.duration, "duration", req.op)
    if not text.strip() or start < 0 or duration <= 0:
        raise MontageError("титру нужны текст, начало не меньше нуля и длина больше нуля")
    ids = element_attrs(read_index(ctx.paths.index))
    number = max((int(m.group(1)) for m in map(_TITLE_ID.fullmatch, ids) if m), default=0) + 1
    new_id = f"t-{number}"
    fragment = title_fragment(new_id, text, start, duration)
    extend_root(ctx, start + duration)
    patch(ctx, lambda current: insert_before_root_end(current, fragment))
    return {"ok": True, "new_clip": new_id}


def title_text(ctx, clip, req):
    text = need(req.text, "text", req.op)
    if clip.layer != "titles":
        raise MontageError(f"{clip.id} — не титр")
    patch(ctx, lambda current: set_text(current, clip.id, text))
    return {"ok": True}


CLIP_OPS = {"move": move, "trim-start": trim_start, "trim-end": trim_end, "split": split,
            "delete": delete, "volume": volume, "fade": fade, "title-text": title_text}
