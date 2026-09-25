"""Сравнение current/index.html с текущим проектом: что устарело и почему.

`stale_clips` — чистая функция (текст + state → список записей), без I/O
(это в `index_io.py`/`refresh.py`). Три исхода, только первый правит
`refresh.refresh_draft` (`reason` не задан/None):

- протух — сцена/слой сейчас указывают на другой принятый результат:
  `current_asset_id` заполнен, есть на что заменить исходник;
- «нет принятого» — сцена/слой сейчас не указывают ни на один принятый
  результат (отклонили, отправили в архив, скрыли, отменили выбор): менять
  не на что, но пользователь должен это увидеть;
- «нужен --rebuild» (`cause`: scene_added/scene_removed/gen_mode/
  layer_added) — структурная перемена, которую точечная правка не берёт.
  `clip` у структурных записей всегда `None`, даже когда в разметке
  технически есть повисший клип (scene_removed) — refresh_draft их так и
  так не трогает.

Черновик, собранный `draft.build_current`, несёт на корне слепок структуры
на момент сборки (`data-am-scenes`, `data-am-gen-mode`, `data-am-layers` —
см. `draft_html.render_draft_html`) — по нему отличаем сцену/слой, которые
владелец сам убрал со стола (не стейл, его решение), от тех, что пропали из
проекта (стейл). Черновик без этого слепка (собран до раунда 2, или правлен
руками) — слепок восстанавливаем из самих клипов: тот же алгоритм, один на
все черновики, не два разных пути поведения."""

from __future__ import annotations

from . import AUDIO_LAYER_NAMES
from .draft_plan import audio_sources, video_sources
from .html_doc import ROOT_ID, element_attrs


def _structural(*, clip, layer, scene_id, cause) -> dict:
    return {"clip": clip, "layer": layer, "scene_id": scene_id, "asset_id": None,
            "current_asset_id": None, "reason": "нужен --rebuild", "cause": cause}


def _refresh_target(clip_id, layer, scene, asset, current) -> dict:
    if current is None:
        return {"clip": clip_id, "layer": layer, "scene_id": scene, "asset_id": asset,
                "current_asset_id": None, "reason": "нет принятого", "cause": None}
    return {"clip": clip_id, "layer": layer, "scene_id": scene, "asset_id": asset,
            "current_asset_id": current, "reason": None, "cause": None}


def _recorded_structure(root_attrs: dict, clips_attrs: dict) -> tuple[set, str, set]:
    """(recorded_scenes, recorded_gen_mode, recorded_layers) — со корня, если
    там есть слепок; иначе восстановлены из самих клипов: recorded_scenes =
    data-am-scene видео-клипов, recorded_gen_mode = one_shot, если у
    видео-клипа нет сцены, иначе per_scene, recorded_layers = слои,
    встретившиеся на клипах. Черновик с частичным слепком (data-am-scenes/
    data-am-gen-mode раунда 2, ещё без data-am-layers раунда 3) —
    сцены/gen_mode со корня, слои — восстановлены отдельно: не всё сразу
    легаси только потому, что не хватает одного нового поля."""

    have_scenes = "data-am-scenes" in root_attrs and "data-am-gen-mode" in root_attrs
    if have_scenes:
        scenes = set((root_attrs.get("data-am-scenes") or "").split())
        gen_mode = root_attrs.get("data-am-gen-mode")
    else:
        scenes, has_sceneless_video = set(), False
        for attrs in clips_attrs.values():
            if attrs.get("data-am-layer") != "video":
                continue
            scene = attrs.get("data-am-scene") or None
            if scene:
                scenes.add(scene)
            else:
                has_sceneless_video = True
        gen_mode = "one_shot" if has_sceneless_video else "per_scene"

    if "data-am-layers" in root_attrs:
        layers = set((root_attrs.get("data-am-layers") or "").split())
    else:
        layers = {attrs.get("data-am-layer") for attrs in clips_attrs.values()
                  if attrs.get("data-am-layer") in AUDIO_LAYER_NAMES}
    return scenes, gen_mode, layers


def stale_clips(html_text: str, state: dict) -> list[dict]:
    """Клипы, чей исходник разошёлся с текущим проектом (см. докстроку модуля).

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

    recorded_scenes, recorded_gen_mode, recorded_layers = _recorded_structure(
        root_attrs, clips_attrs)
    gen_mode_changed = recorded_gen_mode != current_gen_mode

    stale = []
    for clip_id, attrs in clips_attrs.items():
        layer, asset = attrs.get("data-am-layer"), attrs.get("data-am-asset")
        if not layer or not asset or layer not in ("video", *AUDIO_LAYER_NAMES):
            continue
        scene = attrs.get("data-am-scene") or None
        if layer == "video":
            # Сцена этого клипа уже не в проекте — её отдельно и один раз
            # называет scene_removed (по разности множеств, ниже); гонять
            # тут ещё и per-clip «нет принятого» для неё незачем — то же
            # самое верно и при смене gen_mode, где wanted_video построен
            # под другую форму (per_scene — по сцене, one_shot — один клип
            # без сцены) и сравнивать поклипно бессмысленно.
            if gen_mode_changed or (scene is not None and scene not in scene_ids_now):
                continue
            current = wanted_video.get(scene)
        else:
            current = wanted_audio.get(layer)
        if current != asset:
            stale.append(_refresh_target(clip_id, layer, scene, asset, current))

    if gen_mode_changed:
        stale.append(_structural(clip=None, layer=None, scene_id=None, cause="gen_mode"))
    # Сцена меняет раскладку в обоих режимах: у one_shot один клип покрывает
    # всю историю (story_end по всем сценам), так что добавление/удаление
    # сцены требует --rebuild и там, не только в per_scene.
    for scene_id in sorted(scene_ids_now - recorded_scenes):
        stale.append(_structural(clip=None, layer="video", scene_id=scene_id, cause="scene_added"))
    for scene_id in sorted(recorded_scenes - scene_ids_now):
        stale.append(_structural(clip=None, layer="video", scene_id=scene_id, cause="scene_removed"))
    for layer in wanted_audio:
        if layer not in recorded_layers:
            stale.append(_structural(clip=None, layer=layer, scene_id=None, cause="layer_added"))
    return stale
