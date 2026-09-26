"""Обновление устаревших клипов существующего черновика.

Сравнение с проектом (что устарело и почему) — в `stale.py`, отдельно от
файлового I/O и правки атрибутов, которые здесь."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from . import MontageError
from .draft import media_prober
from .accepted_sources import audio_sources
from .draft_plan import TRANSITION, VIDEO_VOLUME
from .html_doc import element_attrs, fmt_number, set_attr
from .index_io import read_index, write_index
from .media_sync import sync_media
from .probe import MediaInfo, probe_media
from .stale import stale_clips


def _restate_video_audio(text: str, clip_id: str, info: MediaInfo, under_layers: bool
                         ) -> tuple[str, str | None]:
    """У обновлённого видео-клипа звук мог появиться или пропасть — приводит
    muted/data-has-audio/громкость/fade-края к тому же виду, что дал бы
    свежий черновик (VIDEO_VOLUME/TRANSITION), а не оставляет их от прежнего
    исходника. Возвращает (текст, что изменилось | None)."""

    was_muted = "muted" in element_attrs(text)[clip_id]
    if info.has_audio and was_muted:
        is_first = clip_id == "v-1"
        text = set_attr(text, clip_id, "muted", None)
        text = set_attr(text, clip_id, "data-has-audio", "true")
        text = set_attr(text, clip_id, "data-volume", fmt_number(VIDEO_VOLUME[under_layers]))
        text = set_attr(text, clip_id, "data-fade-in", None if is_first else fmt_number(TRANSITION))
        text = set_attr(text, clip_id, "data-fade-out", fmt_number(TRANSITION))
        return text, "добавился звук"
    if not info.has_audio and not was_muted:
        text = set_attr(text, clip_id, "data-has-audio", None)
        text = set_attr(text, clip_id, "data-volume", None)
        text = set_attr(text, clip_id, "data-fade-in", None)
        text = set_attr(text, clip_id, "data-fade-out", None)
        text = set_attr(text, clip_id, "muted", True)
        return text, "пропал звук"
    return text, None


def _seconds(attrs: dict, name: str, clip: str) -> float:
    """Число секунд из атрибута клипа; пусто — 0. Не число — отказ по-русски."""

    value = attrs.get(name) or 0
    try:
        return float(value)
    except (TypeError, ValueError):
        raise MontageError(f"повреждённое значение {name} у клипа {clip}: «{str(value)[:40]}» — "
                           "поправьте его в монтаже или соберите черновик заново "
                           "(montage draft --rebuild)") from None


def refresh_draft(paths, state, resolve: Callable[[str], Path], *, probe=probe_media) -> list[dict]:
    """Меняет исходник только у устаревших клипов (`reason` не задан). Место
    на дорожке не трогает; если новый исходник короче — укорачивает клип до
    его длины; если звук появился/пропал — приводит muted/громкость/fade к
    тому же виду, что дал бы свежий черновик. Клипы с «нет принятого» и
    «нужен --rebuild» возвращаются в списке, но их не трогает: точечная
    правка сюда не дотягивается."""

    if not paths.index.exists():
        raise MontageError("черновика ещё нет: сначала montage draft")
    text = read_index(paths.index)
    stale = stale_clips(text, state)
    refreshable = [item for item in stale if item.get("clip") and item.get("current_asset_id")]
    if not refreshable:
        return stale
    media = media_prober(resolve, probe)
    synced = sync_media(((item["current_asset_id"], resolve(item["current_asset_id"]))
                         for item in refreshable), paths.assets)
    under_layers = bool(audio_sources(state))
    for item in refreshable:
        clip, asset = item["clip"], item["current_asset_id"]
        info = media(asset)
        attrs = element_attrs(text)[clip]
        media_start = _seconds(attrs, "data-media-start", clip)
        if media_start >= info.duration:
            media_start = 0.0
            text = set_attr(text, clip, "data-media-start", "0")
        text = set_attr(text, clip, "src", synced[asset]["src"])
        text = set_attr(text, clip, "data-am-asset", asset)
        if _seconds(attrs, "data-duration", clip) > info.duration - media_start:
            text = set_attr(text, clip, "data-duration", fmt_number(info.duration - media_start))
        if item["layer"] == "video":
            text, change = _restate_video_audio(text, clip, info, under_layers)
            if change:
                item["audio_change"] = change
    write_index(paths.index, text)
    return stale
