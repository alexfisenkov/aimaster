"""Единое правило «эта пара — половины одного разреза».

Round-fix-2/5, item 3: `split_fades.py` (правит разметку) и `model_diff.py`
(рассказывает человеку) раньше держали каждый своё определение, и они успели
разойтись (`split_fades` уже сверял `data-media-start`, `model_diff` — ещё
нет). Здесь оно одно, и оба места приводят своё представление клипа
(словарь `element_attrs` или `model.Clip`) к общему `SplitMark` перед
сравнением.

Опознаётся по разметке, не по тому, кто её только что создал: тот же
`data-am-asset`, а если его нет хотя бы с одной стороны (Studio могла
перетащить новый файл, не проставив нашу метку) — тот же `src`; у титра нет
ни того, ни другого — по совпадающему тексту обеих половин (CLI и Studio
копируют его на разрез целиком, как и остальные атрибуты). Плюс — соседние
по времени и по `data-media-start`, в пределах одного кадра.
"""

from __future__ import annotations

from dataclasses import dataclass

# Общей частоты кадров у композиции нет — тестовые клипы навыка кодируются
# на 30 к/с (montage_testkit.make_clip), более редкий монтаж только
# выигрывает от чуть более широкого допуска.
ONE_FRAME = 1 / 30


@dataclass(frozen=True)
class SplitMark:
    """Общее описание клипа для сравнения «пара разреза» — ни `model.Clip`,
    ни словарь `element_attrs` сюда не годятся напрямую, оба места приводят
    своё представление к этому перед вызовом `is_split_pair`."""

    layer: str
    asset_id: str | None
    src: str | None
    text: str | None
    start: float
    duration: float
    media_start: float

    @property
    def end(self) -> float:
        return self.start + self.duration


def same_source(left: SplitMark, right: SplitMark) -> bool:
    if left.asset_id and right.asset_id:
        return left.asset_id == right.asset_id
    if left.src and right.src:
        return left.src == right.src
    return left.layer == "titles" and right.layer == "titles" and left.text == right.text


def is_split_pair(left: SplitMark, right: SplitMark) -> bool:
    """`right` — та часть, что могла появиться разрезом `left`: `left`
    теперь кончается там, где начинается `right`, и `right` продолжает
    исходник `left` с того места, на котором тот остановился."""

    if left.layer != right.layer or not same_source(left, right):
        return False
    if abs(right.start - left.end) > ONE_FRAME:
        return False
    return abs(right.media_start - (left.media_start + left.duration)) <= ONE_FRAME
