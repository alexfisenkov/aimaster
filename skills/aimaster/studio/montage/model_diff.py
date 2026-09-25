"""Смысловой diff двух моделей монтажа: строки по-русски, чтобы агент пересказал
человеку, что поменялось с прошлой сборки. Обрезка начала (сдвиг начала вместе с
куском исходника) — одна строка, разрез — одна строка, без «укорочен/добавлен»."""

from __future__ import annotations

from typing import Mapping

from . import LAYER_LABELS
from .model import Clip, Model

EPS = 0.01


def fmt_time(seconds: float) -> str:
    minutes, rest = divmod(max(0.0, float(seconds)), 60)
    return f"{int(minutes)}:{rest:04.1f}"


def fmt_len(seconds: float) -> str:
    return f"{float(seconds):.1f}".replace(".", ",") + " с"


def clips_count(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return f"{count} клип"
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return f"{count} клипа"
    return f"{count} клипов"


def clip_name(clip: Clip, names: Mapping[str, str]) -> str:
    if clip.layer == "titles":
        return f"титр «{clip.text or clip.id}»"
    if clip.layer == "video":
        scene = names.get(clip.scene_id) if clip.scene_id else None
        return f"клип {scene}" if scene else f"клип {clip.id}"
    return f"звук «{LAYER_LABELS[clip.layer]}» ({clip.id})"


def _timing(old: Clip, new: Clip, name: str, split_parent: bool) -> list[str]:
    shift, head = new.start - old.start, new.media_start - old.media_start
    if abs(shift) > EPS and abs(head) > EPS and abs(shift - head) <= EPS:
        verb = "обрезано" if head > 0 else "возвращено"
        return [f"{name}: начало {verb} на {fmt_len(abs(head))}"]
    out = []
    if abs(shift) > EPS:
        out.append(f"{name}: сдвинут {fmt_time(old.start)} → {fmt_time(new.start)}")
    if abs(head) > EPS:
        out.append(f"{name}: из исходника берётся кусок с {fmt_time(new.media_start)}")
    if abs(new.duration - old.duration) > EPS and not split_parent:
        verb = "укорочен" if new.duration < old.duration else "удлинён"
        out.append(f"{name}: {verb} до {fmt_len(new.duration)}")
    return out


def _changed(old: Clip, new: Clip, name: str, split_parent: bool) -> list[str]:
    out = []
    if new.layer == "titles" and new.text != old.text:
        out.append(f"{name}: текст «{old.text}» → «{new.text}»")
    out += _timing(old, new, name, split_parent)
    if new.volume is not None and abs((old.volume or 0) - new.volume) > EPS:
        out.append(f"{name}: громкость {round((old.volume or 0) * 100)}% → {round(new.volume * 100)}%")
    for label, before, after in (("плавное появление звука", old.fade_in, new.fade_in),
                                 ("плавное затухание звука", old.fade_out, new.fade_out)):
        if abs(after - before) > EPS:
            out.append(f"{name}: {label} {fmt_len(after)}" if after else f"{name}: {label} убрано")
    if new.asset_id and old.asset_id and new.asset_id != old.asset_id:
        out.append(f"{name}: заменён исходник")
    if new.layer != old.layer:
        out.append(f"{name}: перенесён на дорожку «{LAYER_LABELS[new.layer]}»")
    return out


def _split_pieces(before: dict, after: dict) -> dict[str, str]:
    """{новая часть: исходный клип}: часть начинается там, где исходный теперь кончается."""

    pieces = {}
    for piece_id in sorted(after.keys() - before.keys()):
        piece = after[piece_id]
        for parent_id in sorted(before.keys() & after.keys()):
            parent = after[parent_id]
            if piece.src and parent.src == piece.src and parent.layer == piece.layer \
                    and abs(parent.end - piece.start) <= EPS \
                    and before[parent_id].end >= piece.end - EPS:
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
