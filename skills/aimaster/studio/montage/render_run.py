"""Рендер MP4 версии: место под файл в media/<проект>/montage/, запуск
`render` движка, лог montage/.logs/render-vNNN.log и проверка лога на следы
сети. Одна и та же команда рендера — у сборки и у проверки монтажа на CI
(`render_args`)."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from . import MontageError
from .engine import load_pin
from .engine_env import frames_cache
from .index_io import write_text_atomic
from .link_guard import is_link
from .paths import MontagePaths, render_output
from .short_paths import short_paths
from .typeface import FONT_FAMILY
from .verify import network_markers


def render_args(engine, output: Path) -> list[str]:
    """Аргументы `render` движка. --json — как у каждого вызова (engine_cli.argv_for)."""

    pin = load_pin()
    return ["render", ".", "--output", str(output), "--quality", pin["render_quality"],
            "--frames-cache-dir", str(frames_cache(engine)), "--quiet", "--json"]


def remove_output(output: Path) -> None:
    try:
        output.unlink(missing_ok=True)
    except OSError:
        pass  # уборка при уже случившейся ошибке — не подменяет её своей


def _plain_folders(media_root: Path, folder: Path) -> None:
    """media/<проект>/montage — обычные папки или их ещё нет. Ссылка (симлинк,
    junction) увела бы MP4 версии в чужое место. Смотрим только сами папки
    пути (lstat), внутрь не заходим: там рабочие папки рендера HyperFrames."""

    current = Path(media_root)
    for part in Path(folder).relative_to(media_root).parts:
        current = current / part
        shown = current.relative_to(Path(media_root).parent).as_posix()
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            return  # дальше папок нет — создадим их сами
        except OSError as error:
            raise MontageError(f"не удалось проверить папку {shown}") from error
        if is_link(info):
            raise MontageError(f"папка {shown} — ссылка на другое место; собранный ролик туда не "
                               "кладу. Замените её обычной папкой и соберите снова")
        if not stat.S_ISDIR(info.st_mode):
            raise MontageError(f"{shown} — не папка; собранный ролик туда не положить")


def _clear_orphan(media_root: Path, output: Path) -> None:
    """Номер новее всех записанных и опубликованных версий: файл с этим именем
    может остаться только от прерванной сборки — он не версия, его заменяем."""

    _plain_folders(media_root, output.parent)
    try:
        output.unlink(missing_ok=True)
        output.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise MontageError(f"не удалось подготовить место для {output.name}") from error


def _write_log(paths: MontagePaths, version_id: str, text: str) -> str:
    name = f"render-{version_id}.log"
    try:
        write_text_atomic(paths.logs / name, text)
    except MontageError:
        pass  # без лога сборка остаётся сборкой
    return f"montage/.logs/{name}"


def render_mp4(ctx, engine, runner, version_id: str) -> Path:
    """MP4 версии в media/<проект>/montage/vNNN.mp4; лог — montage/.logs/render-vNNN.log.
    Сбой или след сети в логе — MontageError, свой файл удалён."""

    pin = load_pin()
    output = render_output(ctx.media_root, ctx.project_id, version_id)
    _clear_orphan(ctx.media_root, output)
    try:
        result = runner.run(engine, render_args(engine, output), cwd=ctx.paths.current,
                            timeout=pin["timeouts"]["render"])
    except BaseException:  # Ctrl+C или сбой запуска — недописанный MP4 не оставляем
        remove_output(output)
        raise
    log = f"{result.stdout}\n{result.stderr}"
    log_name = _write_log(ctx.paths, version_id, log)
    shown = {ctx.workspace: "<рабочая папка>", engine.prefix: "<движок>"}
    if result.code != 0 or not output.is_file():
        remove_output(output)
        why = (f"не уложилась в {pin['timeouts']['render']} с" if result.timed_out
               else short_paths(result.stderr or result.stdout, shown).strip()[-500:]
               or f"код {result.code}")
        raise MontageError(f"Сборка не удалась: {why} (лог: {log_name})")
    network = network_markers(short_paths(log, shown))
    if network:
        remove_output(output)
        raise MontageError(f"Сборка обращалась в сеть или к чужому шрифту: {'; '.join(network)}. "
                           f"Текст — только шрифтом «{FONT_FAMILY}» (он в assets/fonts), скрипты — "
                           "только локальные из assets/ (GSAP кладёт montage gsap)")
    return output
