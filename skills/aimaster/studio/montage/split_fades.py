"""Плавные края на месте разреза: и CLI, и Studio (проба 0.8.75) при `split`
копируют `data-fade-in`/`data-fade-out` и класс `am-fade-in` целиком на обе
половины — тот же приём, что для остальных атрибутов, которых split не должен
трогать сам. На стыке сцен эти края нужны, на месте внутреннего разреза — нет:
левая половина больше не кончается на границе сцены (убираем `data-fade-out`),
правая больше не начинается с неё (убираем `data-fade-in` и класс `am-fade-in`).

Пара «половина слева/справа» узнаётся общим правилом `split_pairs.
is_split_pair`, не тем, кто её только что создал — поэтому функция чистая и
годится и для наших правок, и для разреза, сделанного мышью в Studio.

Задача 15 (перед lint/render, на разрезе, сделанном мышью в Studio — наш
собственный путь правок его не видит): звать ТОЛЬКО со scoped `only` —
`normalize_split_fades(text, only=<id правых половин, которых нет в модели
последней версии>)`, никогда без `only` вовсе. Без него функция чистит ЛЮБУЮ
подходящую пару во всём документе, включая ту, что человек мог осмысленно
поправить руками между версиями (round-fix-2/5, item 1 — тот же риск, что и
у `edit_ops.split()`, только edit_ops сам знает свои новые id, а задача 15
узнаёт их сравнением с моделью прошлой версии, не diff'ом текста).
"""

from __future__ import annotations

from typing import Iterable

from .html_doc import element_attrs, set_attr
from .split_pairs import SplitMark, is_split_pair


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mark(attrs: dict) -> SplitMark | None:
    start, duration = _num(attrs.get("data-start")), _num(attrs.get("data-duration"))
    if start is None or duration is None:
        return None
    tag = attrs.get("_tag")
    layer = attrs.get("data-am-layer") or ("titles" if tag == "div" else tag or "")
    # round-fix-3/5, item E: тот же запасной атрибут, что читает model.py —
    # `data-playback-start`, если `data-media-start` нет вовсе (model.py:94).
    media = attrs.get("data-media-start")
    if media is None:
        media = attrs.get("data-playback-start")
    return SplitMark(layer=layer, asset_id=attrs.get("data-am-asset") or None,
                     src=attrs.get("src") or None, text=attrs.get("_text") or None,
                     start=start, duration=duration, media_start=_num(media) or 0.0)


def normalize_split_fades(text: str, only: Iterable[str] | None = None) -> tuple[str, list[str]]:
    """Снимает внутренний `data-fade-out` слева и `data-fade-in`/`am-fade-in`
    справа на каждом найденном стыке разреза. Идемпотентна: повторный вызов
    на уже нормализованном тексте возвращает его же и пустой список.

    `only` — id правых половин, которые вообще рассматривать (round-fix-2/5,
    item 1): без него функция чистит ЛЮБУЮ подходящую пару во всём документе,
    что при разрезе одного клипа задевало и чужой, случайно оказавшийся
    смежным по разметке; `edit_ops.split()` передаёт сюда только пары,
    которые создал сам вызов."""

    attrs = element_attrs(text)
    ids = sorted(attrs)
    scope = None if only is None else set(only)
    changed: list[str] = []
    for left_id in ids:
        left = _mark(attrs[left_id])
        if left is None:
            continue
        for right_id in ids:
            if right_id == left_id or (scope is not None and right_id not in scope):
                continue
            right = _mark(attrs[right_id])
            if right is None or not is_split_pair(left, right):
                continue
            left_attrs, right_attrs = attrs[left_id], attrs[right_id]
            if "data-fade-out" in left_attrs:
                text = set_attr(text, left_id, "data-fade-out", None)
                changed.append(left_id)
            right_classes = right_attrs.get("class", "").split()
            has_fade_in_attr = "data-fade-in" in right_attrs
            has_fade_in_class = "am-fade-in" in right_classes
            if has_fade_in_attr:
                text = set_attr(text, right_id, "data-fade-in", None)
            if has_fade_in_class:
                # round-fix-2/5, item 2: класс переписываем, только если он
                # действительно нёс am-fade-in — иначе на элементе без class
                # вовсе (типично для <audio>) появлялся бы пустой class="".
                kept = " ".join(name for name in right_classes if name != "am-fade-in")
                text = set_attr(text, right_id, "class", kept or None)
            if has_fade_in_attr or has_fade_in_class:
                changed.append(right_id)
    return text, changed
