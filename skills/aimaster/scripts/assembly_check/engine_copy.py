"""Своя папка движка для проверки — как у сквозного теста монтажа
(`test_montage_e2e.own_engine`): всё, что движок пишет (HOME движка, кэш
кадров, монтажный стол), уходит во временную папку проверки, а общая папка
движка только читается.

Дашборд и команды агента ищут движок сами (`engine.locate()`), как у
человека, — через AIMASTER_HYPERFRAMES_DIR. Поэтому своя папка должна
пройти `locate()`: `node_modules` — ссылка на пакеты общей папки (только
чтение; на Windows без прав на ссылки — junction), браузер для сборки —
копия внутри своего HOME движка (`locate()` принимает браузер только
оттуда), запись установщика — своя, с путём к копии. Скиллы HyperFrames —
копия кеша рядом, если он есть. `fingerprint` — отпечаток того, что пишет
только установщик (пакеты, запись, браузер): до и после прогона он обязан
совпасть."""

from __future__ import annotations

import os
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path

from studio.montage import engine
from studio.montage.prefix_layout import read_record, write_record


@dataclass(frozen=True)
class OwnEngine:
    prefix: Path    # AIMASTER_HYPERFRAMES_DIR для дашборда и команд агента
    node: str
    browser: str    # копия chrome-headless-shell в своём HOME движка
    modules: Path   # node_modules общей папки: puppeteer-core для браузерных фаз


def is_dir_link(path: Path) -> bool:
    """Символьная ссылка или junction Windows — но не настоящая папка."""

    try:
        info = os.lstat(path)
    except OSError:
        return False
    tag = getattr(info, "st_reparse_tag", 0)
    return stat.S_ISLNK(info.st_mode) or tag == getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", -1)


def link_dir(target: Path, link: Path) -> None:
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        import _winapi  # junction не требует прав на символьные ссылки
        _winapi.CreateJunction(str(target), str(link))


def unlink_dir(link: Path) -> None:
    """Убрать ссылку, не заходя внутрь: rmtree по ней стёр бы общий движок."""

    if not is_dir_link(link):
        return
    try:
        os.unlink(link)
    except OSError:
        os.rmdir(link)


def own_prefix(root: Path) -> Path:
    return Path(root) / "tools" / "hyperframes"


def make_own_engine(found: engine.Engine, root: Path) -> OwnEngine:
    shared = Path(found.prefix)
    prefix = own_prefix(root)
    prefix.mkdir(parents=True)
    link_dir(shared / "node_modules", prefix / "node_modules")
    browser = Path(os.path.realpath(found.browser))
    inside = browser.relative_to(Path(os.path.realpath(shared / "home")))
    copied = prefix / "home" / inside
    shutil.copytree(browser.parent, copied.parent, symlinks=True)
    write_record(prefix, {**read_record(shared), "browser": str(copied)})
    tag = engine.load_pin()["skills"]["tag"]
    skills = shared.parent / "hyperframes-skills" / tag
    if skills.is_dir():
        shutil.copytree(skills, prefix.parent / "hyperframes-skills" / tag, symlinks=True)
    return OwnEngine(prefix=prefix, node=found.node, browser=str(copied),
                     modules=shared / "node_modules")


def release(root: Path) -> None:
    """Перед удалением временной папки: сперва ссылка на общие пакеты (даже
    если своя папка движка собралась не до конца)."""

    unlink_dir(own_prefix(root) / "node_modules")


def fingerprint(found: engine.Engine) -> tuple:
    """(файлов, байт, последняя правка) пакетов, записи и браузера общей папки."""

    shared = Path(found.prefix)
    places = [shared / "node_modules", shared / engine.RECORD_NAME,
              Path(os.path.realpath(found.browser)).parent]
    count = size = newest = 0
    for place in places:
        files = [place] if place.is_file() else (p for p in place.rglob("*") if not p.is_symlink())
        for path in files:
            try:
                info = path.stat()
            except OSError:
                continue
            count, size, newest = count + 1, size + info.st_size, max(newest, info.st_mtime_ns)
    return count, size, newest
