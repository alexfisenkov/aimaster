"""Монтажные столы, открытые дашбордом: одно действие со столом проекта за
раз, остановка по простою и при выходе сервера, уборка реестра своих
процессов (`desk_children.sweep`).

Простой — 60 минут без обоих признаков жизни: экран «Сборка» этого проекта не
спрашивал состояние монтажа (спрашивает раз в 5 с, пока вкладка видна —
`touch`) и current/index.html не менялся (Studio пишет правку мыши на диск за
секунду). Короче нельзя: человек работает во вкладке Studio, вкладка
дашборда при этом скрыта и молчит, а правок может не быть, пока он смотрит и
слушает. Дольше незачем: Studio с браузером превью занимает сотни мегабайт,
а поднять стол снова — секунда-другая, правки уже на диске.

Стол, который открыл агент (`montage open`) и дашборд ни разу не трогал,
здесь не учитывается — его останавливает `montage close`. Но стоит дашборду
открыть `…/montage/desk` для того же проекта — стол уже работает, новый
процесс не поднимается (`StudioDesk.open` вернёт тот же `state: "open"`), —
и с этого момента запись в `_watched` есть: тот же час простоя остановит его
точно так же, как свой. При выходе сервера останавливаются все столы,
запущенные этим процессом: сперва дожидаемся действий, которые идут прямо
сейчас (стол могут как раз открывать), а стол, открытый уже после выхода,
закрывается сразу. Замок `_guard` — только над словарями; остановка стола
и `os.stat` идут вне его."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass

from .montage import desk_children
from .montage.paths import MontagePaths
from .montage.proc_tree import kill_tree

IDLE_SECONDS = 60 * 60
SWEEP_SECONDS = 60.0
STOP_WAIT = 10.0


def index_stamp(paths: MontagePaths) -> tuple[int, int] | None:
    try:
        info = os.stat(paths.index)
    except OSError:
        return None
    return info.st_mtime_ns, info.st_size


@dataclass
class _Watched:
    paths: MontagePaths
    seen_at: float
    stamp: tuple | None


def _take(lock: threading.Lock, wait: float) -> bool:
    return lock.acquire(timeout=wait) if wait > 0 else lock.acquire(blocking=False)


class DeskKeeper:
    def __init__(self, *, close_desk, kill=kill_tree, clock=time.monotonic, idle=IDLE_SECONDS,
                 sweep_every=SWEEP_SECONDS, stamp=index_stamp):
        self._close_desk, self._kill, self._clock = close_desk, kill, clock
        self._idle, self._sweep_every, self._stamp = idle, sweep_every, stamp
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}
        self._watched: dict[str, _Watched] = {}
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None

    def lock(self, project_id: str) -> threading.Lock:
        """Одно действие со столом проекта за раз: открыть, закрыть, остановить."""

        with self._guard:
            return self._locks.setdefault(project_id, threading.Lock())

    def opened(self, project_id: str, paths: MontagePaths) -> None:
        stamp = self._stamp(paths)
        with self._guard:
            if not self._stopping.is_set():
                self._watched[project_id] = _Watched(paths, self._clock(), stamp)
                return
        self._close_quietly(paths)  # дашборд уже выходит — стол не должен его пережить

    def closed(self, project_id: str) -> None:
        with self._guard:
            self._watched.pop(project_id, None)

    def touch(self, project_id: str) -> None:
        with self._guard:
            watched = self._watched.get(project_id)
            if watched is not None:
                watched.seen_at = self._clock()

    def watched(self) -> list[str]:
        with self._guard:
            return sorted(self._watched)

    def sweep(self) -> list[str]:
        """Уборка реестра и остановка простаивающих столов; ответ — чьи остановлены.

        Простой судится здесь, а закрывается в `_stop_desk` — между этими
        двумя моментами `self._guard` не удержать (замок стола ждут, стол
        останавливают без него). За это время запись могли тронуть: опрос
        экрана (`touch`) или переоткрытие стола после закрытия. Поэтому
        каждому кандидату несём не только id, а и `seen_at`, по которому его
        судили, — `_stop_desk` сверяет его под замком заново и, если запись
        уже не та, уборку этого стола пропускает до следующего захода."""

        desk_children.sweep(kill=self._kill)
        now, idle = self._clock(), []
        with self._guard:
            items = list(self._watched.items())
        for project_id, watched in items:
            stamp = self._stamp(watched.paths)
            with self._guard:
                if stamp != watched.stamp:
                    watched.stamp, watched.seen_at = stamp, now
                    continue
                expired, judged_seen_at = now - watched.seen_at >= self._idle, watched.seen_at
            if expired:
                idle.append((project_id, judged_seen_at))
        return [project_id for project_id, judged_seen_at in idle
                if self._stop_desk(project_id, wait=0, judged_seen_at=judged_seen_at)]

    def _stop_desk(self, project_id: str, *, wait: float, judged_seen_at: float | None = None) -> bool:
        """Останавливает стол, но только если это ровно та запись, что признали
        простаивающей: `judged_seen_at` — её `seen_at` на момент решения
        (`None` у `stop()` — при выходе сервера закрываем любую текущую
        запись, свежесть уже не важна)."""

        lock = self.lock(project_id)
        if not _take(lock, wait):
            return False  # стол сейчас открывают или закрывают — до следующей уборки
        try:
            with self._guard:
                current = self._watched.get(project_id)
                if current is None or (judged_seen_at is not None and current.seen_at != judged_seen_at):
                    return False  # запись сменилась (тронули или переоткрыли) — не наша уборка
                self._watched.pop(project_id, None)
            self._close_quietly(current.paths)
            return True
        finally:
            lock.release()

    def _close_quietly(self, paths: MontagePaths) -> None:
        try:
            self._close_desk(paths)
        except Exception:  # noqa: BLE001 — не остановился по-хорошему: выход сервера добьёт свой процесс
            pass

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="aimaster-desk-keeper", daemon=True)
        self._thread.start()

    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self) -> None:
        while not self._stopping.wait(self._sweep_every):
            try:
                self.sweep()
            except Exception:  # noqa: BLE001 — уборка не должна уронить сервер
                pass

    def stop(self) -> None:
        """Выход сервера: остановить уборку, дождаться идущих действий, закрыть
        свои столы, добить свои процессы."""

        self._stopping.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        with self._guard:
            projects = sorted(set(self._locks) | set(self._watched))
        for project_id in projects:
            self._stop_desk(project_id, wait=STOP_WAIT)
        desk_children.sweep(kill=self._kill, all_live=True)
