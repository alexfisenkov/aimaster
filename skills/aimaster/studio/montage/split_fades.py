"""Плавные края на месте разреза: и CLI, и Studio (проба 0.8.75) при `split`
копируют `data-fade-in`/`data-fade-out` и класс `am-fade-in` целиком на обе
половины — тот же приём, что для остальных атрибутов, которых split не должен
трогать сам. На стыке сцен эти края нужны, на месте внутреннего разреза — нет:
левая половина больше не кончается на границе сцены (убираем `data-fade-out`),
правая больше не начинается с неё (убираем `data-fade-in` и класс `am-fade-in`).

Пара «левая/правая половина» узнаётся по разметке, не по тому, кто её только
что создал: тот же исходник (`data-am-asset` — если титр, то текст) и смежные
без зазора тайминг и `data-media-start`, в пределах одного кадра. Поэтому
функция чистая и годится и для наших правок, и для разреза, сделанного мышью
в Studio (задача 15 зовёт её перед lint/render)."""

from __future__ import annotations

from .html_doc import element_attrs, set_attr

# Единой частоты кадров у композиции пока нет (титры и «внешние» видео могут
# отличаться) — берём консервативное 1/30 с: тестовые клипы навыка кодируются
# на 30 кадрах в секунду (montage_testkit.make_clip), а более редкий монтаж
# только выигрывает от чуть более широкого допуска.
ONE_FRAME = 1 / 30


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _same_source(left: dict, right: dict) -> bool:
    left_source = left.get("data-am-asset") or left.get("src")
    right_source = right.get("data-am-asset") or right.get("src")
    if left_source or right_source:
        return bool(left_source) and left_source == right_source
    # титр: своего ассета нет, опознаём по совпадающему тексту обеих половин
    return left.get("_tag") == "div" and right.get("_tag") == "div" and left.get("_text") == right.get("_text")


def _contiguous(left: dict, right: dict) -> bool:
    if not _same_source(left, right):
        return False
    left_start, left_duration = _num(left.get("data-start")), _num(left.get("data-duration"))
    right_start = _num(right.get("data-start"))
    if None in (left_start, left_duration, right_start):
        return False
    if abs(right_start - (left_start + left_duration)) > ONE_FRAME:
        return False
    left_media = _num(left.get("data-media-start")) or 0.0
    right_media = _num(right.get("data-media-start")) or 0.0
    return abs(right_media - (left_media + left_duration)) <= ONE_FRAME


def normalize_split_fades(text: str) -> tuple[str, list[str]]:
    """Снимает внутренний `data-fade-out` слева и `data-fade-in`/`am-fade-in`
    справа на каждом найденном стыке разреза. Идемпотентна: повторный вызов
    на уже нормализованном тексте возвращает его же и пустой список."""

    attrs = element_attrs(text)
    ids = sorted(attrs)
    changed: list[str] = []
    for left_id in ids:
        left = attrs[left_id]
        for right_id in ids:
            if right_id == left_id:
                continue
            right = attrs[right_id]
            if not _contiguous(left, right):
                continue
            left_dirty = "data-fade-out" in left
            right_classes = right.get("class", "").split()
            right_dirty = "data-fade-in" in right or "am-fade-in" in right_classes
            if left_dirty:
                text = set_attr(text, left_id, "data-fade-out", None)
                changed.append(left_id)
            if right_dirty:
                text = set_attr(text, right_id, "data-fade-in", None)
                kept = " ".join(name for name in right_classes if name != "am-fade-in")
                text = set_attr(text, right_id, "class", kept)
                changed.append(right_id)
    return text, changed
