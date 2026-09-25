"""Черновой монтаж в <проект>/montage/current: создать, пересобрать.

Обновление устаревших клипов (`refresh.refresh_draft`) и сравнение с
проектом (`stale.stale_clips`) — в отдельных модулях, отдельно от сборки:
разные поводы меняться (fix round 2/5 ruling item 1, round 3/5 item 3)."""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import MontageError
from .canvas import Canvas, canvas_for
from .draft_html import render_draft_html
from .draft_plan import plan_draft
from .engine import tools_prefix
from .index_io import write_index, write_text_atomic
from .media_sync import sync_media
from .paths import MontagePaths
from .probe import MediaInfo, probe_media
from .typeface import sync_fonts
from .vendor import copy_gsap, gsap_sources

HYPERFRAMES_CONFIG = {"media": {"autoProxy": True}}


@dataclass(frozen=True)
class DraftResult:
    canvas: Canvas
    duration: float
    clips: int
    media: dict


def media_prober(resolve, probe):
    """Кеширует `probe(resolve(asset_id))` по asset_id — один и тот же
    ассет в плане (видео и его же звук, повтор клипа) пробуется раз, а не
    на каждое обращение. Публичная: тем же кешем пользуется `refresh.py`."""

    cache: dict[str, MediaInfo] = {}

    def media(asset_id: str) -> MediaInfo:
        if asset_id not in cache:
            cache[asset_id] = probe(resolve(asset_id))
        return cache[asset_id]
    return media


def _gsap_prefix(engine_prefix) -> Path:
    """Папка движка, из которой черновик берёт GSAP (по умолчанию — та же,
    что у engine.locate); без GSAP закреплённой версии — MontageError с
    командой установки (vendor.py) до первой записи на диск."""

    prefix = Path(engine_prefix) if engine_prefix is not None else tools_prefix()
    gsap_sources(prefix)
    return prefix


def build_current(paths: MontagePaths, state: dict, resolve: Callable[[str], Path], *,
                  probe=probe_media, engine_prefix: Path | None = None) -> DraftResult:
    prefix = _gsap_prefix(engine_prefix)
    media = media_prober(resolve, probe)
    plan = plan_draft(state, media)
    first = plan.first_video_asset()
    canvas = canvas_for(media(first) if first else None)
    scripts = copy_gsap(prefix, paths.assets)
    synced = sync_media(((asset, resolve(asset)) for asset in plan.media_assets()), paths.assets)
    sources = {asset: item["src"] for asset, item in synced.items()}
    sync_fonts(paths.assets)
    write_text_atomic(paths.current / "hyperframes.json",
                      json.dumps(HYPERFRAMES_CONFIG, indent=2) + "\n")
    write_index(paths.index, render_draft_html(plan, canvas, sources, scripts))
    return DraftResult(canvas, plan.duration, len(plan.clips), synced)


def create_draft(paths, state, resolve, *, probe=probe_media, engine_prefix=None) -> DraftResult:
    if paths.index.exists():
        raise MontageError("черновик уже есть: montage draft --refresh заменит устаревшие клипы, "
                           "--rebuild соберёт его заново")
    return build_current(paths, state, resolve, probe=probe, engine_prefix=engine_prefix)


def rebuild_draft(paths, state, resolve, *, probe=probe_media,
                  engine_prefix=None) -> tuple[DraftResult, Path | None]:
    """Черновик заново из проекта. Прежний current/index.html (с правками из стола)
    не теряется: он уходит в .undo/before-rebuild-*.html, путь — вторым элементом."""

    prefix = _gsap_prefix(engine_prefix)
    backup = None
    if paths.index.is_file():
        try:
            paths.undo.mkdir(parents=True, exist_ok=True)
            backup = paths.undo / (f"before-rebuild-{time.strftime('%Y%m%d-%H%M%S')}"
                                   f"-{time.time_ns() % 1_000_000_000:09d}.html")
            shutil.copy2(paths.index, backup)
        except OSError as error:
            raise MontageError(f"не удалось сохранить прежний черновик в .undo: {error}") from error
    return build_current(paths, state, resolve, probe=probe, engine_prefix=prefix), backup
