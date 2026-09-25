"""Заготовки тестов монтажа: клипы из ffmpeg, состояния проектов, подмена CLI
HyperFrames. Имя не test_* — unittest сам этот файл не запускает."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from studio.montage.engine import PREFIX_ENV  # noqa: E402
from studio.platform_compat import find_program  # noqa: E402


def isolate_hyperframes_dir(test: unittest.TestCase, root) -> None:
    """Подменяет AIMASTER_HYPERFRAMES_DIR на пустую временную папку — иначе
    `workspace init` (и любой другой вызов montage_report) читает настоящий
    кеш HyperFrames пользователя: медленно, недетерминированно между машинами
    и может скопировать реальные скиллы в тестовую рабочую папку (разбор 1/5,
    находка 9). Звать в setUp до первого workspace init."""

    patcher = mock.patch.dict(os.environ, {PREFIX_ENV: str(Path(root) / "неиспользуемый-hyperframes")})
    patcher.start()
    test.addCleanup(patcher.stop)


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
    """mp4-клип, физически закодированный лёжа боком (по умолчанию 192x108 —
    landscape), с записанной в контейнер матрицей поворота — как показывает
    портретную съёмку телефон.

    Кодируем обычный landscape-клип, затем ремуксуем с -display_rotation и
    -c copy: именно эта комбинация реально пишет side_data_list[0].rotation
    в mp4 на этой сборке ffmpeg (8.1) — проверено вручную перед тем, как
    полагаться на неё в тесте. Прямое кодирование с -metadata:s:v:0 rotate=N
    эту метадату на mp4-выходе теряет (тег остаётся только в логе ffmpeg,
    в сам файл не попадает) — этим способом клип раньше и собирался, отсюда
    и правка."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    plain = path.parent / (path.stem + ".плоский" + path.suffix)
    make_clip(plain, seconds, size=size, audio=False)
    _ffmpeg(["-display_rotation", str(rotation), "-i", plain, "-c", "copy", path])
    plain.unlink(missing_ok=True)
    return path


def video_state(scenes, *, audio=None, gen_mode="per_scene", oneshot_asset=None, mode="guided",
                project_id="p") -> dict:
    """Видеопроект на шаге «Сборка»: всё до звука одобрено, у позиций выбраны результаты.

    scenes — [(scene_id, title, text, duration_ms, asset_id | None)];
    audio — {слой: asset_id}; oneshot_asset — общее видео для gen_mode=one_shot."""

    state = {
        "revision": 0,
        "project": {"id": project_id, "title": "Проба монтажа", "type": "video", "mode": mode,
                    "status": "active", "order": 1},
        "milestones": {"scenario": "approved", "image_plan": "approved",
                       "image_results": "approved", "motion": "approved", "audio": "approved"},
        "script": {"active_version_id": "s1", "versions": [
            {"version_id": "s1", "parent_version_id": None, "text": "сценарий", "reason": "начало"}]},
        "gen_mode": gen_mode, "history": [], "stage_decisions": [], "references": [],
        "image_prompts": [], "motion_prompts": [], "image_results": [], "video_results": [],
        "audio_layers": [], "audio_prompts": [], "audio_results": [], "applied_action_ids": [],
        "scenes": [],
    }
    cursor = 0
    for order, (scene_id, title, text, duration_ms, asset) in enumerate(scenes, start=1):
        version = f"result:scene:{scene_id}:video-v1"
        linked = bool(asset) and gen_mode == "per_scene"
        state["scenes"].append({
            "scene_id": scene_id, "order": order, "title": title, "duration_ms": duration_ms,
            "start_ms": cursor, "end_ms": cursor + duration_ms,
            "links": {"video_result_id": version} if linked else {},
            "script_block": {"active_version_id": f"b-{scene_id}", "versions": [
                {"version_id": f"b-{scene_id}", "parent_version_id": None, "text": text,
                 "reason": "начало"}]}})
        cursor += duration_ms
        if linked:
            state["video_results"].append({
                "result_id": f"result:scene:{scene_id}:video", "version_id": version,
                "scene_id": scene_id, "parent_version_id": None, "asset_id": asset,
                "status": "ready", "decision": "approved"})
    if gen_mode == "one_shot" and oneshot_asset:
        state["oneshot"] = {"links": {"video_result_id": "result:oneshot-v1"}}
        state["video_results"].append({
            "result_id": "result:oneshot", "version_id": "result:oneshot-v1",
            "parent_version_id": None, "asset_id": oneshot_asset, "status": "ready",
            "decision": "approved"})
    for layer, asset in (audio or {}).items():
        version = f"result:audio:{layer}-v1"
        state["audio_layers"].append({"layer": layer, "links": {"audio_result_id": version}})
        state["audio_results"].append({
            "result_id": f"result:audio:{layer}", "version_id": version, "parent_version_id": None,
            "asset_id": asset, "status": "ready", "decision": "approved"})
    return state
