"""Русское форматирование для смыслового diff монтажа: числа, склонения,
имена клипов, единицы звука. Отдельно от `model_diff.py` (round-fix-3/5,
item C): там — какая строка и когда вообще появляется в diff, здесь — как
она выглядит на экране. `EPS`/`DEFAULT_VOLUME` живут тут же — те же самые
допуски нужны и для решения «показывать ли строку», и для решения «как её
показать», одно число на обе задачи, не два синхронизируемых вручную.
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Mapping

from . import LAYER_LABELS
from .model import Clip

EPS = 0.01
# HyperFrames: клип без data-volume звучит на полной громкости — тот же
# умолчательный уровень, что draft_html пишет явно для каждого звукового слоя.
DEFAULT_VOLUME = 1.0


def _round1(value: float) -> Decimal:
    """Отображаемая точность — 0,1 с, всегда «к большему по модулю» (не к
    чётному, как режет банковское округление форматной строки Python)."""

    return Decimal(str(max(0.0, float(value)))).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def _round2(value: float) -> Decimal:
    return Decimal(str(max(0.0, float(value)))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def needs_precise_display(old: float, new: float) -> bool:
    """Правда, если старое и новое заметно различаются (>EPS), но при
    округлении до 0,1 с печатались бы одинаково — единая проверка для всех
    мест `model_diff.py`, что сравнивают старое и новое значение
    (round-fix-3/5, item D: длина ролика, сдвиг, длина клипа, затухание,
    сдвиг media_start и величина обрезки начала — раньше такая проверка
    была только у сдвига и длины клипа, и каждая своя, не общая)."""

    return abs(old - new) > EPS and _round1(old) == _round1(new)


def fmt_time(seconds: float) -> str:
    total = float(_round1(seconds))
    minutes, rest = divmod(total, 60)
    return f"{int(minutes)}:{rest:04.1f}"


def fmt_time_precise(seconds: float) -> str:
    """Точность 0,01 с в формате «м:сс.дд» — для media_start, когда 0,1 с
    не различает старое и новое значение (round-fix-3/5, item D)."""

    total = float(_round2(seconds))
    minutes, rest = divmod(total, 60)
    return f"{int(minutes)}:{rest:05.2f}"


def fmt_len(seconds: float) -> str:
    value = _round1(seconds)
    if value == 0 and abs(float(seconds)) > EPS:
        value = Decimal("0.1")  # меньше кадра показа — не «без изменений», а «меньше 0,1 с»
    return f"{value:.1f}".replace(".", ",") + " с"


def fmt_len_precise(seconds: float) -> str:
    """Точность 0,01 с — когда обычной 0,1 с не хватает различить старое и
    новое значение (round-fix-2/5, item 5): не «сдвинут 0:01.0 → 0:01.0»
    для сдвига на 0,03 с, который EPS уже посчитал реальным изменением."""

    return f"{_round2(seconds):.2f}".replace(".", ",") + " с"


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


def _db(fraction: float) -> str:
    # Округлённый Python отрицательный int форматируется ASCII-дефисом; знак
    # — настоящим минусом U+2212 везде (round-fix-2/5, item 8), не смесью.
    if fraction <= 0:
        return "−∞ дБ"
    value = round(20 * math.log10(fraction))
    return f"−{-value} дБ" if value < 0 else f"{value} дБ"


def volume_label(volume: float | None) -> str:
    fraction = DEFAULT_VOLUME if volume is None else volume
    return f"{round(fraction * 100)}% ({_db(fraction)})"
