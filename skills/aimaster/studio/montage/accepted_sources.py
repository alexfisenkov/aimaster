"""Какие результаты проекта идут в монтаж: принятое видео сцен и звуковых слоёв.

Выбранный результат берётся по указателю позиции (`current_member`), а не по
порядку списка, и только принятый (не отклонён, не в архиве, не скрыт, с
непустым asset_id). Отсюда берут источники и раскладка черновика
(`draft_plan.py`), и сравнение черновика с проектом (`stale.py`).
"""

from __future__ import annotations

from ..domain import DomainValidationError
from ..domain_positions import current_member, position_specs
from . import AUDIO_LAYER_NAMES, LAYER_LABELS, MontageError


def _ordered(state) -> list[dict]:
    return sorted(state.get("scenes", []), key=lambda scene: scene.get("order", 0))


def _position_label(state, spec) -> str:
    """Человеку — не голый position_id: «сцены Клубок», «звукового слоя
    «Голос»» (название — как на экране), «общего видео»."""

    scene_id = spec.get("scene_id")
    if scene_id:
        scene = next((s for s in state.get("scenes", []) if s.get("scene_id") == scene_id), None)
        return f"сцены {(scene or {}).get('title') or scene_id}"
    layer = spec.get("layer")
    if layer:
        return f"звукового слоя «{LAYER_LABELS.get(layer, layer)}»"
    if spec.get("kind") == "oneshot":
        return "общего видео"
    return str(spec.get("position_id", "?"))


def _position_specs(state) -> dict:
    """{position_id: spec}; повреждённый проект (не список сцен и т. п.) —
    MontageError, не DomainValidationError/KeyError сквозь этот модуль наружу."""

    try:
        return {spec["position_id"]: spec for spec in position_specs(state)}
    except KeyError as error:
        # str(KeyError) — repr ключа ("'scene_id'"): человеку это ничего не
        # говорит; position_specs читает scene["scene_id"] без .get().
        key = error.args[0] if error.args else "?"
        what = "у сцены нет scene_id" if key == "scene_id" else f"нет поля «{key}»"
        raise MontageError(f"проект повреждён: {what}") from error
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
