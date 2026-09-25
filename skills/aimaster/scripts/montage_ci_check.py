#!/usr/bin/env python3
"""Проверка монтажного движка на CI: ролик 3 с из клипов ffmpeg.

    python skills/aimaster/scripts/montage_ci_check.py --json [--offline]

Берёт движок, поставленный install_montage.py; в папке с кириллицей и
пробелами собирает композицию из двух клипов и голоса (без текста), прогоняет
lint, рендер и ffprobe, ищет в композиции внешние ссылки, а в логе рендера —
следы сетевых запросов (шрифты Google, CDN). --offline только помечает запуск:
сеть отрезают снаружи (см. .github/workflows/ci.yml).
"""

from __future__ import annotations

import argparse
import json
import re
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
from studio.montage.engine import require_engine  # noqa: E402
from studio.montage.engine_cli import frames_cache, run_engine, run_engine_json  # noqa: E402
from studio.montage.probe import probe_media  # noqa: E402
from studio.platform_compat import ensure_utf8_stdio  # noqa: E402

SIZE = (540, 960)
DURATION = 3.0
# Любой след сети в логе рендера — ошибка: CDN-скрипт или шрифт с Google Fonts.
NETWORK_MARKERS = ("Inlined CDN script", "Failed to download CDN script", "from Google Fonts",
                   "fonts.googleapis.com")
# round 3/5: srcset разбирается по каждому кандидату отдельно (обычный
# случай — несколько через запятую с дескриптором плотности/ширины, "1x"/
# "480w"), src/href/poster ловятся и без кавычек, url()/image-set() — как
# один и тот же случай «функция с адресом внутри».
_EXTERNAL = re.compile(
    r"""(?:src|href|poster)\s*=\s*(?:"(?P<dq>[^"]*)"|'(?P<sq>[^']*)'|(?P<uq>[^\s"'>]+))"""
    r"""|srcset\s*=\s*(?:"(?P<srcset_dq>[^"]*)"|'(?P<srcset_sq>[^']*)')"""
    r"""|(?:url|image-set)\(\s*["']?(?P<func>[^"')]*)["']?\s*\)"""
    r"""|@import\s+["'](?P<imp>[^"']*)["']""",
    re.IGNORECASE | re.VERBOSE)
_SCHEME = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|//)", re.I)


def _is_external(url: str) -> bool:
    return bool(url) and bool(_SCHEME.match(url)) and not url.lower().startswith("data:")


COMPOSITION = """<!doctype html>
<html lang="ru">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=540, height=960" />
    <style>
      * { margin: 0; padding: 0; box-sizing: border-box; }
      html, body { width: 540px; height: 960px; overflow: hidden; background: #000; }
      #root { position: relative; width: 540px; height: 960px; overflow: hidden; background: #000; }
      .am-video { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; z-index: 1; }
      .am-fade-in { animation: am-fade-in 0.4s linear both; }
      @keyframes am-fade-in { from { opacity: 0; } to { opacity: 1; } }
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="3" data-width="540" data-height="960" data-no-timeline>
      <video id="v-1" class="am-video" src="assets/clip-1.mp4" data-start="0" data-duration="1.5" data-media-start="0" data-track-index="0" data-has-audio="true" data-volume="0.3" playsinline></video>
      <video id="v-2" class="am-video am-fade-in" src="assets/clip-2.mp4" data-start="1.5" data-duration="1.5" data-media-start="0" data-track-index="0" data-has-audio="true" data-volume="0.3" playsinline></video>
      <audio id="a-voice" src="assets/voice.wav" data-start="0" data-duration="3" data-media-start="0" data-track-index="2" data-volume="1"></audio>
    </div>
  </body>
</html>
"""


def external_urls(html_text: str) -> list[str]:
    found = []
    for m in _EXTERNAL.finditer(html_text):
        srcset = m.group("srcset_dq")
        if srcset is None:
            srcset = m.group("srcset_sq")
        if srcset is not None:
            for candidate in srcset.split(","):
                candidate = candidate.strip()
                url = candidate.split()[0] if candidate else ""
                if _is_external(url):
                    found.append(url)
            continue
        value = m.group("dq")
        if value is None:
            value = m.group("sq")
        if value is None:
            value = m.group("uq") or m.group("func") or m.group("imp")
        if value is not None:
            value = value.strip()
            if _is_external(value):
                found.append(value)
    return found


def _build(comp: Path) -> None:
    assets = comp / "assets"
    montage_testkit.make_clip(assets / "clip-1.mp4", 1.5, size=SIZE, color="red", freq=440)
    montage_testkit.make_clip(assets / "clip-2.mp4", 1.5, size=SIZE, color="blue", freq=660)
    montage_testkit.make_tone(assets / "voice.wav", DURATION, freq=220)
    (comp / "hyperframes.json").write_text('{\n  "media": {"autoProxy": true}\n}\n', encoding="utf-8")
    (comp / "index.html").write_text(COMPOSITION, encoding="utf-8")


def check(offline: bool) -> dict:
    report = {"ok": False, "offline": offline, "problems": []}
    engine = require_engine()
    report["engine"] = engine.version
    with tempfile.TemporaryDirectory(prefix="aimaster-montage-", ignore_cleanup_errors=True) as temp:
        comp = Path(temp) / "проверка монтажа" / "ролик 1"
        _build(comp)
        report["external_urls"] = external_urls((comp / "index.html").read_text(encoding="utf-8"))
        lint = run_engine_json(engine, ["lint", ".", "--json"], cwd=comp, timeout=120, ok_codes=(0, 1))
        report["lint_errors"] = [f"{f.get('code')}: {f.get('message')}"
                                 for f in lint.get("findings", []) if f.get("severity") == "error"]
        if "error" in lint:
            # HyperFrames иногда падает ВНУТРИ самого lint (не находка, а отказ
            # инструмента): {"ok": false, "error": "…", "findings": [], "errorCount": 0}.
            # round 3/5: `ok.is False` одна — это ЛЮБОЙ прошедший lint с
            # находками ({"ok": false, "errorCount": N, "findings": […]}) —
            # не крэш, а обычный результат, уже учтённый строкой выше.
            # Признак настоящего крэша — сам ключ "error".
            report["lint_errors"].append(f"lint не смог проверить: {lint['error']}")
        output = comp.parent / "итог ролика.mp4"
        started = time.monotonic()
        result = run_engine(engine, ["render", ".", "--output", str(output), "--quality", "draft",
                                     "--frames-cache-dir", str(frames_cache(engine)), "--quiet"],
                            cwd=comp, timeout=900)
        report["render_seconds"] = round(time.monotonic() - started, 1)
        log = result.stdout + "\n" + result.stderr
        report["network_markers"] = [line.strip()[:300] for line in log.splitlines()
                                     if any(marker in line for marker in NETWORK_MARKERS)]
        if result.code != 0 or not output.is_file():
            report["problems"].append(f"рендер завершился с кодом {result.code}: {log.strip()[-600:]}")
        else:
            info = probe_media(output)
            report["probe"] = asdict(info)
            if abs(info.duration - DURATION) > 0.1:
                report["problems"].append(f"длительность {info.duration} с вместо {DURATION} с")
            if (info.width, info.height) != SIZE:
                report["problems"].append(f"кадр {info.width}×{info.height} вместо {SIZE[0]}×{SIZE[1]}")
            if not info.has_audio:
                report["problems"].append("в ролике нет звука")
    report["problems"] += [f"внешняя ссылка: {url}" for url in report["external_urls"]]
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
