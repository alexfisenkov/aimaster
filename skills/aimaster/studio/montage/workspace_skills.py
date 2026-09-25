"""Скиллы HyperFrames в рабочей папке: <ws>/.claude/skills/<имя> (Claude Code) и
<ws>/.agents/skills/<имя> (Codex) — копией из кеша с пометкой «поставлено aimaster».

Глобально (~/.claude/skills, ~/.agents/skills) не ставятся — решение владельца
2026-09-25: Claude Code читает .claude/skills в папке запуска и выше до корня
репозитория, Codex — $CWD/.agents/skills так же. Чужая папка с тем же именем не
трогается (conflict); пересобирается только наша копия другой версии. Рабочая
папка не может быть самой домашней — тогда статус skipped_home, без записи.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

from .engine import install_command
from .home_guard import would_write_into_home
from .skill_bundle import SKILL_MARKER, skills_cache, skills_pin, verify_skills

AGENT_DIRS = ((".claude", "skills"), (".agents", "skills"))
HOME_SKIP_MESSAGE = ("рабочая папка — домашняя, скиллы HyperFrames ставятся только в папку "
                     "видеопроектов")
# ".<имя>-" совпал бы с чужой папкой вроде «.hyperframes-backup» (у скилла
# как раз есть имя «hyperframes») — вид ниже точно совпадает с тем, что
# создаёт tempfile.mkdtemp, и только это сверяется при уборке.
TEMP_PREFIX = ".aimaster-tmp-"
TEMP_MIN_AGE_SECONDS = 3600  # не трогаем то, что моложе часа — вдруг чужой параллельный запуск


def inspect_copy(target: Path, version: str) -> str:
    """missing | current | outdated | foreign."""

    if target.is_symlink() or (target.exists() and not target.is_dir()):
        return "foreign"
    if not target.exists():
        return "missing"
    try:
        marker = json.loads((target / SKILL_MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "foreign"
    if not isinstance(marker, dict) or marker.get("installed_by") != "aimaster":
        return "foreign"
    return "current" if marker.get("version") == version else "outdated"


def _sweep_stale(parent: Path, name: str, *, min_age=TEMP_MIN_AGE_SECONDS) -> None:
    """Убирает СВОИ временные папки от прошлых оборванных копий: точное имя
    вида, который создаёт tempfile.mkdtemp для этого скилла (не префиксный
    glob), и только не моложе часа — свежая может быть рабочей папкой
    параллельно идущей установки. Звать один раз в начале операции, до того
    как _copy создаст СВОЮ рабочую папку — иначе можно смести и её.

    Уборка — забота, не обязанность: недоступная (0o300 и т.п.) родительская
    папка не должна ронять всю установку — просто ничего не убираем."""

    if not parent.is_dir():
        return
    pattern = re.compile(r"^" + re.escape(f"{TEMP_PREFIX}{name}-") + r"[A-Za-z0-9_]+$")
    try:
        children = list(parent.iterdir())
    except OSError:
        return
    now = time.time()
    for path in children:
        if not pattern.match(path.name) or path.is_symlink() or not path.is_dir():
            continue
        try:
            age = now - path.stat().st_mtime
        except OSError:
            continue
        if age >= min_age:
            shutil.rmtree(path, ignore_errors=True)


def _copy(source: Path, target: Path, version: str) -> None:
    """Новая копия собирается рядом и встаёт на место; прежняя наша уходит
    только после. Уборка мусора — не здесь, а один раз в начале
    sync_workspace_skills (иначе она рисковала бы смести work/old прямо
    посреди этой же операции)."""

    target.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f"{TEMP_PREFIX}{target.name}-", dir=str(target.parent)))
    try:
        fresh, old = work / "new", work / "old"
        shutil.copytree(source, fresh, ignore=shutil.ignore_patterns(".DS_Store", "__pycache__"))
        (fresh / SKILL_MARKER).write_text(json.dumps(
            {"installed_by": "aimaster", "source": "hyperframes-skills", "version": version},
            ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if target.exists():
            os.rename(target, old)
        try:
            os.rename(fresh, target)
        except OSError:
            if old.exists() and not target.exists():
                os.rename(old, target)
            raise
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _overall(statuses) -> str:
    for status in ("failed", "conflict", "missing", "installed"):
        if status in statuses:
            return status
    return "found"


def sync_workspace_skills(workspace, *, create=True, home=None, environ=None, pin=None) -> dict:
    pin = pin or skills_pin()
    names = sorted(pin["bundles"])
    base = {"version": pin["tag"], "names": names, "items": [], "message": ""}
    if would_write_into_home(workspace):
        return {**base, "status": "skipped_home", "message": HOME_SKIP_MESSAGE}
    source_root = skills_cache(home=home, environ=environ, pin=pin)
    if verify_skills(source_root, pin):
        return {**base, "status": "missing",
                "message": f"скиллы HyperFrames не скачаны; поставить: {install_command()}"}
    if create:
        # Уборка — один раз в начале, для всех имён и обеих папок агентов,
        # до того как _copy создаст свою собственную рабочую папку.
        for parts in AGENT_DIRS:
            agent_dir = Path(workspace).joinpath(*parts)
            for name in names:
                _sweep_stale(agent_dir, name)
    items = []
    for parts in AGENT_DIRS:
        for name in names:
            target = Path(workspace).joinpath(*parts, name)
            state = inspect_copy(target, pin["tag"])
            item = {"path": str(target), "name": name, "status": "found"}
            if state == "foreign":
                item["status"] = "conflict"
            elif state != "current" and not create:
                item["status"] = "missing"
            elif state != "current":
                try:
                    _copy(source_root / name, target, pin["tag"])
                    item["status"] = "installed"
                except (OSError, shutil.Error) as error:
                    item.update(status="failed", message=str(error)[:300])
            items.append(item)
    status = _overall({item["status"] for item in items})
    conflicts = [item["path"] for item in items if item["status"] == "conflict"]
    if conflicts:
        message = "чужие папки с теми же именами не тронуты: " + ", ".join(conflicts)
    elif status == "missing":
        message = "скиллы HyperFrames не скопированы в рабочую папку: montage draft или workspace init"
    else:
        message = ""
    return {**base, "status": status, "items": items, "message": message}


def skills_summary(workspace, **kwargs) -> dict:
    """Коротко для ответов CLI: статус, версия, что делать."""

    report = sync_workspace_skills(workspace, **kwargs)
    return {key: report[key] for key in ("status", "version", "message")}
