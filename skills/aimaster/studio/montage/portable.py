"""Allowlisted composition dependencies and checksums; no workspace tree copies."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import unquote

from . import MontageError
from .composition_refs import external_references, references

_SUFFIXES = {".mp4", ".mov", ".webm", ".wav", ".mp3", ".m4a", ".ogg", ".aac",
             ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".woff", ".woff2",
             ".ttf", ".otf", ".css", ".js", ".srt", ".vtt"}
_PRIVATE_PATH = re.compile(r"(?:/Users/|/home/|file://|(?<![A-Za-z0-9+.-])[A-Za-z]:[\\/])", re.I)


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def inside(root, relative):
    if (not isinstance(relative, str) or not relative or "\\" in relative
            or PureWindowsPath(relative).anchor or PurePosixPath(relative).is_absolute()
            or ".." in PurePosixPath(relative).parts):
        raise MontageError("путь экспортируемого файла должен оставаться внутри комплекта")
    root = Path(root).resolve(strict=True)
    candidate = root / relative
    cursor = candidate
    while cursor != root:
        if cursor.is_symlink():
            raise MontageError("ссылки на другие файлы не входят в переносимый комплект")
        cursor = cursor.parent
    try:
        candidate.resolve(strict=True).relative_to(root)
        if not candidate.is_file():
            raise ValueError()
    except (OSError, ValueError) as error:
        raise MontageError("нужный файл комплекта отсутствует или небезопасен") from error
    return candidate


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def copy_file(source, destination):
    if Path(source).is_symlink():
        raise MontageError("нельзя экспортировать символическую ссылку")
    before = digest(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    if digest(destination) != before or digest(source) != before:
        raise MontageError("файл изменился во время копирования комплекта")
    return {"path": destination.name, "sha256": before}


def dependencies(root, text):
    if external_references(text) or _PRIVATE_PATH.search(text):
        raise MontageError("композиция содержит внешнюю ссылку или приватный абсолютный путь")
    pending = [(ref, "") for ref in references(text)]
    collected = {}
    while pending:
        ref, base = pending.pop(0)
        if ref.startswith("#") or ref.lower().startswith("data:"):
            continue
        relative = unquote(ref.split("?", 1)[0].split("#", 1)[0])
        relative = (PurePosixPath(base) / relative).as_posix() if base else relative
        path = inside(root, relative)
        if not relative.startswith("assets/") or path.suffix.lower() not in _SUFFIXES:
            raise MontageError("в переносимый монтаж входят только используемые media, fonts и scripts из assets/")
        if relative in collected:
            continue
        collected[relative] = path
        if path.suffix.lower() in {".css", ".svg"}:
            content = path.read_text(encoding="utf-8")
            markup = "<style>" + content + "</style>" if path.suffix.lower() == ".css" else content
            if external_references(markup) or _PRIVATE_PATH.search(content):
                raise MontageError("зависимость композиции содержит внешнюю ссылку")
            pending.extend((nested, str(PurePosixPath(relative).parent)) for nested in references(markup))
    # OFL travels with redistributed fonts, even though the browser never requests it.
    if any(name.startswith("assets/fonts/") and path.suffix.lower() in {".woff", ".woff2", ".ttf", ".otf"}
           for name, path in collected.items()):
        collected["assets/fonts/OFL.txt"] = inside(root, "assets/fonts/OFL.txt")
    return collected


def copy_composition(source, text, destination):
    destination.mkdir(parents=True, exist_ok=True)
    files = []
    for relative, path in dependencies(source, text).items():
        receipt = copy_file(path, destination / relative)
        files.append({**receipt, "path": relative})
    with (destination / "index.html").open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    files.append({"path": "index.html", "sha256": digest(destination / "index.html")})
    return files


def verify_files(root, files):
    if not isinstance(files, list) or not files:
        raise MontageError("в комплекте нет списка файлов")
    seen = set()
    for entry in files:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or entry["path"] in seen:
            raise MontageError("некорректный список файлов комплекта")
        seen.add(entry["path"])
        if digest(inside(root, entry["path"])) != entry.get("sha256"):
            raise MontageError("контрольная сумма файла комплекта не совпадает")
    return seen
