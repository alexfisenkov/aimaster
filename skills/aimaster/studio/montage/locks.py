"""Файловые замки монтажа: один на сборку (`.build.lock`), один на монтажный
стол (`.desk.lock`). ОС снимает замок сама, если держатель умер. Текст OSError
(по-английски, зависит от локали) остаётся только в цепочке исключения."""

from __future__ import annotations

import time
from contextlib import ExitStack, contextmanager
from pathlib import Path

from ..platform_compat import LockBusyError, file_lock
from . import MontageError

POLL_SECONDS = 0.1


@contextmanager
def held_lock(lock_path: Path, *, busy: str, wait: float = 0.0, clock=time.monotonic,
              sleep=time.sleep):
    """Держит замок на `lock_path` на всё тело `with`. Занят дольше `wait`
    секунд — MontageError(busy). try — только вокруг захвата: исключение из
    тела проходит как есть, а не превращается в «занято»."""

    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = lock_path.open("a+", encoding="utf-8")
    except OSError as error:
        raise MontageError(f"не удалось открыть замок {lock_path.name} в папке монтажа") from error
    with handle, ExitStack() as held:
        deadline = clock() + wait
        while True:
            try:
                held.enter_context(file_lock(handle, blocking=False))
                break
            except LockBusyError:
                if clock() >= deadline:
                    raise MontageError(busy) from None
                sleep(POLL_SECONDS)
            except OSError as error:
                raise MontageError("файловая система папки проекта не поддерживает блокировки "
                                   f"({lock_path.name})") from error
        yield
