"""Запуск монтажного стола: процесс `preview` движка на свободном порту
127.0.0.1 и ожидание его первой строки `{"ok":true,"result":{…,"ready":true}}`.
Что делать со столом дальше (запись, проверка «свой ли», остановка) — `desk.py`."""

from __future__ import annotations

import socket

from . import MontageError, desk_children
from .desk_record import public, ready_line, record_from_ready, write_record
from .engine import load_pin
from .engine_cli import popen_engine
from .paths import MontagePaths
from .short_paths import short_paths


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def launch(desk, paths: MontagePaths) -> dict:
    """Новый стол для `desk` (StudioDesk: его движок, popen, started, clock,
    sleep и остановка `_stop`); ответ open. Не поднялся — остановлен и отказ."""

    port, log = free_port(), paths.logs / "desk.log"
    extra = {} if desk.popen is None else {"popen": desk.popen}
    process = popen_engine(desk.engine, ["preview", ".", "--foreground", "--json", "--no-open",
                                         "--port", str(port)],
                           cwd=paths.current, log_path=log, **extra)
    try:  # с первой строки после запуска: Ctrl+C здесь не оставит Studio и Chrome без записи
        if desk.adopt is not None:
            desk.adopt(process)  # до того, как Node запустит детей; не вышло — стол всё равно нужен
        started = desk.started(process.pid)
        desk_children.remember(paths, process, started)
        return _await_ready(desk, paths, process, port, log, started)
    except BaseException:
        desk._stop(paths, process.pid)
        raise


def _await_ready(desk, paths: MontagePaths, process, port: int, log, started) -> dict:
    timeout = load_pin()["timeouts"]["preview_start"]
    deadline = desk.clock() + timeout
    while desk.clock() < deadline:
        ready = ready_line(log)
        if ready:
            record = record_from_ready(ready, pid=process.pid, port=port, process_started=started,
                                       montage_root=desk_children.root_key(paths))
            write_record(paths, record)
            return {"state": "open", **public(record)}
        if process.poll() is not None:
            break
        desk.sleep(0.2)
    text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    tail = short_paths(text, {paths.root: "montage", desk.engine.prefix: "<движок>"}).strip()[-300:]
    raise MontageError(f"Монтажный стол не запустился за {timeout} с: {tail}")
