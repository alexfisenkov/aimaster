"""Обновление устаревших клипов существующего черновика.

`stale_clips` сравнивает current/index.html с текущим проектом — какие клипы
`refresh_draft` может точечно поправить (протухший исходник), а какие нет
(«нет принятого» — менять не на что; «нужен --rebuild» — структурная
перемена, точечная правка сюда не дотягивается). Черновик, собранный
`draft.build_current`, несёт на корне слепок структуры (`data-am-scenes`,
`data-am-gen-mode` — см. draft_html.render_draft_html) — по нему отличаем
сцену, которую владелец сам убрал со стола (не стейл, его решение), от той,
что пропала из проекта (стейл). У черновика без этого слепка (до раунда 2)
такого различия нет — прежнее поведение: любая сцена проекта без клипа
считается требующей --rebuild."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from . import AUDIO_LAYER_NAMES, MontageError
from .draft import _prober
from .draft_plan import TRANSITION, VIDEO_VOLUME, audio_sources, video_sources
from .html_doc import ROOT_ID, element_attrs, fmt_number, read_index, set_attr, write_index
from .media_sync import sync_media
from .probe import MediaInfo, probe_media


def _structural(*, clip, layer, scene_id, cause) -> dict:
    return {"clip": clip, "layer": layer, "scene_id": scene_id, "asset_id": None,
            "current_asset_id": None, "reason": "нужен --rebuild", "cause": cause}


def _refresh_target(clip_id, layer, scene, asset, current) -> dict:
    if current is None:
        return {"clip": clip_id, "layer": layer, "scene_id": scene, "asset_id": asset,
                "current_asset_id": None, "reason": "нет принятого", "cause": None}
    return {"clip": clip_id, "layer": layer, "scene_id": scene, "asset_id": asset,
            "current_asset_id": current, "reason": None, "cause": None}


def _legacy_stale_clips(clips_attrs, wanted_video, wanted_audio, scene_ids_now, one_shot_now):
    """Черновик без data-am-scenes/data-am-gen-mode: не может отличить
    «сцену убрали со стола» от «сцена новая» — любая сцена проекта без
    клипа считается требующей --rebuild, как до раунда 2."""

    stale, seen_scenes = [], set()
    for clip_id, attrs in clips_attrs.items():
        layer, asset = attrs.get("data-am-layer"), attrs.get("data-am-asset")
        if not layer or not asset or layer not in ("video", *AUDIO_LAYER_NAMES):
            continue
        scene = attrs.get("data-am-scene") or None
        if layer == "video":
            seen_scenes.add(scene)
            structural = (scene is not None and scene not in scene_ids_now) or (
                (scene is None) != one_shot_now)
            if structural:
                stale.append(_structural(clip=clip_id, layer=layer, scene_id=scene, cause=None))
                continue
            current = wanted_video.get(scene)
        else:
            current = wanted_audio.get(layer)
        if current != asset:
            stale.append(_refresh_target(clip_id, layer, scene, asset, current))
    if not one_shot_now:
        for scene_id in sorted(scene_ids_now - seen_scenes):
            stale.append(_structural(clip=None, layer="video", scene_id=scene_id, cause=None))
    return stale


def _marked_stale_clips(clips_attrs, root_attrs, wanted_video, wanted_audio, scene_ids_now,
                        current_gen_mode):
    """Черновик с data-am-scenes/data-am-gen-mode: сцена, которую записали
    при сборке и она всё ещё в проекте, но у неё нет клипа в разметке — НЕ
    стейл (владелец сам убрал её со стола); появилась/пропала из проекта
    или сменился gen_mode — «нужен --rebuild» с причиной (cause).

    Смена gen_mode делает `wanted_video` несравнимым с тем, что построил
    прежний gen_mode (per_scene клипы именованы по сцене, one_shot — один
    клип без сцены): сравнивать их поклипно бессмысленно, поэтому при смене
    видео-дорожку целиком отдаём одной записи gen_mode, а не гоняем каждый
    клип поодиночке через «нет принятого»."""

    recorded_scenes = set((root_attrs.get("data-am-scenes") or "").split())
    recorded_gen_mode = root_attrs.get("data-am-gen-mode")
    gen_mode_changed = recorded_gen_mode is not None and recorded_gen_mode != current_gen_mode

    stale, seen_layers = [], set()
    for clip_id, attrs in clips_attrs.items():
        layer, asset = attrs.get("data-am-layer"), attrs.get("data-am-asset")
        if not layer or not asset or layer not in ("video", *AUDIO_LAYER_NAMES):
            continue
        scene = attrs.get("data-am-scene") or None
        if layer == "video":
            if gen_mode_changed:
                continue
            if scene is not None and scene not in scene_ids_now:
                stale.append(_structural(clip=None, layer=layer, scene_id=scene, cause="scene_removed"))
                continue
            current = wanted_video.get(scene)
        else:
            seen_layers.add(layer)
            current = wanted_audio.get(layer)
        if current != asset:
            stale.append(_refresh_target(clip_id, layer, scene, asset, current))

    if gen_mode_changed:
        stale.append(_structural(clip=None, layer=None, scene_id=None, cause="gen_mode"))
    else:
        for scene_id in sorted(scene_ids_now - recorded_scenes):
            stale.append(_structural(clip=None, layer="video", scene_id=scene_id, cause="scene_added"))
    for layer in wanted_audio:
        if layer not in seen_layers:
            stale.append(_structural(clip=None, layer=layer, scene_id=None, cause="layer_added"))
    return stale


def stale_clips(html_text: str, state: dict) -> list[dict]:
    """Клипы, чей исходник разошёлся с текущим проектом. Правит только
    первую причину `refresh_draft` (`reason` не задан/None):

    - протух — сцена/слой сейчас указывают на другой принятый результат:
      `current_asset_id` заполнен, есть на что заменить исходник;
    - «нет принятого» — сцена/слой сейчас не указывают ни на один принятый
      результат (отклонили, отправили в архив, скрыли, отменили выбор):
      менять не на что, но пользователь должен это увидеть;
    - «нужен --rebuild» (`cause`: scene_added/scene_removed/gen_mode/
      layer_added) — структурная перемена, которую точечная правка не
      берёт. `clip` у структурных записей всегда `None`, даже когда в
      разметке технически есть повисший клип (scene_removed) — refresh_draft
      их так и так не трогает.

    Титры (задача 14, `montage edit`) сюда не относятся — у них нет
    выбранного результата, который можно принять/отклонить, поэтому слой
    "titles" (и любой, кроме video/аудио) не трогаем вовсе."""

    clips_attrs = element_attrs(html_text)
    root_attrs = clips_attrs.pop(ROOT_ID, {})
    wanted_video = {scene["scene_id"] if scene else None: asset
                    for scene, asset in video_sources(state, strict=False)}
    wanted_audio = audio_sources(state)
    scene_ids_now = {scene["scene_id"] for scene in state.get("scenes", [])}
    current_gen_mode = state.get("gen_mode", "per_scene")

    has_markers = "data-am-scenes" in root_attrs and "data-am-gen-mode" in root_attrs
    if has_markers:
        return _marked_stale_clips(clips_attrs, root_attrs, wanted_video, wanted_audio,
                                   scene_ids_now, current_gen_mode)
    return _legacy_stale_clips(clips_attrs, wanted_video, wanted_audio, scene_ids_now,
                               current_gen_mode == "one_shot")


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
    write_index(paths.index, text)
    return stale
