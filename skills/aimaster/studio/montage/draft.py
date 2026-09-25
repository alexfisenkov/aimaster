"""Черновой монтаж в <проект>/montage/current: создать, обновить устаревшие клипы, пересобрать."""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..platform_compat import replace_file
from . import AUDIO_LAYER_NAMES, MontageError
from .canvas import Canvas, canvas_for
from .draft_html import render_draft_html
from .draft_plan import TRANSITION, VIDEO_VOLUME, audio_sources, plan_draft, video_sources
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

    `newline=""` — пишет `text` как есть, без перевода: свежий черновик
    собран с `\\n` и получит `\\n`, а `refresh_draft`, прочитавший файл
    Studio с CRLF тем же режимом, вернёт CRLF, не перегонит весь файл в LF
    ради правки нескольких атрибутов.

    Сбой файловой системы на любом шаге (нет прав, диск занят другим
    процессом на Windows, диск полон) — MontageError с понятным текстом, а не
    голый traceback; временный файл за собой не оставляем."""

    path = Path(path)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(text, encoding="utf-8", newline="")
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
    """Клипы, чей исходник разошёлся с текущим проектом. Три причины,
    только первую правит `refresh_draft` (`reason` не задан или None):

    - протух — сцена/слой сейчас указывают на другой принятый результат:
      `current_asset_id` заполнен, есть на что заменить исходник;
    - «нет принятого» — сцена/слой сейчас не указывают ни на один принятый
      результат (отклонили, отправили в архив, скрыли, отменили выбор):
      менять не на что, но пользователь должен это увидеть;
    - «нужен --rebuild» — структурная перемена, которую точечная правка не
      берёт: сцена исчезла или появилась с момента черновика, либо сменился
      gen_mode (per_scene ⇄ one_shot). У добавленной сцены своего клипа в
      черновике ещё нет — `clip` в её записи `None`.

    Титры (задача 14, `montage edit`) сюда не относятся — у них нет
    выбранного результата, который можно принять/отклонить, поэтому слой
    "titles" (и любой, кроме video/аудио) не трогаем вовсе."""

    wanted_video = {scene["scene_id"] if scene else None: asset
                    for scene, asset in video_sources(state, strict=False)}
    wanted_audio = audio_sources(state)
    scene_ids_now = {scene["scene_id"] for scene in state.get("scenes", [])}
    one_shot_now = state.get("gen_mode", "per_scene") == "one_shot"

    stale, seen_scenes = [], set()
    for clip_id, attrs in element_attrs(html_text).items():
        layer, asset = attrs.get("data-am-layer"), attrs.get("data-am-asset")
        if not layer or not asset or layer not in ("video", *AUDIO_LAYER_NAMES):
            continue
        scene = attrs.get("data-am-scene") or None
        if layer == "video":
            seen_scenes.add(scene)
            structural = (scene is not None and scene not in scene_ids_now) or (
                (scene is None) != one_shot_now)
            if structural:
                stale.append({"clip": clip_id, "layer": layer, "scene_id": scene, "asset_id": asset,
                              "current_asset_id": None, "reason": "нужен --rebuild"})
                continue
            current = wanted_video.get(scene)
        else:
            current = wanted_audio.get(layer)
        if current is None:
            stale.append({"clip": clip_id, "layer": layer, "scene_id": scene, "asset_id": asset,
                          "current_asset_id": None, "reason": "нет принятого"})
        elif current != asset:
            stale.append({"clip": clip_id, "layer": layer, "scene_id": scene, "asset_id": asset,
                          "current_asset_id": current, "reason": None})
    if not one_shot_now:
        for scene_id in sorted(scene_ids_now - seen_scenes):
            stale.append({"clip": None, "layer": "video", "scene_id": scene_id, "asset_id": None,
                          "current_asset_id": None, "reason": "нужен --rebuild"})
    return stale


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


def refresh_draft(paths, state, resolve, *, probe=probe_media) -> list[dict]:
    """Меняет исходник только у устаревших клипов (`reason` не задан). Место
    на дорожке не трогает; если новый исходник короче — укорачивает клип до
    его длины; если звук появился/пропал — приводит muted/громкость/fade к
    тому же виду, что дал бы свежий черновик. Клипы с «нет принятого» и
    «нужен --rebuild» возвращаются в списке, но их не трогает: точечная
    правка сюда не дотягивается."""

    if not paths.index.exists():
        raise MontageError("черновика ещё нет: сначала montage draft")
    try:
        text = paths.index.read_text(encoding="utf-8", newline="")
    except (OSError, UnicodeDecodeError) as error:
        raise MontageError(f"не удалось прочитать черновик: {error}") from error
    stale = stale_clips(text, state)
    refreshable = [item for item in stale if item.get("clip") and item.get("current_asset_id")]
    if not refreshable:
        return stale
    media = _prober(resolve, probe)
    synced = sync_media(((item["current_asset_id"], resolve(item["current_asset_id"]))
                         for item in refreshable), paths.assets)
    under_layers = bool(audio_sources(state))
    for item in refreshable:
        clip, asset = item["clip"], item["current_asset_id"]
        info = media(asset)
        attrs = element_attrs(text)[clip]
        media_start = float(attrs.get("data-media-start") or 0)
        if media_start >= info.duration:
            media_start = 0.0
            text = set_attr(text, clip, "data-media-start", "0")
        text = set_attr(text, clip, "src", synced[asset]["src"])
        text = set_attr(text, clip, "data-am-asset", asset)
        if float(attrs.get("data-duration") or 0) > info.duration - media_start:
            text = set_attr(text, clip, "data-duration", fmt_number(info.duration - media_start))
        if item["layer"] == "video":
            text, change = _restate_video_audio(text, clip, info, under_layers)
            if change:
                item["audio_change"] = change
    write_text_atomic(paths.index, text)
    return stale
