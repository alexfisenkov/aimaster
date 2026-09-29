"""Учёт процессов прогона: дашборд, монтажный стол и его потомки, браузер
браузерных фаз. Каждый процесс записан вместе с отпечатком времени запуска
(`proc.process_started`): номер процесса ОС выдаёт заново, и «наш» — только
тот же номер с тем же временем запуска. Останавливается только наш —
`proc_tree.kill_tree` (узел целиком: Chrome, которого puppeteer запускает
своей сессией, группой не достаётся); чужие процессы не трогаются никогда."""

from __future__ import annotations

from dataclasses import dataclass, field

from studio.montage.proc import PidHandle, process_alive, process_started
from studio.montage.proc_tree import _descendants, kill_tree
from studio.platform_compat import IS_WINDOWS


@dataclass
class Processes:
    started: object = process_started
    alive: object = process_alive
    kill: object = kill_tree
    children: object = _descendants
    known: dict = field(default_factory=dict)  # pid → (подпись, время запуска)

    def add(self, pid, label: str, *, with_children: bool = False, expected: str | None = None) -> None:
        """Записать процесс (и, по желанию, его потомков — пока он жив:
        после остановки дерево уже не прочитать). Время запуска не
        прочиталось — процесса уже нет, записывать нечего; `expected` —
        время запуска из записи стола: не совпало — процесс не тот."""

        stamp = self.started(pid)
        if stamp is None or (expected is not None and stamp != expected):
            return
        if pid not in self.known:
            self.known[pid] = (label, stamp)
        if with_children and not IS_WINDOWS:
            for child in self.children(pid):
                self.add(child, f"{label} → потомок")

    def ours(self, pid) -> bool:
        entry = self.known.get(pid)
        return entry is not None and self.alive(pid) and self.started(pid) == entry[1]

    def left(self) -> list[str]:
        """Наши процессы, которые всё ещё работают: «подпись (pid N)»."""

        return [f"{label} (pid {pid})" for pid, (label, _stamp) in sorted(self.known.items())
                if self.ours(pid)]

    def stop_left(self) -> list[str]:
        """Остановить оставшиеся наши процессы; вернуть, кого пришлось останавливать."""

        stopped = self.left()
        for pid in list(self.known):
            if self.ours(pid):
                self.kill(PidHandle(pid))
        return stopped
