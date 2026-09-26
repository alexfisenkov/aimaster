"""Окружение каждого запуска движка: тихие флаги HyperFrames, свой HOME
движка (кэши, браузер, настройки не попадают в домашнюю папку человека),
браузер из записи установщика, ffmpeg/ffprobe, найденные монтажом, кэш кадров
и адрес монтажного стола только на 127.0.0.1."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from ..platform_compat import IS_WINDOWS, find_program
from .engine import Engine

QUIET_FLAGS = {
    "HYPERFRAMES_NO_UPDATE_CHECK": "1",
    "HYPERFRAMES_NO_AUTO_INSTALL": "1",
    "HYPERFRAMES_NO_TELEMETRY": "1",
    "HYPERFRAMES_SKIP_SKILLS": "1",
    "NO_COLOR": "1",
    "FORCE_COLOR": "0",
}


def engine_home(engine: Engine) -> Path:
    return Path(engine.prefix) / "home"


def frames_cache(engine: Engine) -> Path:
    return Path(engine.prefix) / "cache" / "frames"


FF_VARIABLES = (("ffmpeg", "HYPERFRAMES_FFMPEG_PATH"), ("ffprobe", "HYPERFRAMES_FFPROBE_PATH"))


def engine_env(engine: Engine, base: Mapping[str, str] | None = None, *,
               cwd: Path | None = None, find=find_program) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    # ffmpeg/ffprobe — тот же, что находит монтаж (полный путь из абсолютного PATH):
    # иначе HyperFrames ищет сам и доходит до папки запуска (current/, её .hyperframes/bin).
    for name, variable in FF_VARIABLES:
        env.pop(variable, None)
        found = find(name, environ=env)
        if found:
            env[variable] = found
    env.update(QUIET_FLAGS)
    if cwd is not None:
        # `preview .` 0.8.75 называет проект по basename($PWD): PWD вызывающего
        # дал бы Studio адрес «#project/<его папка>» вместо папки монтажа.
        env["PWD"] = str(cwd)
    env["HOME"] = str(engine_home(engine))
    if IS_WINDOWS:
        env["USERPROFILE"] = env["HOME"]
    env["HYPERFRAMES_EXTRACT_CACHE_DIR"] = str(frames_cache(engine))
    # Браузер — только из записи установщика, чужой из окружения не наследуем (round 4/5).
    env.pop("HYPERFRAMES_BROWSER_PATH", None)
    if engine.browser:
        env["HYPERFRAMES_BROWSER_PATH"] = engine.browser
    # `preview` слушает HYPERFRAMES_PREVIEW_HOST (иначе 127.0.0.1): чужое значение
    # из окружения человека выставило бы монтажный стол в сеть.
    env["HYPERFRAMES_PREVIEW_HOST"] = "127.0.0.1"
    return env
