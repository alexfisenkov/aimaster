"""Монтажный стол: интерфейс Desk и реализация StudioDesk — HyperFrames Studio в
соседней вкладке. Один процесс `preview` на проект (замок montage/.desk.lock на
открытие и закрытие); pid, порт, адрес и время запуска процесса — в
montage/.desk.json. Останавливается только доказанно свой процесс
(`desk_identity`). Вариант 2 (свой стол внутри дашборда) — другая реализация
того же интерфейса. Остановка по простою и при выходе сервера дашборда, а также
страница-переходник, которая ставит `TELEMETRY_STORAGE_KEY` на origin Studio до
её первой загрузки, — план Б (`studio_origin` — для неё)."""

from __future__ import annotations

import socket
import subprocess
import time
from typing import Protocol
from urllib.parse import urlsplit

from . import MontageError
from .desk_identity import FOREIGN, HUNG, OPEN, fetch_config, verdict
from .desk_record import forget_record, read_record, ready_line, record_from_ready, write_record
from .engine import Engine, load_pin
from .engine_cli import popen_engine
from .locks import held_lock
from .paths import MontagePaths
from .proc import PidHandle, process_alive, process_started
from .proc_tree import kill_tree

TELEMETRY_STORAGE_KEY = "hyperframes-studio:telemetryDisabled"
PUBLIC_KEYS = ("url", "port", "pid", "started_at")
DESK_LOCK_WAIT = 5.0
_children: dict[int, subprocess.Popen] = {}  # столы, запущенные этим процессом: Popen — доказательство


class Desk(Protocol):
    def open(self, paths: MontagePaths) -> dict: ...

    def close(self, paths: MontagePaths) -> dict: ...

    def status(self, paths: MontagePaths) -> dict: ...


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def studio_origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def stop_process(pid: int) -> None:
    """Стол вместе с детьми (Chrome превью, ffmpeg) — через proc_tree.kill_tree."""

    child = _children.get(pid)
    try:
        kill_tree(child or PidHandle(pid))
    except OSError as error:
        raise MontageError(f"не удалось остановить монтажный стол (процесс {pid})") from error
    if child is not None:
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


def _closed(record: dict | None, seen: str) -> dict:
    if seen != FOREIGN:
        return {"state": "closed"}
    return {"state": "closed", "forgotten": (
        f"процесс {record['pid']} на порту {record['port']} — уже не монтажный стол этого "
        "проекта: запись забыта, ничего не остановлено")}


class StudioDesk:
    def __init__(self, engine: Engine | None, *, popen=None, clock=time.monotonic,
                 sleep=time.sleep, alive=process_alive, config=fetch_config,
                 started=process_started, kill=stop_process):
        self.engine, self.popen, self.clock, self.sleep = engine, popen, clock, sleep
        self.alive, self.config, self.started, self.kill = alive, config, started, kill

    def _check(self, paths: MontagePaths) -> tuple[dict | None, str]:
        record = read_record(paths)
        if record is None:
            return None, "gone"
        return record, verdict(record, paths, config=self.config, alive=self.alive,
                               started=self.started, child=_children.get(record["pid"]))

    def _stop(self, pid: int) -> None:
        self.kill(pid)
        _children.pop(pid, None)

    def _lock(self, paths: MontagePaths):
        return held_lock(paths.root / ".desk.lock", wait=DESK_LOCK_WAIT, clock=self.clock,
                         sleep=self.sleep, busy="монтажный стол этого проекта сейчас открывают "
                                                "или закрывают — повторите через минуту")

    def status(self, paths: MontagePaths) -> dict:
        record, seen = self._check(paths)
        if seen == OPEN:
            return {"state": "open", **{key: record[key] for key in PUBLIC_KEYS if key in record}}
        if seen == HUNG:  # свой, но молчит: запись — чтобы open/close его остановили
            return {"state": "closed", "note": "монтажный стол не отвечает — его остановит "
                                               "montage open или montage close"}
        forget_record(paths)
        return _closed(record, seen)

    def close(self, paths: MontagePaths) -> dict:
        with self._lock(paths):
            record, seen = self._check(paths)
            if seen in (OPEN, HUNG):
                self._stop(record["pid"])
            forget_record(paths)
            return _closed(record, seen)

    def open(self, paths: MontagePaths) -> dict:
        if not paths.index.is_file():
            raise MontageError("черновика ещё нет: сначала montage draft")
        with self._lock(paths):
            record, seen = self._check(paths)
            if seen == OPEN:
                return {"state": "open", **{key: record[key] for key in PUBLIC_KEYS if key in record}}
            if seen == HUNG:
                self._stop(record["pid"])  # зависший свой стол — остановить, прежде чем поднимать новый
            forget_record(paths)
            if self.engine is None:
                raise MontageError("Монтажный движок не готов: монтажный стол не запустить")
            return self._launch(paths)

    def _launch(self, paths: MontagePaths) -> dict:
        port, log = free_port(), paths.logs / "desk.log"
        extra = {} if self.popen is None else {"popen": self.popen}
        process = popen_engine(self.engine, ["preview", ".", "--foreground", "--json", "--no-open",
                                             "--port", str(port)],
                               cwd=paths.current, log_path=log, **extra)
        _children[process.pid] = process
        try:
            return self._await_ready(paths, process, port, log)
        except BaseException:
            self._stop(process.pid)
            raise

    def _await_ready(self, paths: MontagePaths, process, port: int, log) -> dict:
        timeout = load_pin()["timeouts"]["preview_start"]
        deadline = self.clock() + timeout
        while self.clock() < deadline:
            ready = ready_line(log)
            if ready:
                record = record_from_ready(ready, pid=process.pid, port=port,
                                           process_started=self.started(process.pid))
                write_record(paths, record)
                return {"state": "open", **{key: record[key] for key in PUBLIC_KEYS}}
            if process.poll() is not None:
                break
            self.sleep(0.2)
        tail = log.read_text(encoding="utf-8", errors="replace").strip()[-300:] if log.exists() else ""
        raise MontageError(f"Монтажный стол не запустился за {timeout} с: {tail}")
