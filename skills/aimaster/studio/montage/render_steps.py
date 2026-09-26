"""Шаги сборки версии — все под `build_lock`: подготовка index.html, проверки
до движка, рендер MP4 с логом, проверка готового файла. Порядок шагов и
запись версии — `render.py`."""

from __future__ import annotations

from pathlib import Path

from ..workspace import MONTAGE_MAX_BYTES
from . import AUDIO_LAYER_NAMES, MontageError
from .canvas import DEFAULT_HEIGHT, DEFAULT_WIDTH, Canvas
from .composition_refs import check_composition
from .engine import load_pin
from .engine_cli import frames_cache
from .html_doc import ROOT_ID, element_attrs
from .index_io import read_index, write_index, write_text_atomic
from .model import Model, read_model
from .paths import MontagePaths, render_output
from .short_paths import short_paths
from .split_fades import normalize_split_fades
from .typeface import FONT_FAMILY
from .verify import lint_problems, lint_warnings, network_markers, output_problems


def normalized_index(paths: MontagePaths, base: Model | None, *, trusted: bool = True) -> str:
    """Текст для сборки. У половин разреза, которых не было в прошлой версии
    (разрез мышью в Studio — наш путь правок его не видит), сняты внутренние
    края звука; половины, известные прошлой версии, не трогаем — их края мог
    поправить человек. Версий ещё не было — новыми считаются все клипы
    (черновик пар разреза не создаёт). Снимок прошлой версии потерян или
    повреждён (`trusted=False`) — не знаем, что новое, и не трогаем ничего.
    Пишем, только если файл всё ещё тот, что прочитали (Studio могла успеть)."""

    original = read_index(paths.index)
    if not trusted:
        return original
    known = {clip.id for clip in base.clips} if base is not None else set()
    scope = [element_id for element_id in element_attrs(original)
             if element_id != ROOT_ID and element_id not in known]
    text, changed = normalize_split_fades(original, only=scope)
    if changed:
        if read_index(paths.index) != original:
            raise MontageError("монтаж поменяли, пока сборка готовила его (например, в монтажном "
                               "столе) — соберите ещё раз")
        write_index(paths.index, text)
    return text


def preflight(paths: MontagePaths, engine, runner, text: str) -> tuple[Model, list[str]]:
    """Ссылки композиции (без движка) → lint → модель. Возвращает модель и предупреждения lint."""

    problems = check_composition(text, paths.current)
    if problems:
        raise MontageError("Монтаж нельзя собрать: " + "; ".join(problems))
    report = runner.json(engine, ["lint", ".", "--json"], cwd=paths.current,
                         timeout=load_pin()["timeouts"]["cli"], ok_codes=(0, 1))
    problems = [short_paths(problem, {paths.root: "montage", engine.prefix: "<движок>"})
                for problem in lint_problems(report)]
    if problems:
        raise MontageError("Проверка монтажа (lint) нашла ошибки: " + "; ".join(problems))
    return read_model(engine, paths.current, cache_dir=paths.cache, runner=runner), lint_warnings(report)


def remove_output(output: Path) -> None:
    try:
        output.unlink(missing_ok=True)
    except OSError:
        pass  # уборка при уже случившейся ошибке — не подменяет её своей


def _clear_orphan(output: Path) -> None:
    """Номер новее всех записанных и опубликованных версий: файл с этим именем
    может остаться только от прерванной сборки — он не версия, его заменяем."""

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
    _clear_orphan(output)
    # --json: без него движок на каждой сборке ходит за обновлениями (engine_cli.argv_for)
    try:
        result = runner.run(engine, ["render", ".", "--output", str(output), "--quality",
                                     pin["render_quality"], "--frames-cache-dir",
                                     str(frames_cache(engine)), "--quiet", "--json"],
                            cwd=ctx.paths.current, timeout=pin["timeouts"]["render"])
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


def _canvas(text: str, recorded) -> Canvas:
    """Кадр — с корня композиции (его меняет Studio), иначе записанный в state черновиком."""

    root = element_attrs(text).get(ROOT_ID, {})
    for width, height in ((root.get("data-width"), root.get("data-height")),
                          ((recorded or {}).get("width"), (recorded or {}).get("height"))):
        try:
            return Canvas(int(float(width)), int(float(height)))
        except (TypeError, ValueError):
            continue
    return Canvas(DEFAULT_WIDTH, DEFAULT_HEIGHT)


def checked_output(output: Path, model: Model, text: str, probe, *, recorded_canvas=None) -> float:
    """ffprobe готового файла против модели и холста; возвращает длительность ролика."""

    info = probe(output)
    needs_audio = any(clip.layer in AUDIO_LAYER_NAMES for clip in model.clips)
    problems = output_problems(info, duration=model.duration, canvas=_canvas(text, recorded_canvas),
                               needs_audio=needs_audio)
    if problems:
        raise MontageError("Собранный ролик не прошёл проверку: " + "; ".join(problems))
    try:
        size = output.stat().st_size
    except OSError as error:
        raise MontageError(f"собранный ролик {output.name} пропал до проверки") from error
    if size > MONTAGE_MAX_BYTES:
        raise MontageError(f"Ролик больше {MONTAGE_MAX_BYTES // 2 ** 30} ГБ — такой файл студия "
                           "не примет; сократите монтаж")
    return info.duration
