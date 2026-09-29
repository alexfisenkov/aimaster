"""Монтажный стол: интерфейс Desk и реализация StudioDesk — HyperFrames Studio в
соседней вкладке. Один процесс `preview` на проект (замок montage/.desk.lock на
открытие и закрытие); pid, порт, адрес и время запуска процесса — в
montage/.desk.json. Останавливается только доказанно свой процесс
(`desk_identity`, свои Popen — `desk_children`); запуск процесса и ожидание
его строки готовности — `desk_launch`. Вариант 2 (свой стол внутри дашборда) —
другая реализация того же интерфейса. Страница-переходник, которая ставит
`TELEMETRY_STORAGE_KEY` на origin Studio до её первой загрузки, —
`desk_opener.py`; остановка по простою и при выходе сервера дашборда —
`studio/desk_keeper.py`."""

from __future__ import annotations

import time
from typing import Protocol
from urllib.parse import urlsplit

from . import MontageError, desk_children
from .desk_identity import FOREIGN, GONE, HUNG, OPEN, fetch_config, verdict
from .desk_launch import free_port, launch  # noqa: F401 — free_port: прежнее имя desk.*
from .desk_record import (FORGET_TEXT, FORGOTTEN, KEPT, KEPT_NOTE, PUBLIC_KEYS, REPLACED,  # noqa: F401
                          forget_record, public, read_record, record_text)
from .engine import Engine
from .locks import held_lock
from .paths import MontagePaths
from .proc import PidHandle, process_alive, process_started
from .proc_tree import kill_tree
from .replace_target import clear_link

TELEMETRY_STORAGE_KEY = "hyperframes-studio:telemetryDisabled"
DESK_LOCK_WAIT = 5.0
LOCK_NAME = ".desk.lock"
BUSY = "монтажный стол этого проекта сейчас открывают или закрывают — повторите через минуту"


class Desk(Protocol):
    def open(self, paths: MontagePaths) -> dict: ...

    def close(self, paths: MontagePaths) -> dict: ...

    def status(self, paths: MontagePaths) -> dict: ...


def studio_origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def stop_process(pid: int) -> None:
    """Стол вместе с детьми (Chrome превью, ffmpeg) — через proc_tree.kill_tree."""

    try:
        kill_tree(PidHandle(pid))
    except OSError as error:
        raise MontageError(f"не удалось остановить монтажный стол (процесс {pid})") from error


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
                 started=process_started, kill=stop_process, adopt=None):
        self.engine, self.popen, self.clock, self.sleep = engine, popen, clock, sleep
        self.alive, self.config, self.started, self.kill = alive, config, started, kill
        self.adopt = adopt  # стол дашборда — в его задание Windows (desk_job.py); CLI — None

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
        return held_lock(paths.root / LOCK_NAME, wait=wait, clock=self.clock, sleep=self.sleep,
                         busy=BUSY)

    def status(self, paths: MontagePaths) -> dict:
        text, record, seen = self._check(paths)
        if seen == OPEN:
            return {"state": "open", **public(record)}
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
        # Закрытие идёт мимо проверки ссылок (своё Studio остановить нужно
        # всегда): ссылка на месте замка — долой сама, по ней замок не открыть.
        try:
            clear_link(paths.root / LOCK_NAME)
        except OSError as error:
            raise MontageError(f"не удалось убрать ссылку на месте замка {LOCK_NAME} в папке "
                               "монтажа") from error
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
                return {"state": "open", **public(record)}
            if seen == HUNG:
                self._stop(paths, record["pid"])  # зависший свой стол — остановить, прежде чем поднимать новый
            outcome = forget_record(paths)
            if self.engine is None:
                raise MontageError("Монтажный движок не готов: монтажный стол не запустить")
            opened = self._launch(paths)  # не удалённую прежнюю запись заменила запись нового стола
            return {**opened, **_forgotten_note(record, seen, REPLACED if outcome == KEPT else outcome)}

    def _launch(self, paths: MontagePaths) -> dict:
        return launch(self, paths)
