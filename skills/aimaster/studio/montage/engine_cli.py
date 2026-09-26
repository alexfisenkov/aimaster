"""Запуск CLI HyperFrames: без оболочки, `node <…>/bin/hyperframes.mjs <команда>`.

Окружение запуска — `engine_env`, процесс и остановка его узла — `proc_runner`
(имена оттуда доступны и отсюда). В каждой команде — флаг --json (`argv_for`).
Отказ CLI (код 2, JSON в stderr) превращается в понятный `MontageError`.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from . import MontageError
from .engine import Engine
from .engine_env import (  # noqa: F401 — прежние имена engine_cli.*
    FF_VARIABLES, QUIET_FLAGS, engine_env, engine_home, frames_cache)
from .proc_runner import default_runner
from .proc_tree import CREATE_NEW_PROCESS_GROUP, CREATE_NO_WINDOW, group_kwargs  # noqa: F401
from .replace_target import open_fresh
from .short_paths import short_paths


@dataclass(frozen=True)
class EngineResult:
    code: int
    stdout: str
    stderr: str
    timed_out: bool = False


JSON_FLAG = "--json"


def argv_for(engine: Engine, args: Sequence[str]) -> list[str]:
    """argv запуска движка; --json добавляется, если его нет. HyperFrames 0.8.75
    (dist/cli.js, `hasJsonFlag`) без --json на каждом запуске проверяет
    обновления — свои (registry.npmjs.org) и своих скиллов (`git ls-remote`
    github.com и raw.githubusercontent.com), — и никакая переменная окружения
    этого не отключает. `render` и `browser` флаг принимают, их вывод не меняется
    (у `render` он действует только с --batch)."""

    items = [str(item) for item in args]
    if JSON_FLAG not in items:
        items.append(JSON_FLAG)
    return [engine.node, str(engine.script), *items]


def _decode(raw) -> str:
    return (raw or b"").decode("utf-8", errors="replace")


def run_engine(engine: Engine, args: Sequence[str], *, cwd: Path, timeout: float,
               runner=default_runner) -> EngineResult:
    engine_home(engine).mkdir(parents=True, exist_ok=True)
    try:
        proc = runner(argv_for(engine, args), cwd=str(cwd), env=engine_env(engine, cwd=cwd),
                      stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                      stderr=subprocess.PIPE, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        reason = f"не завершился за {timeout:g} с"
        partial = _decode(error.stderr)
        stderr = f"{partial}\n{reason}" if partial else reason
        return EngineResult(124, _decode(error.output), stderr, True)
    except OSError:
        # текст OSError — по-английски и с путём к node; он не для человека
        return EngineResult(127, "", "не удалось запустить Node.js движка — проверьте установку: "
                                     "montage status")
    return EngineResult(proc.returncode, _decode(proc.stdout), _decode(proc.stderr))


def _json_payload(text: str):
    text = (text or "").strip()
    start = text.find("{")
    if start < 0:
        return None
    try:
        # raw_decode вместо loads: остаток строки после JSON (хвостовой лог,
        # перевод строки) не должен валить разбор — нам нужен только объект.
        value, _ = json.JSONDecoder().raw_decode(text[start:])
    except ValueError:
        return None
    return value


def run_engine_json(engine: Engine, args: Sequence[str], *, cwd: Path, timeout: float,
                    ok_codes=(0,), runner=default_runner) -> dict:
    result = run_engine(engine, args, cwd=cwd, timeout=timeout, runner=runner)
    command = " ".join(map(str, list(args)[:2]))
    if result.timed_out:
        raise MontageError(f"HyperFrames «{command}» не ответил за {timeout:g} с")
    if result.code not in ok_codes:
        refusal = _json_payload(result.stderr) or _json_payload(result.stdout)
        shown = {cwd: ".", engine.prefix: "<движок>"}
        if isinstance(refusal, dict) and refusal.get("reason"):
            fix = f" ({refusal['fix']})" if refusal.get("fix") else ""
            raise MontageError(short_paths(f"HyperFrames отказал выполнить «{command}» — причина "
                                           f"словами движка, по-английски: {refusal['reason']}{fix}",
                                           shown))
        tail = short_paths(result.stderr or result.stdout, shown).strip()[-600:]
        raise MontageError(f"HyperFrames «{command}» завершился с кодом {result.code}: {tail}")
    payload = _json_payload(result.stdout)
    if not isinstance(payload, dict):
        raise MontageError(f"HyperFrames «{command}» вернул не JSON")
    return payload


def popen_engine(engine: Engine, args: Sequence[str], *, cwd: Path, log_path: Path,
                 popen=subprocess.Popen):
    """Отдельный процесс (монтажный стол): переживает вызвавший его CLI.

    POSIX — своя сессия (группа для остановки с детьми); Windows — своя группа
    процессов и скрытая консоль, чтобы Chrome и ffmpeg не открывали окна."""

    engine_home(engine).mkdir(parents=True, exist_ok=True)
    try:  # журнал — не по симлинку: «wb» по ссылке обнулил бы чужой файл (replace_target)
        log = open_fresh(log_path)
    except OSError as error:
        raise MontageError(f"не удалось открыть журнал {Path(log_path).name} монтажного стола") from error
    with log:
        try:
            return popen(argv_for(engine, args), cwd=str(cwd), env=engine_env(engine, cwd=cwd),
                         stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                         **group_kwargs())
        except OSError as error:
            raise MontageError("не удалось запустить HyperFrames — проверьте установку: "
                               "montage status") from error


class EngineRunner:
    """Настоящий запуск. Тесты подставляют объект с теми же двумя методами."""

    def json(self, engine: Engine, args, *, cwd: Path, timeout: float, ok_codes=(0,)) -> dict:
        return run_engine_json(engine, args, cwd=cwd, timeout=timeout, ok_codes=ok_codes)

    def run(self, engine: Engine, args, *, cwd: Path, timeout: float) -> EngineResult:
        return run_engine(engine, args, cwd=cwd, timeout=timeout)
