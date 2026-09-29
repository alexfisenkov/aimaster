"""Синтетический проект и команды агента между браузерными фазами.

Проект — тот же, что у смоука чистой машины с движком
(`smoke_montage.project_ready_for_assembly`): видео в автопилоте, две сцены
(клипы ffmpeg 2 с и 1 с), стадии одобрены до «Сборки». Дальше — как агент:
`montage draft` → `montage render` (v001); после правки мышью в Studio —
`montage diff`, ревизия из `montage status`, `montage render --by owner` (v002).
Каждая команда — отдельным процессом `creator_studio.py`, как у агента."""

from __future__ import annotations

import os
from pathlib import Path

from smoke_clean_machine import clean_env
from smoke_kit import cli
from smoke_montage import MONTAGE_PROJECT, project_ready_for_assembly

TITLE = "Проба «монтаж»"  # название проекта смоука — из него имя файла «Скачать»
PROJECT = MONTAGE_PROJECT


def check_env(home: Path, engine_dir: Path) -> dict:
    """Окружение команд и дашборда: свой HOME (как у смоука чистой машины) и
    своя папка движка. Движок без записи — пустая папка, как у человека без
    установки."""

    env = clean_env(home)
    env["AIMASTER_HYPERFRAMES_DIR"] = str(engine_dir)
    return env


def v001(env: dict, workspace: Path) -> dict:
    cli(env, "workspace", "init", workspace)
    revision = project_ready_for_assembly(env, workspace)
    drafted = cli(env, "montage", "draft", workspace, PROJECT, "--expected-revision", revision)
    built = cli(env, "montage", "render", workspace, PROJECT, "--expected-revision", drafted["revision"])
    return {"draft": drafted, "render": built}


def owner_render(env: dict, workspace: Path) -> dict:
    """Что сделает агент по «Собрать ролик → чат»: diff, ревизия, сборка от имени человека."""

    diff = cli(env, "montage", "diff", workspace, PROJECT)
    status = cli(env, "montage", "status", workspace, PROJECT, "--json")
    built = cli(env, "montage", "render", workspace, PROJECT, "--expected-revision", status["revision"],
                "--by", "owner")
    return {"diff": diff, "status": status, "render": built}


def index_path(workspace: Path) -> Path:
    return Path(workspace) / "projects" / PROJECT / "montage" / "current" / "index.html"


def desk_file(workspace: Path) -> Path:
    return Path(workspace) / "projects" / PROJECT / "montage" / ".desk.json"


def empty_dir(path: Path) -> Path:
    os.makedirs(path, exist_ok=True)
    return path
