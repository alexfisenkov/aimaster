"""Размер кадра монтажа: по первому видеоклипу, иначе 1080×1920.

`AssetIndex` размер кадра MP4 не знает (`assets._mp4` отдаёт None), поэтому
его приносит ffprobe (`probe.MediaInfo`)."""

from __future__ import annotations

from dataclasses import dataclass

from .probe import MediaInfo

DEFAULT_WIDTH, DEFAULT_HEIGHT = 1080, 1920


@dataclass(frozen=True)
class Canvas:
    width: int
    height: int

    def to_dict(self) -> dict:
        return {"width": self.width, "height": self.height}


def _even(value: int) -> int:
    return value if value % 2 == 0 else value + 1


def canvas_for(first_video: MediaInfo | None) -> Canvas:
    """H.264 требует чётных сторон: нечётный размер исходника округляем вверх."""

    if first_video is None or not first_video.width or not first_video.height:
        return Canvas(DEFAULT_WIDTH, DEFAULT_HEIGHT)
    return Canvas(_even(first_video.width), _even(first_video.height))
