"""Монтажный стол: интерфейс Desk и реализация StudioDesk — HyperFrames Studio в
соседней вкладке. Один процесс `preview` на проект (замок montage/.desk.lock на
открытие и закрытие); pid, порт, адрес и время запуска процесса — в
montage/.desk.json. Останавливается только доказанно свой процесс
(`desk_identity`, свои Popen — `desk_children`). Вариант 2 (свой стол внутри дашборда) — другая реализация
того же интерфейса. Остановка по простою и при выходе сервера дашборда, а также
страница-переходник, которая ставит `TELEMETRY_STORAGE_KEY` на origin Studio до
её первой загрузки, — план Б (`studio_origin` — для неё)."""

from __future__ import annotations

import socket
import time
from typing import Protocol
from urllib.parse import urlsplit

from . import MontageError, desk_children
from .desk_identity import FOREIGN, GONE, HUNG, OPEN, fetch_config, verdict
from .desk_record import (FORGET_TEXT, FORGOTTEN, KEPT, KEPT_NOTE, REPLACED, forget_record,
                          read_record, ready_line, record_from_ready, record_text, write_record)
from .engine import Engine, load_pin
from .engine_cli import popen_engine
from .locks import held_lock
from .paths import MontagePaths
from .proc import PidHandle, process_alive, process_started
from .proc_tree import kill_tree
from .short_paths import short_paths

TELEMETRY_STORAGE_KEY = "hyperframes-studio:telemetryDisabled"
PUBLIC_KEYS = ("url", "port", "pid", "started_at")
DESK_LOCK_WAIT = 5.0
BUSY = "монтажный стол этого проекта сейчас открывают или закрывают — повторите через минуту"


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

    try:
        kill_tree(PidHandle(pid))
    except OSError as error:
        raise MontageError(f"не удалось остановить монтажный стол (процесс {pid})") from error


def _public(record: dict) -> dict:
    return {key: record[key] for key in PUBLIC_KEYS if key in record}


def _forgotten_note(record: dict | None, seen: str, outcome: str | None) -> dict:
    """Чужой процесс — что стало с записью (итог `forget_record`); свой — только
    если запись не удалилась."""

    if seen != FOREIGN:
        return {"note": KEPT_NOTE} if outcome == KEPT else {}
    return {"forgotten": f"процесс {record['pid']} на порту {record['port']} — уже не монтажный стол "
                         f"этого проекта: {FORGET_TEXT[outcome]}, ничего не остановлено"}


class StudioDesk:
    def __init__(self, engine: Engine | None, *, popen=None, clock=time.monotonic,
                 sleep=time.sleep, alive=process_alive, config=fetch_config,
                 started=process_started, kill=stop_process):
        self.engine, self.popen, self.clock, self.sleep = engine, popen, clock, sleep
        self.alive, self.config, self.started, self.kill = alive, config, started, kill

    def _check(self, paths: MontagePaths) -> tuple[str | None, dict | None, str]:
        text = record_text(paths)
        record = read_record(paths, text)
        if record is None:
            return text, None, GONE
        return text, record, verdict(record, paths, config=self.config, alive=self.alive,
                                     started=self.started, own=desk_children.own(paths, record))

    def _stop(self, paths: MontagePaths, pid: int) -> None:
        self.kill(pid)
        desk_children.forget(paths, pid)

    def _lock(self, paths: MontagePaths, wait: float = DESK_LOCK_WAIT):
        return held_lock(paths.root / ".desk.lock", wait=wait, clock=self.clock, sleep=self.sleep,
                         busy=BUSY)

    def status(self, paths: MontagePaths) -> dict:
        text, record, seen = self._check(paths)
        if seen == OPEN:
            return {"state": "open", **_public(record)}
        if seen == HUNG:  # свой, но молчит: запись — чтобы open/close его остановили
            return {"state": "closed", "note": "монтажный стол не отвечает — его остановит "
                                               "montage open или montage close"}
        outcome = None if text is not None else FORGOTTEN
        if text is not None:
            try:  # open/close идут прямо сейчас — запись им, status её не трогает
                with self._lock(paths, wait=0):
                    outcome = forget_record(paths, if_text=text)
            except MontageError:
                pass
        return {"state": "closed", **_forgotten_note(record, seen, outcome)}

    def close(self, paths: MontagePaths) -> dict:
        if not paths.root.is_dir():
            return {"state": "closed"}  # монтажа нет — и стола нет, папок не заводим
        with self._lock(paths):
            _text, record, seen = self._check(paths)
            if seen in (OPEN, HUNG):
                self._stop(paths, record["pid"])
            return {"state": "closed", **_forgotten_note(record, seen, forget_record(paths))}

    def open(self, paths: MontagePaths) -> dict:
        if not paths.index.is_file():
            raise MontageError("черновика ещё нет: сначала montage draft")
        with self._lock(paths):
            _text, record, seen = self._check(paths)
            if seen == OPEN:
                return {"state": "open", **_public(record)}
            if seen == HUNG:
                self._stop(paths, record["pid"])  # зависший свой стол — остановить, прежде чем поднимать новый
            outcome = forget_record(paths)
            if self.engine is None:
                raise MontageError("Монтажный движок не готов: монтажный стол не запустить")
            opened = self._launch(paths)  # не удалённую прежнюю запись заменила запись нового стола
            return {**opened, **_forgotten_note(record, seen, REPLACED if outcome == KEPT else outcome)}

    def _launch(self, paths: MontagePaths) -> dict:
        port, log = free_port(), paths.logs / "desk.log"
        extra = {} if self.popen is None else {"popen": self.popen}
        process = popen_engine(self.engine, ["preview", ".", "--foreground", "--json", "--no-open",
                                             "--port", str(port)],
                               cwd=paths.current, log_path=log, **extra)
        try:  # с первой строки после запуска: Ctrl+C здесь не оставит Studio и Chrome без записи
            started = self.started(process.pid)
            desk_children.remember(paths, process, started)
            return self._await_ready(paths, process, port, log, started)
        except BaseException:
            self._stop(paths, process.pid)
            raise

    def _await_ready(self, paths: MontagePaths, process, port: int, log, started) -> dict:
        timeout = load_pin()["timeouts"]["preview_start"]
        deadline = self.clock() + timeout
        while self.clock() < deadline:
            ready = ready_line(log)
            if ready:
                record = record_from_ready(ready, pid=process.pid, port=port, process_started=started,
                                           montage_root=desk_children.root_key(paths))
                write_record(paths, record)
                return {"state": "open", **_public(record)}
            if process.poll() is not None:
                break
            self.sleep(0.2)
        text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
        tail = short_paths(text, {paths.root: "montage", self.engine.prefix: "<движок>"}).strip()[-300:]
        raise MontageError(f"Монтажный стол не запустился за {timeout} с: {tail}")
