"""Запуск CLI HyperFrames: без оболочки, `node <…>/bin/hyperframes.mjs <команда>`.

Окружение каждого запуска: тихие флаги HyperFrames, свой HOME движка (кэши,
браузер, настройки не попадают в домашнюю папку человека), путь к скачанному
браузеру и кэш кадров. Отказ CLI (код 2, JSON в stderr) превращается в
понятный `MontageError`.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from ..platform_compat import IS_WINDOWS
from . import MontageError
from .engine import Engine

QUIET_FLAGS = {
    "HYPERFRAMES_NO_UPDATE_CHECK": "1",
    "HYPERFRAMES_NO_AUTO_INSTALL": "1",
    "HYPERFRAMES_NO_TELEMETRY": "1",
    "HYPERFRAMES_SKIP_SKILLS": "1",
    "NO_COLOR": "1",
    "FORCE_COLOR": "0",
}
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000


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


def engine_env(engine: Engine, base: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    env.update(QUIET_FLAGS)
    env["HOME"] = str(engine_home(engine))
    if IS_WINDOWS:
        env["USERPROFILE"] = env["HOME"]
    env["HYPERFRAMES_EXTRACT_CACHE_DIR"] = str(frames_cache(engine))
    if engine.browser:
        env["HYPERFRAMES_BROWSER_PATH"] = engine.browser
    return env


def argv_for(engine: Engine, args: Sequence[str]) -> list[str]:
    return [engine.node, str(engine.script), *map(str, args)]


def _decode(raw) -> str:
    return (raw or b"").decode("utf-8", errors="replace")


def _group_kwargs() -> dict:
    """Popen-флаги, под которыми node становится корнем отдельной группы
    процессов — без этого таймаут убивает только node, а Chrome и ffmpeg,
    которых node запустил, остаются висеть сиротами."""

    return ({"creationflags": CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW} if IS_WINDOWS
           else {"start_new_session": True})


def _taskkill_path() -> str:
    root = os.environ.get("SystemRoot") or os.environ.get("windir") or "C:\\Windows"
    return str(Path(root) / "System32" / "taskkill.exe")


def _kill_tree(proc) -> None:
    """Останавливает весь узел процессов node, а не только сам node.

    POSIX: node запущен лидером своей сессии (`_group_kwargs`), поэтому его
    pgid равен его pid — killpg разом убивает node и всех его детей. Windows:
    сигналов нет, поэтому taskkill /T (дерево) по полному пути System32, без
    оболочки."""

    if IS_WINDOWS:
        subprocess.run([_taskkill_path(), "/T", "/F", "/PID", str(proc.pid)],
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass  # уже сам завершился между таймаутом и попыткой убить


def default_runner(argv, *, cwd, env, stdin, stdout, stderr, timeout, popen=subprocess.Popen):
    """Как subprocess.run, но при таймауте останавливает весь узел процессов,
    а не только node, и сохраняет частичный вывод, накопленный до убийства.

    `popen=` — только для тестов (как и `popen=` у popen_engine): реальные
    вызовы используют subprocess.Popen по умолчанию."""

    proc = popen(argv, cwd=cwd, env=env, stdin=stdin, stdout=stdout, stderr=stderr,
                **_group_kwargs())
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        out, err = proc.communicate()  # дренируем то, что успело накопиться
        raise subprocess.TimeoutExpired(argv, timeout, output=out, stderr=err) from None
    return subprocess.CompletedProcess(argv, proc.returncode, out, err)


def run_engine(engine: Engine, args: Sequence[str], *, cwd: Path, timeout: float,
               runner=default_runner) -> EngineResult:
    engine_home(engine).mkdir(parents=True, exist_ok=True)
    try:
        proc = runner(argv_for(engine, args), cwd=str(cwd), env=engine_env(engine),
                      stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                      stderr=subprocess.PIPE, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        return EngineResult(124, _decode(error.output), _decode(error.stderr), True)
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
        if isinstance(refusal, dict) and refusal.get("reason"):
            fix = f" ({refusal['fix']})" if refusal.get("fix") else ""
            raise MontageError(f"HyperFrames отказал: {refusal['reason']}{fix}")
        tail = (result.stderr or result.stdout).strip()[-600:]
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
            return popen(argv_for(engine, args), cwd=str(cwd), env=engine_env(engine),
                         stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                         **_group_kwargs())
        except OSError as error:
            raise MontageError(f"не удалось запустить HyperFrames: {error}") from error


class EngineRunner:
    """Настоящий запуск. Тесты подставляют объект с теми же двумя методами."""

    def json(self, engine: Engine, args, *, cwd: Path, timeout: float, ok_codes=(0,)) -> dict:
        return run_engine_json(engine, args, cwd=cwd, timeout=timeout, ok_codes=ok_codes)

    def run(self, engine: Engine, args, *, cwd: Path, timeout: float) -> EngineResult:
        return run_engine(engine, args, cwd=cwd, timeout=timeout)
