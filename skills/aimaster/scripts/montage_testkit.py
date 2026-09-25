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

from studio.montage import MontageError  # noqa: E402
from studio.montage.draft_html import title_fragment  # noqa: E402
from studio.montage.engine import PREFIX_ENV, Engine, load_pin  # noqa: E402
from studio.montage.engine_cli import EngineResult  # noqa: E402
from studio.montage.html_doc import (  # noqa: E402
    element_attrs, element_span, fmt_number, insert_before_root_end, root_duration, set_attr)
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


def fake_gsap_prefix(root, *, version: str | None = None, files=("gsap", "MotionPathPlugin")) -> Path:
    """Папка движка с одним только GSAP, как его ставит установщик:
    `node_modules/gsap/package.json` (версия — закреплённая, если не задана)
    и `dist/<имя>.min.js`. Для черновика и vendor без настоящего движка."""

    prefix = Path(root) / "движок"
    package = prefix / "node_modules" / "gsap"
    (package / "dist").mkdir(parents=True, exist_ok=True)
    (package / "package.json").write_text(
        '{"name": "gsap", "version": "%s"}' % (version or load_pin()["gsap_version"]), encoding="utf-8")
    for name in files:
        (package / "dist" / f"{name}.min.js").write_text(f"/* {name} */\n", encoding="utf-8")
    return prefix


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


TITLES = (("t-1", "Барсик идёт по саду", 0.2, 1.6), ("t-2", "Находит клубок", 2.2, 1.1))


def with_titles(html_text: str, titles=TITLES) -> str:
    """Черновик без титров + титры, как их добавил бы montage edit (title-add)."""

    for clip_id, text, start, duration in titles:
        html_text = insert_before_root_end(html_text, title_fragment(clip_id, text, start, duration))
    return html_text


def fake_engine(prefix: Path) -> Engine:
    return Engine(node="node", script=Path(prefix) / "hyperframes.mjs", prefix=Path(prefix),
                  version="0.8.75", browser=None)


def timeline_from_html(html_text: str) -> dict:
    """Вывод `hyperframes timeline --json` 0.8.75 для нашей разметки (поля, что читает model.py)."""

    attrs = element_attrs(html_text)
    tracks: dict[str, list] = {}
    for element_id, data in attrs.items():
        if element_id == "root" or "data-start" not in data:
            continue
        tag = data["_tag"]
        kind = tag if tag in ("video", "audio", "img") else "div"
        track = {"video": "video", "img": "video", "audio": "audio"}.get(kind, "graphics")
        start, duration = float(data["data-start"]), float(data.get("data-duration") or 0)
        tracks.setdefault(track, []).append({
            "id": element_id, "elementId": element_id, "kind": kind, "trackKind": track,
            "start": start, "duration": duration, "end": round(start + duration, 3),
            "src": data.get("src"),
            "volume": float(data["data-volume"]) if "data-volume" in data else None,
            "trackIndex": int(data.get("data-track-index") or 0), "hfId": data.get("data-hf-id")})
    return {"timeline": {"duration": float(attrs["root"]["data-duration"]),
                         "tracks": [{"kind": kind, "rows": rows} for kind, rows in tracks.items()]},
            "_meta": {"version": "0.8.75"}}


def _opt(args, name):
    return args[args.index(name) + 1] if name in args else None


class FakeHyperframes:
    """Подмена EngineRunner: ведёт себя как CLI HyperFrames 0.8.75 на наших композициях
    (проба: move не выходит за корень; trim не трогает data-media-start; split ставит
    data-media-start новой части и зовёт её <id>-2; set volume=; delete; lint; render)."""

    def __init__(self, *, lint_report=None, render_bytes=None, render_log="[INFO] done", refuse=None):
        self.calls: list[list[str]] = []
        self.lint_report = lint_report or {"ok": True, "errorCount": 0, "findings": []}
        self.render_bytes = render_bytes
        self.render_log = render_log
        self.refuse = dict(refuse or {})

    def json(self, engine, args, *, cwd, timeout, ok_codes=(0,)):
        args = [str(item) for item in args]
        self.calls.append(args)
        index = Path(cwd) / "index.html"
        if args[0] == "lint":
            return dict(self.lint_report)
        if args == ["timeline", "--json"]:
            return timeline_from_html(index.read_text(encoding="utf-8"))
        if args[0] == "timeline":
            return self._mutate(index, args[1:])
        raise AssertionError(f"неожиданная команда {args}")

    def run(self, engine, args, *, cwd, timeout):
        args = [str(item) for item in args]
        self.calls.append(args)
        if args[0] != "render":
            raise AssertionError(f"неожиданная команда {args}")
        if self.render_bytes is None:
            return EngineResult(1, "", "render failed: browser crashed")
        Path(_opt(args, "--output")).write_bytes(self.render_bytes)
        return EngineResult(0, self.render_log, "")

    def _mutate(self, index: Path, args: list[str]) -> dict:
        op, ref = args[0], args[1].lstrip("#")
        if op in self.refuse:
            raise MontageError(f"HyperFrames отказал: {self.refuse[op]}")
        text = index.read_text(encoding="utf-8")
        data = element_attrs(text)[ref]
        start, duration = float(data["data-start"]), float(data.get("data-duration") or 0)
        if op == "move":
            root, at = root_duration(text), float(args[2])
            if at + duration > root + 1e-6:
                raise MontageError(f"HyperFrames отказал: move would end at {at + duration}, "
                                   f"beyond composition duration {root}")
            text = set_attr(text, ref, "data-start", args[2])
        elif op == "trim":
            for flag, attr in (("--start", "data-start"), ("--duration", "data-duration")):
                if _opt(args, flag) is not None:
                    text = set_attr(text, ref, attr, _opt(args, flag))
        elif op == "split":
            at = float(args[2])
            first = round(at - start, 3)
            media = float(data.get("data-media-start") or 0)
            begin, end = element_span(text, ref)
            piece = text[begin:end]
            for attr, value in (("data-start", fmt_number(at)),
                                ("data-duration", fmt_number(duration - first)),
                                ("data-media-start", fmt_number(media + first)), ("id", f"{ref}-2")):
                piece = set_attr(piece, ref, attr, value)
            text = set_attr(text, ref, "data-duration", fmt_number(first))
            _begin, end = element_span(text, ref)
            text = text[:end] + piece + text[end:]
        elif op == "delete":
            begin, end = element_span(text, ref)
            text = text[:begin] + text[end:]
        elif op == "set":
            field, value = args[2].split("=", 1)
            text = set_attr(text, ref, f"data-{field}", value)
        else:
            raise AssertionError(f"неожиданная правка {op}")
        index.write_text(text, encoding="utf-8")
        return {"ok": True, "receipt": {"file": "index.html", "changed": True}, "file": "index.html"}
