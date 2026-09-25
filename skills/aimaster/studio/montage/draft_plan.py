"""Проект → план черновика: какие клипы, где, с какой громкостью (чистая функция).

Видео — по порядку сцен, каждый клип в окне своей сцены и не длиннее исходника;
выбранный результат берётся по указателю позиции (`current_member`), а не по
порядку списка. Звук — один текущий файл на слой от начала ролика. Переход —
проявление следующего клипа (CSS `@keyframes` в draft_html) и мягкие края его
звука (`data-fade-in/out` в HyperFrames — это громкость, не картинка).
Титров и надписей в черновике нет: текст сцены — описание кадра, а не реплика;
титры добавляет только `montage edit` (решение владельца 2026-09-25).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..domain import DomainValidationError
from ..domain_positions import current_member, position_specs
from . import AUDIO_LAYER_NAMES, MontageError
from .probe import MediaInfo

TRANSITION = 0.4
DEFAULT_VOLUMES = {"voice": 1.0, "music": 0.3, "fx": 0.8, "atmos": 0.5}
VIDEO_VOLUME = {False: 1.0, True: 0.3}  # без звуковых слоёв / под ними
LAYER_FADE_OUT = {"music": 1.0, "atmos": 1.0}


@dataclass(frozen=True)
class ClipPlan:
    clip_id: str
    layer: str
    start: float
    duration: float
    scene_id: str | None = None
    asset_id: str | None = None
    media_start: float = 0.0
    volume: float | None = None
    fade_in: float = 0.0
    fade_out: float = 0.0
    visual_fade: bool = False
    has_audio: bool = False


@dataclass(frozen=True)
class DraftPlan:
    duration: float
    clips: tuple[ClipPlan, ...]
    # Слепок структуры проекта на момент сборки: `stale_clips` (refresh.py)
    # пишет их на корень (data-am-scenes/data-am-gen-mode) и потом сравнивает
    # с текущим проектом — так отличает добавленную/удалённую сцену и смену
    # gen_mode от сцены, чей клип владелец сам убрал со стола.
    scene_ids: tuple[str, ...] = ()
    gen_mode: str = "per_scene"

    def media_assets(self) -> list[str]:
        return list(dict.fromkeys(clip.asset_id for clip in self.clips if clip.asset_id))

    def first_video_asset(self) -> str | None:
        return next((c.asset_id for c in self.clips if c.layer == "video" and c.asset_id), None)


def _ordered(state) -> list[dict]:
    return sorted(state.get("scenes", []), key=lambda scene: scene.get("order", 0))


def scene_ranges(state) -> dict[str, tuple[float, float]]:
    """Окно сцены в секундах; у старых записей без start_ms — по длительностям."""

    ranges, cursor = {}, 0
    for scene in _ordered(state):
        duration = scene.get("duration_ms") or (scene.get("end_ms", 0) - scene.get("start_ms", 0))
        start = scene.get("start_ms", cursor)
        ranges[scene["scene_id"]] = (round(start / 1000, 3), round((start + duration) / 1000, 3))
        cursor = start + duration
    return ranges


def _position_label(state, spec) -> str:
    """Человеку — не голый position_id: «сцены Клубок», «звукового слоя
    «music»», «общего видео»."""

    scene_id = spec.get("scene_id")
    if scene_id:
        scene = next((s for s in state.get("scenes", []) if s.get("scene_id") == scene_id), None)
        return f"сцены {(scene or {}).get('title') or scene_id}"
    layer = spec.get("layer")
    if layer:
        return f"звукового слоя «{layer}»"
    if spec.get("kind") == "oneshot":
        return "общего видео"
    return str(spec.get("position_id", "?"))


def _position_specs(state) -> dict:
    """{position_id: spec}; повреждённый проект (не список sцен и т. п.) —
    MontageError, не DomainValidationError сквозь этот модуль наружу."""

    try:
        return {spec["position_id"]: spec for spec in position_specs(state)}
    except DomainValidationError as error:
        raise MontageError(f"проект повреждён: {error}") from error


def _accepted_asset(state, spec) -> str | None:
    """Asset ID указателя позиции — только принятый результат: не отклонён,
    не отправлен в архив (retired), не скрыт, с непустым asset_id. Тот же
    критерий, что у `runner_context._position_context` (approved+not retired)
    и `domain._accepted_linked_result` (+ not hidden, + asset_id непустой) —
    не сам хелпер (он ещё и сам ищет версию по id и не знает про owner-links
    позиции монтажа `current_member` уже проверяет), а его правило приёмки:
    отклонённый/отправленный в архив/скрытый/неопределившийся результат в
    черновик не попадает."""

    if spec is None:
        return None
    try:
        result = current_member(state, spec, "result", missing_ok=True)
    except DomainValidationError as error:
        raise MontageError(
            f"сломана ссылка на результат {_position_label(state, spec)} — выберите вариант заново"
        ) from error
    if not result:
        return None
    if (result.get("decision") != "approved" or result.get("retired") is True
            or result.get("hidden") is True or not isinstance(result.get("asset_id"), str)
            or not result["asset_id"].strip()):
        return None
    return result["asset_id"]


def video_sources(state, *, strict=True) -> list[tuple[dict | None, str]]:
    """[(сцена или None для one_shot, asset_id)] по порядку сценария."""

    specs = _position_specs(state)
    if state.get("gen_mode", "per_scene") == "one_shot":
        asset = _accepted_asset(state, specs.get("pos:oneshot"))
        if asset:
            return [(None, asset)]
        if strict:
            raise MontageError("общее видео (one_shot) не принято")
        return []
    found, missing = [], []
    for scene in _ordered(state):
        asset = _accepted_asset(state, specs.get(f"pos:scene:{scene['scene_id']}:video"))
        if asset:
            found.append((scene, asset))
        else:
            missing.append(scene.get("title") or scene["scene_id"])
    if strict and (missing or not found):
        if not missing:
            raise MontageError("в проекте нет сцен")
        raise MontageError("; ".join(f"видео сцены {name} не принято" for name in missing))
    return found


def audio_sources(state) -> dict[str, str]:
    specs = _position_specs(state)
    sources = {}
    for layer in AUDIO_LAYER_NAMES:
        asset = _accepted_asset(state, specs.get(f"pos:audio:{layer}"))
        if asset:
            sources[layer] = asset
    return sources


def _video_clips(state, videos, media, under_layers) -> list[ClipPlan]:
    ranges = scene_ranges(state)
    story_end = max((end for _start, end in ranges.values()), default=0.0)
    clips = []
    for index, (scene, asset) in enumerate(videos, start=1):
        info = media(asset)
        start, end = ranges[scene["scene_id"]] if scene else (0.0, story_end or info.duration)
        fade = TRANSITION if info.has_audio else 0.0
        clips.append(ClipPlan(
            f"v-{index}", "video", start, round(min(end - start, info.duration), 3),
            scene_id=scene["scene_id"] if scene else None, asset_id=asset,
            volume=VIDEO_VOLUME[under_layers] if info.has_audio else None,
            fade_in=fade if index > 1 else 0.0, fade_out=fade, visual_fade=index > 1,
            has_audio=info.has_audio))
    return clips


def plan_draft(state: dict, media: Callable[[str], MediaInfo]) -> DraftPlan:
    if (state.get("project") or {}).get("type") == "photo":
        raise MontageError("у фото-проекта монтажа нет: его сборка — принятая картинка")
    audio = audio_sources(state)
    clips = _video_clips(state, video_sources(state), media, bool(audio))
    total = round(max(clip.start + clip.duration for clip in clips), 3)
    for layer, asset in audio.items():
        info = media(asset)
        clips.append(ClipPlan(f"a-{layer}", layer, 0.0, round(min(info.duration, total), 3),
                              asset_id=asset, volume=DEFAULT_VOLUMES[layer],
                              fade_out=LAYER_FADE_OUT.get(layer, 0.0), has_audio=True))
    scene_ids = tuple(scene["scene_id"] for scene in _ordered(state))
    gen_mode = state.get("gen_mode", "per_scene")
    return DraftPlan(duration=total, clips=tuple(clips), scene_ids=scene_ids, gen_mode=gen_mode)
