"""Черновой монтаж в <проект>/montage/current: создать, обновить устаревшие клипы, пересобрать."""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..platform_compat import replace_file
from . import MontageError
from .canvas import Canvas, canvas_for
from .draft_html import render_draft_html
from .draft_plan import audio_sources, plan_draft, video_sources
from .html_doc import element_attrs, fmt_number, set_attr
from .media_sync import sync_media
from .paths import MontagePaths
from .probe import MediaInfo, probe_media
from .typeface import sync_fonts

HYPERFRAMES_CONFIG = {"media": {"autoProxy": True}}


@dataclass(frozen=True)
class DraftResult:
    canvas: Canvas
    duration: float
    clips: int
    media: dict


def write_text_atomic(path: Path, text: str) -> None:
    """Пишет текстовый файл через временный + атомарную замену.

    Сбой файловой системы на любом шаге (нет прав, диск занят другим
    процессом на Windows, диск полон) — MontageError с понятным текстом, а не
    голый traceback; временный файл за собой не оставляем."""

    path = Path(path)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(text, encoding="utf-8", newline="\n")
        replace_file(temporary, path)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise MontageError(f"не удалось записать {path.name}: {error}") from error


def _prober(resolve, probe):
    cache: dict[str, MediaInfo] = {}

    def media(asset_id: str) -> MediaInfo:
        if asset_id not in cache:
            cache[asset_id] = probe(resolve(asset_id))
        return cache[asset_id]
    return media


def build_current(paths: MontagePaths, state: dict, resolve: Callable[[str], Path], *,
                  probe=probe_media) -> DraftResult:
    media = _prober(resolve, probe)
    plan = plan_draft(state, media)
    first = plan.first_video_asset()
    canvas = canvas_for(media(first) if first else None)
    synced = sync_media(((asset, resolve(asset)) for asset in plan.media_assets()), paths.assets)
    sources = {asset: item["src"] for asset, item in synced.items()}
    sync_fonts(paths.assets)
    write_text_atomic(paths.current / "hyperframes.json",
                      json.dumps(HYPERFRAMES_CONFIG, indent=2) + "\n")
    write_text_atomic(paths.index, render_draft_html(plan, canvas, sources))
    return DraftResult(canvas, plan.duration, len(plan.clips), synced)


def create_draft(paths, state, resolve, *, probe=probe_media) -> DraftResult:
    if paths.index.exists():
        raise MontageError("черновик уже есть: montage draft --refresh заменит устаревшие клипы, "
                           "--rebuild соберёт его заново")
    return build_current(paths, state, resolve, probe=probe)


def rebuild_draft(paths, state, resolve, *, probe=probe_media) -> tuple[DraftResult, Path | None]:
    """Черновик заново из проекта. Прежний current/index.html (с правками из стола)
    не теряется: он уходит в .undo/before-rebuild-*.html, путь — вторым элементом."""

    backup = None
    if paths.index.is_file():
        try:
            paths.undo.mkdir(parents=True, exist_ok=True)
            backup = paths.undo / (f"before-rebuild-{time.strftime('%Y%m%d-%H%M%S')}"
                                   f"-{time.time_ns() % 1_000_000_000:09d}.html")
            shutil.copy2(paths.index, backup)
        except OSError as error:
            raise MontageError(f"не удалось сохранить прежний черновик в .undo: {error}") from error
    return build_current(paths, state, resolve, probe=probe), backup


def stale_clips(html_text: str, state: dict) -> list[dict]:
    """Клипы, чей исходник уже не выбранный результат своей сцены или слоя."""

    wanted = {("video", scene["scene_id"] if scene else None): asset
              for scene, asset in video_sources(state, strict=False)}
    wanted.update({(layer, None): asset for layer, asset in audio_sources(state).items()})
    stale = []
    for clip_id, attrs in element_attrs(html_text).items():
        layer, asset = attrs.get("data-am-layer"), attrs.get("data-am-asset")
        if not layer or not asset:
            continue
        scene = attrs.get("data-am-scene") or None
        current = wanted.get((layer, scene if layer == "video" else None))
        if current and current != asset:
            stale.append({"clip": clip_id, "layer": layer, "scene_id": scene, "asset_id": asset,
                          "current_asset_id": current})
    return stale


def refresh_draft(paths, state, resolve, *, probe=probe_media) -> list[dict]:
    """Меняет исходник только у устаревших клипов. Место на дорожке не трогает;
    если новый исходник короче — укорачивает клип до его длины."""

    if not paths.index.exists():
        raise MontageError("черновика ещё нет: сначала montage draft")
    try:
        text = paths.index.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise MontageError(f"не удалось прочитать черновик: {error}") from error
    stale = stale_clips(text, state)
    if not stale:
        return []
    synced = sync_media(((item["current_asset_id"], resolve(item["current_asset_id"]))
                         for item in stale), paths.assets)
    for item in stale:
        clip, asset = item["clip"], item["current_asset_id"]
        info = probe(resolve(asset))
        attrs = element_attrs(text)[clip]
        media_start = float(attrs.get("data-media-start") or 0)
        if media_start >= info.duration:
            media_start = 0.0
            text = set_attr(text, clip, "data-media-start", "0")
        text = set_attr(text, clip, "src", synced[asset]["src"])
        text = set_attr(text, clip, "data-am-asset", asset)
        if float(attrs.get("data-duration") or 0) > info.duration - media_start:
            text = set_attr(text, clip, "data-duration", fmt_number(info.duration - media_start))
    write_text_atomic(paths.index, text)
    return stale
