"""Проверки сборки: ошибки lint, выход ffprobe, следы сети и чужих шрифтов в логе рендера."""

from __future__ import annotations

from .canvas import Canvas
from .probe import MediaInfo

# HyperFrames 0.8.75 (строки его компилятора, dist/cli.js): шрифт, не
# объявленный @font-face из assets/, он подбирает сам — качает с Google Fonts
# («Fetched … from Google Fonts») или встраивает системный («Injected
# deterministic @font-face rules»), а не найдя — оставляет браузеру («No
# deterministic font mapping»). Без сети первой строки нет, а остальные есть:
# ролик офлайн и онлайн разошёлся бы, поэтому ошибка — любая из них. У монтажа
# свой шрифт (typeface, «AM Inter» из assets/fonts встраивается как data URI:
# «Embedded local font file» — это не след сети).
FONT_MARKERS = ("from Google Fonts", "fonts.googleapis.com", "FONT_FETCH",
                "Injected deterministic @font-face", "No deterministic font mapping",
                "Localized remote font", "Remote font download", "Inlined external @font-face")
# CDN-скрипт встраивается, скачанный; отсутствующий локальный GSAP компилятор
# сам подменяет ссылкой на CDN. Свой GSAP лежит в assets/ (черновик, montage gsap).
SCRIPT_MARKERS = ("Inlined CDN script", "Failed to download CDN script", "cdn.jsdelivr.net",
                  "Rewriting missing gsap script to CDN")
# Прочие внешние файлы, которые компилятор качает сам (проверка ссылок
# композиции их уже не пускает — это страховка на то, что она пропустила).
ASSET_MARKERS = ("Remote asset download", "External stylesheet fetch")
DURATION_TOLERANCE = 0.1  # три кадра при 30 к/с: контейнер округляет длину по кадрам и звуку


def _lines(log_text: str, markers) -> list[str]:
    return [line.strip()[:300] for line in (log_text or "").splitlines()
            if any(marker in line for marker in markers)]


def network_markers(log_text: str) -> list[str]:
    return _lines(log_text, FONT_MARKERS + SCRIPT_MARKERS + ASSET_MARKERS)


def _findings(report: dict, severity: str) -> list[str]:
    return [f"{item.get('code')}: {item.get('message')}"
            for item in report.get("findings") or []
            if isinstance(item, dict) and item.get("severity") == severity]


def lint_problems(report: dict) -> list[str]:
    """Ошибки lint. Ключ "error" — lint упал сам, не проверив композицию
    ({"ok": false, "error": "…", "findings": []}): это тоже отказ."""

    problems = _findings(report, "error")
    if report.get("error"):
        problems.append(f"lint не смог проверить: {report['error']}")
    if report.get("ok") is False and not problems:
        problems.append("lint не прошёл, но не назвал ошибок")
    return problems


def lint_warnings(report: dict) -> list[str]:
    return _findings(report, "warning")


def output_problems(info: MediaInfo, *, duration: float, canvas: Canvas,
                    needs_audio: bool) -> list[str]:
    problems = []
    if not info.has_video:
        problems.append("в файле нет видео")
    if abs(info.duration - duration) > DURATION_TOLERANCE:
        problems.append(f"длительность {info.duration:.2f} с вместо {duration:.2f} с")
    if (info.width, info.height) != (canvas.width, canvas.height):
        problems.append(f"кадр {info.width}×{info.height} вместо {canvas.width}×{canvas.height}")
    if needs_audio and not info.has_audio:
        problems.append("в ролике нет звука, хотя в монтаже есть звуковые клипы")
    return problems
