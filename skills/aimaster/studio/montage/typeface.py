"""Шрифт монтажа: Inter (OFL-1.1) из навыка → current/assets/fonts, @font-face локально.

HyperFrames 0.8.75 подменяет общий `sans-serif` на Inter и при сети тянет его с
Google Fonts. Шрифт, объявленный в композиции через локальный @font-face, он
встраивает как data URI и в сеть не ходит (проба 2026-09-25: рендер с сетью и
без сети совпал покадрово, framemd5 одинаковый). Поэтому текст в композициях
монтажа — только семейство FONT_FAMILY. Файлы — латиница и кириллица, 400 и 700,
из @fontsource/inter 5.3.0; манифест со sha256 — fonts/fonts.json.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from ..platform_compat import replace_file
from . import MontageError

FONT_DIR = Path(__file__).with_name("fonts")
FONT_FAMILY = "AM Inter"
FONT_STACK = f'"{FONT_FAMILY}", sans-serif'
ASSETS_SUBDIR = "fonts"


def load_manifest() -> dict:
    return json.loads((FONT_DIR / "fonts.json").read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    """Сбой чтения (нет прав, файл пропал между .is_file() и этим вызовом,
    диск отвалился) — MontageError, не голый OSError: verify_bundle это
    обещает и сам, и через sync_fonts (задача 4 раунда 2)."""

    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError as error:
        raise MontageError(f"не удалось прочитать {Path(path).name}: {error}") from error


def verify_bundle(manifest=None) -> list[str]:
    """Файлы шрифта в навыке, которых нет или чей sha256 не совпал с
    манифестом — включая лицензию: OFL требует нести её текст рядом с
    файлами, а не просто сослаться на неё, так что она проверяется наравне
    со шрифтами, а не отдельным особым случаем. Сбой чтения файла (не
    отсутствие, а именно ошибка ФС) — MontageError, не голый OSError."""

    manifest = manifest or load_manifest()
    broken = [item["file"] for item in manifest["files"]
              if not (FONT_DIR / item["file"]).is_file()
              or _sha256(FONT_DIR / item["file"]) != item["sha256"]]
    license_file, license_sha = manifest["license_file"], manifest["license_sha256"]
    if not (FONT_DIR / license_file).is_file() or _sha256(FONT_DIR / license_file) != license_sha:
        broken.append(license_file)
    return broken


def font_face_css(indent: str = "      ", manifest=None) -> str:
    manifest = manifest or load_manifest()
    return "\n".join(
        f'{indent}@font-face {{ font-family: "{FONT_FAMILY}"; '
        f'src: url("assets/{ASSETS_SUBDIR}/{item["file"]}") format("woff2"); '
        f'font-weight: {item["weight"]}; font-style: normal; font-display: block; '
        f'unicode-range: {item["unicode_range"]}; }}'
        for item in manifest["files"])


def sync_fonts(assets_dir: Path, manifest=None) -> list[str]:
    """Кладёт файлы шрифта и лицензию (OFL требует нести её текст рядом —
    условие 2) в <current>/assets/fonts; совпавшие не трогает. Возвращает
    имена скопированных.

    Повреждённый пакет (не тот sha256 у файла шрифта или лицензии, самого
    файла нет) — отказ сразу, до копирования: показывать в композиции
    половину шрифта хуже, чем не показать вовсе. Сбой файловой системы (нет
    прав, диск занят другим процессом на Windows) — MontageError, а не
    голый traceback."""

    manifest = manifest or load_manifest()
    broken = verify_bundle(manifest)
    if broken:
        raise MontageError("пакет навыка повреждён, переустановите: " + ", ".join(broken))
    target_dir = Path(assets_dir) / ASSETS_SUBDIR
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise MontageError(f"не удалось создать папку шрифтов {target_dir}: {error}") from error
    items = [(item["file"], item["sha256"]) for item in manifest["files"]]
    items.append((manifest["license_file"], manifest["license_sha256"]))
    copied = []
    for name, sha256 in items:
        target = target_dir / name
        if target.is_file() and _sha256(target) == sha256:
            continue
        temporary = target.with_name(f".{target.name}.part")
        try:
            shutil.copyfile(FONT_DIR / name, temporary)
            replace_file(temporary, target)
        except OSError as error:
            temporary.unlink(missing_ok=True)
            raise MontageError(f"не удалось скопировать {name}: {error}") from error
        copied.append(name)
    return copied
