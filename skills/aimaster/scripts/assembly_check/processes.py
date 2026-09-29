"""Учёт процессов прогона: дашборды, монтажный стол и его потомки, узел
браузерных фаз и всё, что он запустил. Каждый процесс записан вместе с
отпечатком времени запуска (`proc.process_started`): номер процесса ОС
выдаёт заново, и «наш» — только тот же номер с тем же временем запуска.
Номер, уже записанный за другим временем запуска, — чужой процесс: ни он,
ни его дети в учёт не попадают. Потомки (`proc_tree.descendants`, на любой
ОС) читаются, только пока записанный родитель — тот же самый процесс.

Останавливается только наш: `proc_tree.kill_tree` (узел целиком), а на
macOS и Linux ещё и прямой сигнал тому, кто не ведёт свою группу
(`kill_tree` достаёт такого только как потомка живого родителя) — SIGTERM,
пауза, SIGKILL тому же процессу. Чужие процессы не трогаются никогда."""

from __future__ import annotations

import os
import signal
import time
from dataclasses import dataclass, field

from studio.montage.proc import PidHandle, process_alive, process_started
from studio.montage.proc_tree import descendants, kill_tree
from studio.platform_compat import IS_WINDOWS

GRACE = 3.0


@dataclass
class Processes:
    started: object = process_started
    alive: object = process_alive
    kill: object = kill_tree
    children: object = descendants
    send: object = os.kill  # прямой сигнал (только macOS и Linux)
    windows: bool = IS_WINDOWS
    sleep: object = time.sleep
    known: dict = field(default_factory=dict)  # pid → (подпись, время запуска)

    def add(self, pid, label: str, *, with_children: bool = False, expected: str | None = None) -> None:
        """Записать процесс и, по желанию, его потомков. Время запуска не
        прочиталось — процесса уже нет; `expected` (время из записи стола) не
        совпало или номер записан за другим временем — процесс не тот."""

        stamp = self.started(pid)
        if stamp is None or (expected is not None and stamp != expected):
            return
        entry = self.known.setdefault(pid, (label, stamp))
        if entry[1] != stamp:
            return
        if with_children:
            for child in self.children(pid):
                self.add(child, f"{label} → потомок")

    def ours(self, pid) -> bool:
        entry = self.known.get(pid)
        return entry is not None and self.alive(pid) and self.started(pid) == entry[1]

    def left(self) -> list[str]:
        """Наши процессы, которые всё ещё работают: «подпись (pid N)»."""

        return [f"{label} (pid {pid})" for pid, (label, _stamp) in sorted(self.known.items())
                if self.ours(pid)]

    def wait_gone(self, timeout: float) -> list[str]:
        """Дать уходящим процессам (дети, зомби) до `timeout` секунд; кто остался."""

        left = self.left()
        for _ in range(int(timeout / 0.2)):
            if not left:
                break
            self.sleep(0.2)
            left = self.left()
        return left

    def _signal(self, pid, sig) -> None:
        try:
            self.send(pid, sig)
        except OSError:
            pass  # уже ушёл

    def stop_left(self) -> tuple[list[str], list[str]]:
        """Остановить оставшиеся наши процессы: (кого останавливали, кто не остановился)."""

        stopping = self.left()
        for pid in list(self.known):
            if self.ours(pid):
                self.kill(PidHandle(pid))
        if not self.windows:
            rest = [pid for pid in self.known if self.ours(pid)]
            for pid in rest:
                self._signal(pid, signal.SIGTERM)
            self.wait_gone(GRACE)
            for pid in rest:
                if self.ours(pid):  # тот же процесс, не новый с его номером
                    self._signal(pid, getattr(signal, "SIGKILL", signal.SIGTERM))
        return stopping, self.wait_gone(GRACE)
