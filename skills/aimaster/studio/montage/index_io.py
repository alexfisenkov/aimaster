"""Чтение и запись `index.html` (и прочих текстовых файлов монтажа) на диске.

Отдельно от `html_doc.py`: тот — чистый разбор/правка текста, без I/O; здесь
— файловая система. `newline=""` всюду: CRLF файла, который правила Studio
на Windows, не должен превращаться в LF при точечной правке ни на чтении,
ни на записи.

`Path.read_text(..., newline=...)` появился только в Python 3.13 (CI —
3.11/3.12/3.13, сборка с ним красная на более старых) — читаем через
`Path.open(..., newline="")`, не через `read_text`."""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

from ..platform_compat import replace_file
from . import MontageError


def _read_umask() -> int:
    # Узнать umask можно только установив новый; читаем один раз при импорте
    # (однопоточный момент), а не на каждой записи из потоков дашборда.
    current = os.umask(0o022)
    os.umask(current)
    return current


_UMASK = _read_umask()


def _target_mode(path: Path) -> int:
    """Права файла после замены: как у заменяемого (владелец мог их задать),
    у нового — 0644 минус umask. mkstemp создаёт временный файл 0600, и без
    этого index.html/hyperframes.json после записи не читал бы никто, кроме
    владельца процесса."""

    try:
        return stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        return 0o644 & ~_UMASK


def write_text_atomic(path: Path, text: str) -> None:
    """Пишет текстовый файл через временный + атомарную замену, `newline=""`
    — `text` уходит на диск как есть, без перевода строк: свежий текст,
    собранный с `\\n`, получит `\\n`; текст, прочитанный `read_index` из
    файла с CRLF и точечно правленный, вернёт CRLF, не перегонит весь файл
    в LF ради пары атрибутов.

    Временное имя — через `mkstemp` в той же папке: не голое «.name.tmp»
    (параллельная запись того же файла из двух мест иначе коллизирует на
    одном временном имени); права — как у заменяемого файла (`_target_mode`).
    Сбой чтения/записи на любом шаге (нет прав, диск занят другим процессом
    на Windows, диск полон) — MontageError с понятным текстом, а не голый
    traceback; попытка убрать недописанный временный файл не должна
    подменить исходную ошибку своей."""

    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        temporary = Path(temp_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
                handle.write(text)
            os.chmod(temporary, _target_mode(path))
            replace_file(temporary, path)
        except OSError:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass  # чистка — best effort, не маскирует исходную ошибку
            raise
    except OSError as error:
        raise MontageError(f"не удалось записать {path.name}: {error}") from error


def read_index(path: Path) -> str:
    """Читает index.html с `newline=""` — CRLF файла Studio не превращается
    в LF уже на чтении, до того как что-то в нём поправят."""

    try:
        with Path(path).open(encoding="utf-8", newline="") as handle:
            return handle.read()
    except (OSError, UnicodeDecodeError) as error:
        raise MontageError(f"не удалось прочитать черновик: {error}") from error


def write_index(path: Path, text: str) -> None:
    """index.html — тот же атомарный писатель, что и для прочих файлов
    монтажа (`hyperframes.json`); имя отдельное — для читаемости вызова."""

    write_text_atomic(path, text)
