"""Монтажный стол: интерфейс Desk и реализация StudioDesk — HyperFrames Studio в
соседней вкладке. Один процесс `preview` на проект; pid, порт и адрес — в
montage/.desk.json. Вариант 2 (свой стол внутри дашборда) — другая реализация
того же интерфейса. Остановка по простою и при выходе сервера дашборда, а
также страница-переходник, которая ставит `TELEMETRY_STORAGE_KEY` на origin
Studio до её первой загрузки, — план Б (`studio_origin` — для неё)."""

from __future__ import annotations

import socket
import subprocess
import time
from datetime import datetime, timezone
from typing import Protocol
from urllib.parse import urlsplit

from . import MontageError
from .desk_record import forget_record, read_record, ready_line, write_record
from .engine import Engine, load_pin
from .engine_cli import popen_engine
from .paths import MontagePaths
from .proc import PidHandle, own_session_alive
from .proc_tree import kill_tree

TELEMETRY_STORAGE_KEY = "hyperframes-studio:telemetryDisabled"
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
_children: dict[int, subprocess.Popen] = {}  # свои процессы стола — чтобы прибрать после остановки


class Desk(Protocol):
    def open(self, paths: MontagePaths) -> dict: ...

    def close(self, paths: MontagePaths) -> dict: ...

    def status(self, paths: MontagePaths) -> dict: ...


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def port_answers(port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False


def studio_origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def stop_process(pid: int) -> None:
    """Стол вместе с детьми (Chrome превью, ffmpeg) — через proc_tree.kill_tree."""

    try:
        kill_tree(PidHandle(pid))
    except OSError as error:
        raise MontageError(f"не удалось остановить монтажный стол (процесс {pid})") from error
    child = _children.pop(pid, None)
    if child is not None:
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


class StudioDesk:
    def __init__(self, engine: Engine | None, *, popen=None, clock=time.monotonic,
                 sleep=time.sleep, alive=own_session_alive, answers=port_answers, kill=stop_process):
        self.engine, self.popen, self.clock, self.sleep = engine, popen, clock, sleep
        self.alive, self.answers, self.kill = alive, answers, kill

    def status(self, paths: MontagePaths) -> dict:
        record = read_record(paths)
        if record is None or not self.alive(record["pid"]):
            forget_record(paths)  # процесса нет — запись устарела
            return {"state": "closed"}
        if not self.answers(record["port"]):
            return {"state": "closed"}  # жив, но молчит: запись — чтобы open/close его остановили
        return {"state": "open", **{key: record[key] for key in ("url", "port", "pid", "started_at")
                                    if key in record}}

    def open(self, paths: MontagePaths) -> dict:
        if not paths.index.is_file():
            raise MontageError("черновика ещё нет: сначала montage draft")
        current = self.status(paths)
        if current["state"] == "open":
            return current
        self.close(paths)  # зависший стол этого проекта — остановить, прежде чем поднимать новый
        if self.engine is None:
            raise MontageError("Монтажный движок не готов: монтажный стол не запустить")
        port, log = free_port(), paths.logs / "desk.log"
        extra = {} if self.popen is None else {"popen": self.popen}
        process = popen_engine(self.engine, ["preview", ".", "--foreground", "--json", "--no-open",
                                             "--port", str(port)],
                               cwd=paths.current, log_path=log, **extra)
        if self.popen is None:
            _children[process.pid] = process
        try:
            return self._await_ready(paths, process, port, log)
        except BaseException:
            self.kill(process.pid)
            raise

    def _await_ready(self, paths: MontagePaths, process, port: int, log) -> dict:
        timeout = load_pin()["timeouts"]["preview_start"]
        deadline = self.clock() + timeout
        while self.clock() < deadline:
            ready = ready_line(log)
            if ready:
                url = ready["studioUrl"]
                if urlsplit(url).hostname not in LOOPBACK_HOSTS:
                    raise MontageError(f"Монтажный стол открылся не на 127.0.0.1 ({url}) — остановлен")
                record = {"pid": process.pid, "port": int(ready.get("port") or port), "url": url,
                          "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
                write_record(paths, record)
                return {"state": "open", **record}
            if process.poll() is not None:
                break
            self.sleep(0.2)
        tail = log.read_text(encoding="utf-8", errors="replace").strip()[-300:] if log.exists() else ""
        raise MontageError(f"Монтажный стол не запустился за {timeout} с: {tail}")

    def close(self, paths: MontagePaths) -> dict:
        record = read_record(paths)
        if record is not None and self.alive(record["pid"]):
            self.kill(record["pid"])
        forget_record(paths)
        return {"state": "closed"}
