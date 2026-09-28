"""Экран «Сборка» со стороны сервера дашборда: ответы эндпоинтов
`/api/projects/<id>/montage…` (разбор путей и коды — `montage_routes.py`).

Всё идёт через `studio.montage.service_screen` и `service`: там проект
открывается заново и папка монтажа проверяется на ссылки. Действия со столом
проекта — по одному (`DeskKeeper.lock`). Опрос состояния стол не ждёт: занят
— «busy»; проверка самого стола (HTTP-запрос к Studio, не дольше 2 с) идёт
уже без замка проекта, чтобы открытие и закрытие её не ждали. Схема слоёв
одного проекта читается одним потоком за раз: движок после правки думает до
120 с, второй запрос ждёт и берёт кэш. «Показать в папке» — файл текущей
версии из state, никаких путей из запроса и никаких замков. Ответы — без
абсолютных путей и без команды установки движка."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from .desk_keeper import DeskKeeper
from .keyed_locks import KeyedLocks
from .montage import MontageError, service, service_screen
from .montage.desk import StudioDesk
from .montage.engine import locate as locate_engine
from .reveal import reveal_available, reveal_file

DESK_STATUS_WAIT = 0.2
LOOKUP_WAIT = 30.0  # дольше, чем `node --version` может думать (20 с)
NO_REVEAL = "на этом компьютере нечем открыть папку — путь к файлу есть на экране"


class EngineLookup:
    """`engine.locate()` не чаще раза в минуту, а пока движка нет — раз в
    15 с: он запускает `node --version`, а экран спрашивает состояние раз в
    5 с. Поставленный движок экран увидит не позже чем через 15 с.

    Ищет один поток и без замка: остальные тем временем берут прежний ответ,
    а если его ещё нет — ждут этот поиск, а не запускают свой."""

    def __init__(self, locate=None, *, clock=time.monotonic, fresh=60.0, missing=15.0):
        self._locate, self._clock = locate or locate_engine, clock
        self._fresh, self._missing = fresh, missing
        self._lock = threading.Lock()
        self._value: tuple | None = None
        self._until = float("-inf")
        self._looking: threading.Event | None = None

    def __call__(self):
        with self._lock:
            if self._value is not None and self._clock() < self._until:
                return self._value
            looking, last = self._looking, self._value
            if looking is None:
                self._looking = mine = threading.Event()
        if looking is not None:  # ищет другой поток
            if last is not None:
                return last
            looking.wait(LOOKUP_WAIT)
            with self._lock:
                found = self._value
            return found if found is not None else self._locate()
        try:
            value = self._locate()
        except BaseException:
            with self._lock:
                self._looking = None
            mine.set()
            raise
        with self._lock:
            self._value, self._looking = value, None
            self._until = self._clock() + (self._fresh if value[0] is not None else self._missing)
        mine.set()
        return value


class MontageScreen:
    def __init__(self, workspace, *, keeper: DeskKeeper, engines, desk_factory=StudioDesk,
                 reveal=reveal_file, reveal_ready: bool | None = None, runner=None):
        self.workspace = Path(workspace)
        self.keeper, self.engines, self.desk_factory = keeper, engines, desk_factory
        self.reveal_file, self.runner = reveal, runner
        self.reveal_ready = reveal_available() if reveal_ready is None else reveal_ready
        self._model_reads = KeyedLocks()

    def status(self, project_id: str) -> dict:
        self.keeper.touch(project_id)
        result = service_screen.screen_status(
            self.workspace, project_id, locate=self.engines,
            desk_state=lambda paths: self._desk_state(project_id, paths))
        if result.get("applicable"):
            result["reveal"] = self.reveal_ready
        return result

    def _desk_state(self, project_id: str, paths) -> dict:
        lock = self.keeper.lock(project_id)
        if not lock.acquire(timeout=DESK_STATUS_WAIT):
            return {"state": "busy"}  # стол открывают или закрывают
        lock.release()
        return self.desk_factory(None).status(paths)

    def model(self, project_id: str) -> dict:
        with self._model_reads.hold(project_id):
            return service_screen.screen_model(self.workspace, project_id, locate=self.engines,
                                               runner=self.runner)

    def open_desk(self, project_id: str) -> dict:
        with self.keeper.lock(project_id):
            engine, reason = self.engines()
            if engine is None:
                raise MontageError(f"монтажный стол не установлен: {reason}")
            view, paths = service_screen.open_desk_for_screen(
                self.workspace, project_id, desk=self.desk_factory(engine))
            self.keeper.opened(project_id, paths)
            return view

    def close_desk(self, project_id: str) -> dict:
        with self.keeper.lock(project_id):
            closed = service.close_desk(self.workspace, project_id, desk=self.desk_factory(None))
            self.keeper.closed(project_id)
            return closed

    def restore(self, project_id: str, version_id: str, expected_revision: int) -> dict:
        return service_screen.restore_as_owner(self.workspace, project_id, expected_revision,
                                               version_id)

    def reveal(self, project_id: str) -> dict:
        if not self.reveal_ready:
            raise MontageError(NO_REVEAL)
        target, shown = service_screen.current_output(self.workspace, project_id)
        self.reveal_file(target)
        return {"project_id": project_id, "shown": shown}
