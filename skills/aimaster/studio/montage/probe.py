"""ffprobe: длительность, размер кадра, есть ли картинка и звук."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..platform_compat import find_program
from . import MontageError

PROBE_TIMEOUT = 60


@dataclass(frozen=True)
class MediaInfo:
    duration: float
    width: int | None
    height: int | None
    has_video: bool
    has_audio: bool


def find_ffprobe() -> str | None:
    return find_program("ffprobe")


def parse_probe(payload: dict) -> MediaInfo:
    streams = payload.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and not (s.get("disposition") or {}).get("attached_pic")), None)
    try:
        duration = float((payload.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    width = int(video["width"]) if video and video.get("width") else None
    height = int(video["height"]) if video and video.get("height") else None
    return MediaInfo(duration=round(duration, 3), width=width, height=height,
                     has_video=video is not None,
                     has_audio=any(s.get("codec_type") == "audio" for s in streams))


def probe_media(path: Path, *, ffprobe: str | None = None, runner=subprocess.run) -> MediaInfo:
    ffprobe = ffprobe or find_ffprobe()
    if ffprobe is None:
        raise MontageError("Не найден ffprobe (ставится вместе с ffmpeg): "
                           "python3 skills/aimaster/scripts/install.py --install-deps")
    argv = [ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
            str(path)]
    try:
        proc = runner(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                      stderr=subprocess.PIPE, timeout=PROBE_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as error:
        raise MontageError(f"ffprobe не запустился: {error}") from error
    if proc.returncode != 0:
        tail = (proc.stderr or b"").decode("utf-8", errors="replace").strip()[-300:]
        raise MontageError(f"ffprobe не прочитал {Path(path).name}: {tail}")
    try:
        payload = json.loads((proc.stdout or b"").decode("utf-8", errors="replace"))
    except ValueError as error:
        raise MontageError(f"ffprobe вернул не JSON для {Path(path).name}") from error
    return parse_probe(payload)
