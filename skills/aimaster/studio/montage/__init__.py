"""Монтаж на HyperFrames (docs/superpowers/specs/2026-09-25-montage-hyperframes-design.md).

Пакет разбит по ответственностям: engine* — движок, draft* — черновик,
model* — модель и смысловой diff, versions — версии, edit* — правки,
render/verify — сборка, desk — монтажный стол, service — вход для CLI и дашборда.
"""

from __future__ import annotations


class MontageError(RuntimeError):
    """Отказ монтажа; текст по-русски и показывается человеку как есть."""


LAYERS = ("video", "titles", "voice", "music", "fx", "atmos")
LAYER_LABELS = {"video": "Видео", "titles": "Титры", "voice": "Голос",
                "music": "Музыка", "fx": "Шумы", "atmos": "Атмосфера"}
TRACK_OF_LAYER = {layer: index for index, layer in enumerate(LAYERS)}
AUDIO_LAYER_NAMES = ("voice", "music", "fx", "atmos")
