"""Заготовки тестов монтажа: клипы из ffmpeg, состояния проектов, подмена CLI
HyperFrames. Имя не test_* — unittest сам этот файл не запускает."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from studio.platform_compat import find_program  # noqa: E402


def ffmpeg_or_skip() -> str:
    ffmpeg = find_program("ffmpeg")
    if ffmpeg is None or find_program("ffprobe") is None:
        raise unittest.SkipTest("нужны ffmpeg и ffprobe")
    return ffmpeg


def _ffmpeg(args) -> None:
    subprocess.run([ffmpeg_or_skip(), "-v", "error", "-y", *map(str, args)], check=True,
                   stdin=subprocess.DEVNULL, timeout=120)


def make_clip(path: Path, seconds: float = 2.0, *, size=(108, 192), color="red", freq=440,
              audio=True) -> Path:
    """Клип H.264 с ключевым кадром раз в секунду (иначе HyperFrames ругается
    на редкие ключевые кадры) и тоном, если нужен звук."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = size
    args = ["-f", "lavfi", "-i", f"color=c={color}:s={width}x{height}:r=30:d={seconds}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}"]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-g", "30"]
    args += ["-c:a", "aac", "-shortest"] if audio else ["-an"]
    _ffmpeg(args + ["-movflags", "+faststart", path])
    return path


def make_tone(path: Path, seconds: float = 3.0, *, freq=220) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _ffmpeg(["-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}",
             "-c:a", "pcm_s16le", path])
    return path


def make_rotated_clip(path: Path, seconds: float = 1.0, *, size=(192, 108),
                      rotation=90) -> Path:
    """Клип, физически закодированный лёжа боком, с тегом rotate в метаданных —
    как отдаёт вертикальную съёмку телефон. mp4 у этой сборки ffmpeg тег молча
    роняет, поэтому контейнер — mkv (Matroska его сохраняет, хоть и в верхнем
    регистре: ROTATE; `probe._rotation` читает тег без учёта регистра)."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = size
    args = ["-f", "lavfi", "-i", f"color=c=red:s={width}x{height}:r=30:d={seconds}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-g", "30",
            "-metadata:s:v:0", f"rotate={rotation}"]
    _ffmpeg(args + [path])
    return path
