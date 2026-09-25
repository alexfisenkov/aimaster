"""Скиллы HyperFrames закреплённой версии: где лежит кеш и как сверить набор.

Кеш — <user_data_dir>/tools/hyperframes-skills/<тег>/<имя>, рядом с папкой движка
(при AIMASTER_HYPERFRAMES_DIR — рядом с подменённой). Хэш набора — алгоритм
`hashSkillBundle` HyperFrames, сверенный на всех 21 скилле v0.8.75: sha256 от
«путь\\0содержимое\\0» по отсортированным путям, CRLF → LF только в текстовых файлах.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from .engine import load_pin, tools_prefix

SKILL_MARKER = ".aimaster-install.json"
TEXT_EXT = frozenset({".md", ".txt", ".mjs", ".js", ".ts", ".jsx", ".tsx", ".html", ".css",
                      ".json", ".svg", ".csv", ".yml", ".yaml"})


def skills_pin() -> dict:
    return load_pin()["skills"]


def skills_cache(*, home=None, environ=None, pin=None) -> Path:
    pin = pin or skills_pin()
    return tools_prefix(home=home, environ=environ).parent / "hyperframes-skills" / pin["tag"]


def any_skills_cached(*, home=None, environ=None, pin=None) -> bool:
    """True, если под hyperframes-skills/ уже что-то стоит — для любого тега,
    не только закреплённого сейчас. Сигнал «скиллы раньше уже ставили»: им
    пользуется --update один (без --install-deps), чтобы не тянуть скиллы с
    нуля на чистой машине, а только перекладывать уже стоящие на новый тег.

    Не роняет исключение при недоступной папке (PermissionError и т.п.) — это
    просто «сигнала нет», не сбой. Точечные каталоги (в т.ч. наши временные
    `.aimaster-tmp-download-…` от оборванной закачки) не считаются — только
    настоящие теговые папки вида «v0.8.75»."""

    cache_root = skills_cache(home=home, environ=environ, pin=pin).parent
    try:
        children = list(cache_root.iterdir())
    except OSError:
        return False
    return any(child.is_dir() and not child.name.startswith(".") for child in children)


def bundle_hash(skill_dir: Path) -> tuple[str, int]:
    """(хэш, число файлов) как у `hyperframes skills check`; пометка aimaster не считается."""

    skill_dir = Path(skill_dir)
    files = sorted((p for p in skill_dir.rglob("*")
                    if p.is_file() and p.name not in (".DS_Store", SKILL_MARKER)),
                   key=lambda p: p.relative_to(skill_dir).as_posix())
    digest = hashlib.sha256()
    for path in files:
        rel = path.relative_to(skill_dir).as_posix()
        data = path.read_bytes()
        if rel[rel.rfind("."):] in TEXT_EXT:
            data = data.decode("utf-8").replace("\r\n", "\n").encode("utf-8")
        digest.update(rel.encode("utf-8") + b"\0" + data + b"\0")
    return digest.hexdigest()[:16], len(files)


def verify_skills(root: Path, pin: dict) -> list[str]:
    """Имена скиллов, которых нет в root или чей хэш не совпал с выпуском.

    Никогда не бросает исключение: повреждённый (не-UTF-8) файл или файл без
    прав на чтение — тоже «скилл не совпал», а не падение установщика."""

    broken = []
    for name, expected in sorted(pin["bundles"].items()):
        folder = Path(root) / name
        try:
            ok = (folder / "SKILL.md").is_file() \
                and bundle_hash(folder) == (expected["hash"], expected["files"])
        except (OSError, ValueError):
            ok = False
        if not ok:
            broken.append(name)
    return broken
