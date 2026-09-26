"""Нейтральная модель монтажа: время клипов — из `timeline --json`, наши пометки
(слой, сцена, ассет, кусок исходника, края звука, текст титра) — из index.html:
строки `timeline --json` 0.8.75 не содержат `data-media-start`.

В модель не входят `data-hf-id` и номер строки Studio (`data-track-index`,
Studio меняет его при перетаскивании): поэтому нормализация разметки при
открытии стола не делает монтаж «изменённым». Такая модель — основа схемы
слоёв дашборда (план Б) и будущего своего стола (вариант 2).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from . import LAYER_LABELS, LAYERS, MontageError, model_cache
from .engine import Engine
from .engine_cli import EngineRunner
from .html_doc import element_attrs
from .index_io import read_index

CLI_TIMEOUT = 120
_FALLBACK_LAYER = {"video": "video", "img": "video", "image": "video", "audio": "music"}


@dataclass(frozen=True)
class Clip:
    id: str
    layer: str
    kind: str
    start: float
    duration: float
    media_start: float = 0.0
    volume: float | None = None
    fade_in: float = 0.0
    fade_out: float = 0.0
    scene_id: str | None = None
    asset_id: str | None = None
    src: str | None = None
    text: str | None = None

    @property
    def end(self) -> float:
        return round(self.start + self.duration, 3)


@dataclass(frozen=True)
class Model:
    duration: float
    clips: tuple[Clip, ...]

    def to_dict(self) -> dict:
        return {"duration": self.duration, "clips": [asdict(clip) for clip in self.clips]}

    @classmethod
    def from_dict(cls, data: dict) -> "Model":
        return cls(float(data["duration"]), tuple(Clip(**clip) for clip in data.get("clips", [])))

    def clip(self, clip_id: str) -> Clip:
        for clip in self.clips:
            if clip.id == clip_id:
                return clip
        raise MontageError(f"в монтаже нет клипа {clip_id}")


def _num(value, default=0.0) -> float:
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return default


def _rows(timeline: dict):
    for track in (timeline.get("timeline") or {}).get("tracks", []):
        yield from track.get("rows", [])


def build_model(timeline: dict, html_text: str) -> Model:
    attrs = element_attrs(html_text)
    clips = []
    for row in _rows(timeline):
        element_id = row.get("elementId") or row.get("id")
        mark = attrs.get(element_id, {})
        kind = str(row.get("kind") or mark.get("_tag") or "")
        layer = mark.get("data-am-layer")
        if layer not in LAYERS:
            layer = _FALLBACK_LAYER.get(kind, "titles")
        volume = row.get("volume")
        clips.append(Clip(
            id=element_id, layer=layer, kind=kind,
            start=_num(row.get("start")), duration=_num(row.get("duration")),
            media_start=_num(mark.get("data-media-start") or mark.get("data-playback-start")),
            volume=None if volume is None else _num(volume),
            fade_in=_num(mark.get("data-fade-in")), fade_out=_num(mark.get("data-fade-out")),
            scene_id=mark.get("data-am-scene") or None, asset_id=mark.get("data-am-asset") or None,
            # round-fix-3/5, item E: свой src-атрибут разметки, не поле
            # timeline-строки — то самое поле, о ненадёжности которого для
            # опознания разреза уже предупреждал round-fix-1/5, item 8
            # (там — про data-am-asset); split_pairs.same_source сравнивает
            # src у обоих участников через один и тот же источник данных.
            src=mark.get("src") or None,
            text=(mark.get("_text") or None) if layer == "titles" else None))
    order = {layer: index for index, layer in enumerate(LAYERS)}
    clips.sort(key=lambda clip: (order[clip.layer], clip.start, clip.id))
    return Model(_num((timeline.get("timeline") or {}).get("duration")), tuple(clips))


def model_hash(model: Model) -> str:
    canonical = json.dumps(model.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def read_model(engine: Engine, current_dir: Path, *, cache_dir: Path | None = None,
               runner=None) -> Model:
    """Модель текущего монтажа; кэш — по тексту index.html и версии движка
    (`model_cache`: чужой или подложенный файл кэша — промах)."""

    runner = runner or EngineRunner()
    html_text = read_index(Path(current_dir) / "index.html")
    hit = model_cache.load(cache_dir, engine.version, html_text) if cache_dir else None
    if hit is not None:
        try:
            return Model.from_dict(hit)
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
            pass
    timeline = runner.json(engine, ["timeline", "--json"], cwd=Path(current_dir), timeout=CLI_TIMEOUT)
    model = build_model(timeline, html_text)
    if cache_dir:
        model_cache.save(cache_dir, engine.version, html_text, model.to_dict())
    return model


def layers_view(model: Model) -> list[dict]:
    """Схема слоёв для экрана «Сборка»: все шесть дорожек в постоянном порядке."""

    keys = ("id", "kind", "start", "duration", "media_start", "volume", "scene_id", "asset_id", "text")
    return [{"layer": layer, "label": LAYER_LABELS[layer],
             "clips": [{key: getattr(clip, key) for key in keys}
                       for clip in model.clips if clip.layer == layer]}
            for layer in LAYERS]
