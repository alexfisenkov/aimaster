"""Запуск CLI HyperFrames: без оболочки, `node <…>/bin/hyperframes.mjs <команда>`.

Окружение каждого запуска: тихие флаги HyperFrames, свой HOME движка (кэши,
браузер, настройки не попадают в домашнюю папку человека), путь к скачанному
браузеру и кэш кадров. Отказ CLI (код 2, JSON в stderr) превращается в
понятный `MontageError`.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from ..platform_compat import IS_WINDOWS
from . import MontageError
from .engine import Engine
from .proc_tree import CREATE_NEW_PROCESS_GROUP, CREATE_NO_WINDOW, group_kwargs, kill_tree
from .short_paths import short_paths

QUIET_FLAGS = {
    "HYPERFRAMES_NO_UPDATE_CHECK": "1",
    "HYPERFRAMES_NO_AUTO_INSTALL": "1",
    "HYPERFRAMES_NO_TELEMETRY": "1",
    "HYPERFRAMES_SKIP_SKILLS": "1",
    "NO_COLOR": "1",
    "FORCE_COLOR": "0",
}


@dataclass(frozen=True)
class EngineResult:
    code: int
    stdout: str
    stderr: str
    timed_out: bool = False


def engine_home(engine: Engine) -> Path:
    return Path(engine.prefix) / "home"


def frames_cache(engine: Engine) -> Path:
    return Path(engine.prefix) / "cache" / "frames"


def engine_env(engine: Engine, base: Mapping[str, str] | None = None, *,
               cwd: Path | None = None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    env.update(QUIET_FLAGS)
    if cwd is not None:
        # `preview .` 0.8.75 называет проект по basename($PWD): PWD вызывающего
        # дал бы Studio адрес «#project/<его папка>» вместо папки монтажа.
        env["PWD"] = str(cwd)
    env["HOME"] = str(engine_home(engine))
    if IS_WINDOWS:
        env["USERPROFILE"] = env["HOME"]
    env["HYPERFRAMES_EXTRACT_CACHE_DIR"] = str(frames_cache(engine))
    # Браузер — только из записи установщика, чужой из окружения не наследуем (round 4/5).
    env.pop("HYPERFRAMES_BROWSER_PATH", None)
    if engine.browser:
        env["HYPERFRAMES_BROWSER_PATH"] = engine.browser
    # `preview` слушает HYPERFRAMES_PREVIEW_HOST (иначе 127.0.0.1): чужое значение
    # из окружения человека выставило бы монтажный стол в сеть.
    env["HYPERFRAMES_PREVIEW_HOST"] = "127.0.0.1"
    return env


def argv_for(engine: Engine, args: Sequence[str]) -> list[str]:
    return [engine.node, str(engine.script), *map(str, args)]


def _decode(raw) -> str:
    return (raw or b"").decode("utf-8", errors="replace")


def _close_pipes(proc) -> None:
    """Закрывает proc.stdout/stderr, когда их больше некому дочитать —
    иначе Python предупреждает об утечке открытого файла."""

    for pipe in (getattr(proc, "stdout", None), getattr(proc, "stderr", None)):
        if pipe is not None:
            pipe.close()


def default_runner(argv, *, cwd, env, stdin, stdout, stderr, timeout, popen=subprocess.Popen):
    """Как subprocess.run, но при таймауте (и при любом другом обрыве —
    Ctrl+C, ошибка выше по стеку) останавливает весь узел процессов, а не
    только node, и сохраняет частичный вывод, накопленный до убийства.

    После SIGTERM/SIGKILL (POSIX) дренировать пайпы вторым communicate() без
    таймаута небезопасно: если какой-то потомок (например, Chrome в своей
    сессии) пережил рассылку сигналов дольше ожидаемого и всё ещё держит
    открытым конец пайпа, communicate() зависнет уже без таймаута. На POSIX
    берём то, что уже накопил первый communicate() к моменту TimeoutExpired
    (это данные Python, а не что-то, что нужно дочитывать), и просто
    дожидаемся node через proc.wait(). Windows — другое дело: `taskkill /T
    /F` останавливает всё дерево синхронно и до возврата, поэтому дочитать
    пайпы вторым communicate() там безопасно.

    `popen=` — только для тестов (как и `popen=` у popen_engine): реальные
    вызовы используют subprocess.Popen по умолчанию."""

    proc = popen(argv, cwd=cwd, env=env, stdin=stdin, stdout=stdout, stderr=stderr,
                **group_kwargs())
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as first:
        kill_tree(proc)
        if IS_WINDOWS:
            out, err = proc.communicate()
        else:
            proc.wait()
            out, err = first.output, first.stderr
            _close_pipes(proc)  # communicate() их не дочитывал — закрываем сами
        raise subprocess.TimeoutExpired(argv, timeout, output=out, stderr=err) from None
    except BaseException:
        # Ctrl+C или любая другая ошибка в этом процессе не должны оставить
        # HyperFrames работать дальше — как поступает сам subprocess.run().
        kill_tree(proc)
        proc.wait()
        _close_pipes(proc)
        raise
    return subprocess.CompletedProcess(argv, proc.returncode, out, err)


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
    except OSError as error:
        return EngineResult(127, "", str(error))
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
            raise MontageError(short_paths(f"HyperFrames отказал: {refusal['reason']}{fix}", shown))
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
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "wb") as log:
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
