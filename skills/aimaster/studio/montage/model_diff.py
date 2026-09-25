"""Смысловой diff двух моделей монтажа: какая строка и когда появляется.
Русский текст самих строк — в `montage_format.py` (round-fix-3/5, item C).
Обрезка начала (сдвиг начала вместе с куском исходника) — одна строка,
разрез — одна строка, без «укорочен/добавлен»."""

from __future__ import annotations

from typing import Mapping

from . import LAYER_LABELS
from .model import Clip, Model
from .montage_format import (
    DEFAULT_VOLUME, EPS, clip_name, clips_count, fmt_len, fmt_len_precise, fmt_time,
    fmt_time_precise, needs_precise_display, volume_label)
from .split_pairs import SplitMark, is_split_pair


def _timing(old: Clip, new: Clip, name: str, split_parent: bool) -> list[str]:
    shift, head = new.start - old.start, new.media_start - old.media_start
    if abs(shift) > EPS and abs(head) > EPS and abs(shift - head) <= EPS:
        verb = "обрезано" if head > 0 else "возвращено"
        magnitude = abs(head)
        display = (fmt_len_precise(magnitude) if needs_precise_display(0.0, magnitude)
                   else fmt_len(magnitude))
        return [f"{name}: начало {verb} на {display}"]
    out = []
    if abs(shift) > EPS:
        if needs_precise_display(old.start, new.start):
            # 0,1 с не различает старое и новое — не молчать и не врать
            # «не изменилось», показать точный сдвиг (round-fix-2/5, item 5).
            direction = "вперёд" if shift > 0 else "назад"
            out.append(f"{name}: сдвинут на {fmt_len_precise(abs(shift))} {direction}")
        else:
            out.append(f"{name}: сдвинут {fmt_time(old.start)} → {fmt_time(new.start)}")
    if abs(head) > EPS:
        if needs_precise_display(old.media_start, new.media_start):
            out.append(f"{name}: из исходника берётся кусок с {fmt_time_precise(new.media_start)}")
        else:
            out.append(f"{name}: из исходника берётся кусок с {fmt_time(new.media_start)}")
    if abs(new.duration - old.duration) > EPS and not split_parent:
        verb = "укорочен" if new.duration < old.duration else "удлинён"
        if needs_precise_display(old.duration, new.duration):
            out.append(f"{name}: {verb} на {fmt_len_precise(abs(new.duration - old.duration))}")
        else:
            out.append(f"{name}: {verb} до {fmt_len(new.duration)}")
    return out


def _changed(old: Clip, new: Clip, name: str, split_parent: bool) -> list[str]:
    out = []
    if new.layer == "titles" and new.text != old.text:
        out.append(f"{name}: текст «{old.text}» → «{new.text}»")
    out += _timing(old, new, name, split_parent)
    old_volume = DEFAULT_VOLUME if old.volume is None else old.volume
    new_volume = DEFAULT_VOLUME if new.volume is None else new.volume
    if abs(old_volume - new_volume) > EPS:
        out.append(f"{name}: громкость {volume_label(old.volume)} → {volume_label(new.volume)}")
    for label, before, after in (("плавное появление звука", old.fade_in, new.fade_in),
                                 ("плавное затухание звука", old.fade_out, new.fade_out)):
        if abs(after - before) > EPS:
            if not after:
                out.append(f"{name}: {label} убрано")
            elif needs_precise_display(before, after):
                out.append(f"{name}: {label} {fmt_len_precise(after)}")
            else:
                out.append(f"{name}: {label} {fmt_len(after)}")
    if new.asset_id and old.asset_id and new.asset_id != old.asset_id:
        out.append(f"{name}: заменён исходник")
    if new.layer != old.layer:
        out.append(f"{name}: перенесён на дорожку «{LAYER_LABELS[new.layer]}»")
    return out


def _mark(clip: Clip) -> SplitMark:
    return SplitMark(layer=clip.layer, asset_id=clip.asset_id, src=clip.src, text=clip.text,
                     start=clip.start, duration=clip.duration, media_start=clip.media_start)


def _split_pieces(before: dict, after: dict) -> dict[str, str]:
    """{новая часть: клип, из которого она появилась} — по общему правилу
    `split_pairs.is_split_pair` (round-fix-2/5, item 3: раньше своё, чуть
    другое правило было в split_fades.py, и они успели разойтись). Родителем
    может быть и клип, переживший разрез с прошлой версии, и другая новая
    часть — второй разрез той же строки (A → A, A-2; затем A-2 → A-2, A-2-2)
    иначе на втором шаге не находил бы родителя вовсе и уходил в «добавлен»,
    а не «разрезан»."""

    pieces = {}
    for piece_id in sorted(after.keys() - before.keys()):
        piece = after[piece_id]
        piece_mark = _mark(piece)
        for parent_id in sorted(after.keys()):
            if parent_id == piece_id:
                continue
            parent = after[parent_id]
            if not is_split_pair(_mark(parent), piece_mark):
                continue
            was_before = before.get(parent_id)
            if was_before is not None and was_before.end < piece.end - EPS:
                continue  # раньше родитель был короче куска — совпадение, не разрез
            pieces[piece_id] = parent_id
            break
    return pieces


def diff_models(old: Model | None, new: Model, *, names: Mapping[str, str] | None = None) -> list[str]:
    names = names or {}
    if old is None:
        return [f"черновой монтаж: {clips_count(len(new.clips))}, {fmt_len(new.duration)}"]
    before = {clip.id: clip for clip in old.clips}
    after = {clip.id: clip for clip in new.clips}
    changes = []
    if abs(new.duration - old.duration) > EPS:
        if needs_precise_display(old.duration, new.duration):
            changes.append(f"длина ролика изменилась на {fmt_len_precise(abs(new.duration - old.duration))}")
        else:
            changes.append(f"длина ролика {fmt_len(old.duration)} → {fmt_len(new.duration)}")
    pieces = _split_pieces(before, after)
    for piece_id, parent_id in pieces.items():
        changes.append(f"{clip_name(after[parent_id], names)}: разрезан на {fmt_time(after[piece_id].start)}")
    changes += [f"добавлен {clip_name(clip, names)} с {fmt_time(clip.start)}"
                for clip in new.clips if clip.id not in before and clip.id not in pieces]
    changes += [f"удалён {clip_name(clip, names)}" for clip in old.clips if clip.id not in after]
    parents = set(pieces.values())
    for clip in new.clips:
        if clip.id in before:
            changes += _changed(before[clip.id], clip, clip_name(clip, names), clip.id in parents)
    return changes
