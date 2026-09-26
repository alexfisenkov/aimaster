"""Общее для смоуков чистой машины: запуск скриптов навыка отдельным процессом,
разбор JSON, проверки и понятная ошибка SmokeError. Имя не test_* — unittest
этот файл не запускает."""

from __future__ import annotations

import json
import locale
import struct
import subprocess
import sys
import zlib
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
SKILL = SCRIPTS.parent
REPO = SKILL.parent.parent
CLI = SCRIPTS / "creator_studio.py"


class SmokeError(Exception):
    pass


def log(message: str) -> None:
    print(message, flush=True)


def decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode(locale.getpreferredencoding(False), errors="replace")


def python_argv() -> list:
    argv = [sys.executable]
    if sys.flags.utf8_mode:
        argv += ["-X", "utf8"]
    return argv


def run(env: dict, *argv, expect_code: int = 0) -> str:
    cmd = python_argv() + [str(item) for item in argv]
    proc = subprocess.run(cmd, env=env, cwd=str(SKILL), stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, timeout=180)
    out, err = decode(proc.stdout), decode(proc.stderr)
    if proc.returncode != expect_code:
        raise SmokeError("команда %s завершилась с кодом %s (ожидали %s)\nstdout: %s\nstderr: %s"
                         % (" ".join(str(a) for a in argv[:3]), proc.returncode, expect_code,
                            out.strip()[-1500:], err.strip()[-1500:]))
    return out


def run_json(env: dict, *argv) -> dict:
    out = run(env, *argv)
    try:
        return json.loads(out)
    except ValueError:
        raise SmokeError("не JSON в выводе %s: %r" % (" ".join(map(str, argv[:3])), out[:500]))


def cli(env: dict, *argv) -> dict:
    return run_json(env, CLI, *argv)


def run_refused(env: dict, *argv) -> str:
    """Команда должна отказать кодом 3 (доменный отказ) без traceback; возвращает stderr."""

    cmd = python_argv() + [str(item) for item in argv]
    proc = subprocess.run(cmd, env=env, cwd=str(SKILL), stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, timeout=180)
    err = decode(proc.stderr)
    expect(proc.returncode == 3 and "Traceback" not in err,
           "команда %s: ждали отказ с кодом 3, получили код %s; stderr: %s"
           % (" ".join(str(a) for a in argv[1:4]), proc.returncode, err[-800:]))
    return err


def expect(condition, message: str) -> None:
    if not condition:
        raise SmokeError(message)


def write_png(path: Path) -> None:
    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\x20\x80\xc0" * 8 for _ in range(8))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
