"""Столы, запущенные дашбордом, умирают вместе с ним — и на Windows.

На macOS и Linux дашборд, остановленный SIGTERM или Ctrl+C, сам закрывает
свои столы (`desk_keeper.py`). На Windows «остановить» — это чаще всего
TerminateProcess или Ctrl+Break: Python завершается без `finally`, и стол
(своя группа процессов, `proc_tree.group_kwargs`) пережил бы дашборд. Поэтому
дашборд держит одно задание Windows (Job Object) с KILL_ON_JOB_CLOSE и
включает в него процесс каждого стола сразу после запуска: дети стола (Chrome,
ffmpeg) наследуют задание, а когда процесс дашборда завершается как угодно,
ОС закрывает дескриптор задания и завершает весь стол. Дескриптор нарочно не
закрывается до выхода процесса: закрыть его — значит остановить столы.

Столы, открытые командой агента (`montage open`), в задание не входят: CLI
выходит, а стол остаётся до `montage close` (канон references/montage.md).
Задание создаётся при первом столе; не вышло (политика системы, старая
Windows) — стол всё равно открывается, просто без этой страховки. Между
запуском процесса и включением в задание — доли миллисекунды: Node к этому
времени ещё не успевает запустить своих детей."""

from __future__ import annotations

import threading
from functools import partial

from ..platform_compat import IS_WINDOWS
from .desk import StudioDesk


class DeskJob:
    def __init__(self, *, windows: bool = IS_WINDOWS, api=None):
        self.windows, self._api = windows, api
        self._job = None
        self._lock = threading.Lock()

    def _calls(self):
        if self._api is None:
            from . import win_processes  # только Windows
            self._api = win_processes
        return self._api

    def adopt(self, process) -> bool:
        """Включить процесс стола в задание дашборда; True — включён."""

        if not self.windows:
            return False
        try:
            api = self._calls()
            with self._lock:
                if self._job is None:
                    self._job = api.kill_on_close_job()
                api.assign(self._job, process.pid)
        except OSError:
            return False
        return True


def dashboard_desk_factory(job: DeskJob | None = None):
    """Фабрика столов для экрана «Сборка» дашборда (`MontageScreen`): тот же
    StudioDesk, но каждый запущенный им стол — в задании этого процесса."""

    return partial(StudioDesk, adopt=(job or DeskJob()).adopt)
