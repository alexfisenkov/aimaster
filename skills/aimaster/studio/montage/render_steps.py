"""Шаги сборки версии — все под `build_lock`: подготовка index.html, проверки
до движка, проверка готового файла. Сам рендер MP4 — `render_run.py`, порядок
шагов и запись версии — `render.py`."""

from __future__ import annotations

from pathlib import Path

from ..workspace import MONTAGE_MAX_BYTES
from . import AUDIO_LAYER_NAMES, MontageError
from .canvas import DEFAULT_HEIGHT, DEFAULT_WIDTH, Canvas
from .composition_refs import check_composition
from .engine import load_pin
from .html_doc import ROOT_ID, element_attrs
from .index_io import read_index, write_index
from .model import Model, read_model
from .paths import MontagePaths
from .short_paths import short_paths
from .split_fades import normalize_split_fades
from .verify import lint_problems, lint_warnings, output_problems


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
    shown = {paths.root: "montage", engine.prefix: "<движок>"}
    problems = [short_paths(problem, shown) for problem in lint_problems(report)]
    if problems:
        raise MontageError("Проверка монтажа (lint) нашла ошибки (текст движка, по-английски): "
                           + "; ".join(problems))
    warnings = [short_paths(warning, shown) for warning in lint_warnings(report)]
    return read_model(engine, paths.current, cache_dir=paths.cache, runner=runner), warnings


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
