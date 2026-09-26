#!/usr/bin/env python3
"""Проверка монтажного движка на CI: черновик навыка из клипов ffmpeg и его сборка.

    python skills/aimaster/scripts/montage_ci_check.py --json [--offline]

Черновик строит та же функция, что `montage draft` (`draft.build_current`:
клипы и звук по плану, локальный GSAP из движка и таймлайн main на паузе,
шрифт «AM Inter»), в папке с кириллицей и пробелами; кириллический титр
добавляет та же функция, что `montage edit title-add`. Дальше — как перед
сборкой версии: ссылки композиции, lint, рендер с качеством навыка, ffprobe и
следы сети в логе рендера (`verify.network_markers`: любой след — ошибка);
в отчёте — md5 декодированного видео, на Linux CI его сравнивают у запусков
с сетью и без. --offline только помечает запуск: сеть отрезают снаружи (см.
.github/workflows/ci.yml).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
import unittest
from dataclasses import asdict
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
for _path in (str(_SCRIPTS.parent), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import montage_testkit  # noqa: E402
from studio.montage import MontageError  # noqa: E402
from studio.montage.canvas import Canvas  # noqa: E402
from studio.montage.composition_refs import check_composition, external_references  # noqa: E402
from studio.montage.draft import build_current  # noqa: E402
from studio.montage.edit import EditContext, EditRequest  # noqa: E402
from studio.montage.edit_ops import title_add  # noqa: E402
from studio.montage.engine import load_pin, require_engine  # noqa: E402
from studio.montage.engine_cli import frames_cache, run_engine, run_engine_json  # noqa: E402
from studio.montage.index_io import read_index  # noqa: E402
from studio.montage.paths import montage_paths  # noqa: E402
from studio.montage.probe import probe_media  # noqa: E402
from studio.montage.verify import lint_problems, network_markers, output_problems  # noqa: E402
from studio.platform_compat import ensure_utf8_stdio, find_program  # noqa: E402

SIZE = (540, 960)
DURATION = 3.0
TITLE = "Проверка шрифта: Ёжик и кот 2026"
SCENES = (("s1", "Сад", "Проверка монтажа", 2000, "clip-1"), ("s2", "Клубок", "Без сети", 1000, "clip-2"))


def build_draft(project_dir: Path, engine_prefix: Path) -> Path:
    """Черновик навыка с титром в <project_dir>/montage/current; возвращает эту папку.
    GSAP — из `engine_prefix` (как у `montage draft`), клипы — ffmpeg."""

    sources = Path(project_dir) / "исходники"
    files = {
        "clip-1": montage_testkit.make_clip(sources / "clip-1.mp4", 2.0, size=SIZE, color="red", freq=440),
        "clip-2": montage_testkit.make_clip(sources / "clip-2.mp4", 1.0, size=SIZE, color="blue", freq=660),
        "voice": montage_testkit.make_tone(sources / "voice.wav", DURATION, freq=220),
    }
    state = montage_testkit.video_state(list(SCENES), audio={"voice": "voice"})
    paths = montage_paths(project_dir)
    build_current(paths, state, files.__getitem__, probe=lambda path: probe_media(path),
                  engine_prefix=engine_prefix)
    title_add(EditContext(None, paths, None),
              EditRequest(op="title-add", text=TITLE, at=0.2, duration=2.6))
    return paths.current


def video_md5(path: Path) -> str:
    """md5 декодированного видеопотока: ролик с сетью и без сети обязан совпасть."""

    ffmpeg = find_program("ffmpeg")
    if ffmpeg is None:
        raise OSError("нет ffmpeg для md5 видео")
    proc = subprocess.run([ffmpeg, "-v", "error", "-i", str(path), "-map", "0:v", "-f", "md5", "-"],
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, check=True,
                          timeout=300)
    return proc.stdout.strip().rsplit("=", 1)[-1]


def _render(engine, comp: Path, output: Path, report: dict) -> None:
    pin = load_pin()
    started = time.monotonic()
    result = run_engine(engine, ["render", ".", "--output", str(output), "--quality",
                                 pin["render_quality"], "--frames-cache-dir",
                                 str(frames_cache(engine)), "--quiet"],
                        cwd=comp, timeout=pin["timeouts"]["render"])
    report["render_seconds"] = round(time.monotonic() - started, 1)
    report["network_markers"] = network_markers(result.stdout + "\n" + result.stderr)
    if result.code != 0 or not output.is_file():
        tail = (result.stderr or result.stdout).strip()[-600:]
        report["problems"].append(f"рендер завершился с кодом {result.code}: {tail}")
        return
    info = probe_media(output)
    report["probe"] = asdict(info)
    report["video_md5"] = video_md5(output)
    report["problems"] += output_problems(info, duration=DURATION, canvas=Canvas(*SIZE),
                                          needs_audio=True)


def check(offline: bool) -> dict:
    report = {"ok": False, "offline": offline, "problems": [], "network_markers": []}
    engine = require_engine()
    report["engine"] = engine.version
    with tempfile.TemporaryDirectory(prefix="aimaster-montage-", ignore_cleanup_errors=True) as temp:
        comp = build_draft(Path(temp) / "проверка монтажа" / "ролик 1", engine.prefix)
        text = read_index(comp / "index.html")
        report["external_urls"] = external_references(text)
        report["composition_problems"] = check_composition(text, comp)
        lint = run_engine_json(engine, ["lint", ".", "--json"], cwd=comp,
                               timeout=load_pin()["timeouts"]["cli"], ok_codes=(0, 1))
        report["lint_errors"] = lint_problems(lint)
        _render(engine, comp, comp.parent.parent / "итог ролика.mp4", report)
    report["problems"] += [f"композиция: {problem}" for problem in report["composition_problems"]]
    report["problems"] += [f"lint: {error}" for error in report["lint_errors"]]
    report["problems"] += [f"сеть: {line}" for line in report["network_markers"]]
    report["ok"] = not report["problems"]
    return report


def main(argv=None) -> int:
    ensure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Проверка монтажного движка на CI.")
    parser.add_argument("--json", action="store_true", help="вывод JSON")
    parser.add_argument("--offline", action="store_true", help="пометить запуск без сети")
    args = parser.parse_args(argv)
    try:
        report = check(args.offline)
    except (MontageError, OSError, subprocess.SubprocessError, unittest.SkipTest) as error:
        report = {"ok": False, "offline": args.offline, "problems": [str(error)]}
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json
          else "\n".join(["ОК" if report["ok"] else "НЕ ПРОЙДЕНО", *report["problems"]]))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
