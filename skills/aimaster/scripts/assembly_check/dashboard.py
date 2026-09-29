"""Дашборд прогона: `creator_studio.py serve <рабочая папка> --port 0`,
адрес — из первой строки `{"base_url": …}`; остановка — так же, как его
останавливает агент: SIGTERM на macOS и Linux (дашборд закрывается как по
Ctrl+C и закрывает свои столы), на Windows — Ctrl+Break своей группе
процессов (как смоук чистой машины: SIGTERM там — TerminateProcess).
Вывод дашборда — в файлы журнала, не в трубу: труба без читателя
переполнилась бы и остановила сервер."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import time
from pathlib import Path

from smoke_kit import CLI, SKILL, decode, python_argv

START_TIMEOUT = 60.0
STOP_TIMEOUT = 30.0
# Windows: Ctrl+Break завершает процесс кодом STATUS_CONTROL_C_EXIT, если он
# не вышел сам раньше; любой другой код — падение.
STOP_CODES = (0, 0xC000013A) if os.name == "nt" else (0,)


class DashboardError(Exception):
    pass


def port_refused(port: int, *, wait: float = 0.0, host: str = "127.0.0.1") -> bool:
    """Порт не принимает соединения (сразу или в пределах `wait` секунд)."""

    deadline = time.monotonic() + wait
    while True:
        try:
            with socket.create_connection((host, port), timeout=2):
                pass
        except OSError:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.25)


class Dashboard:
    def __init__(self, env: dict, workspace: Path, logs: Path, name: str):
        self.env, self.workspace, self.logs, self.name = env, workspace, logs, name
        self.proc: subprocess.Popen | None = None
        self.base_url = ""

    def start(self) -> str:
        self.logs.mkdir(parents=True, exist_ok=True)
        out, err = self.logs / f"{self.name}.out", self.logs / f"{self.name}.err"
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        with open(out, "wb") as stdout, open(err, "wb") as stderr:
            self.proc = subprocess.Popen(python_argv() + [str(CLI), "serve", str(self.workspace), "--port", "0"],
                                         env=self.env, cwd=str(SKILL), stdout=stdout, stderr=stderr,
                                         stdin=subprocess.DEVNULL, creationflags=flags)
        deadline = time.monotonic() + START_TIMEOUT
        while time.monotonic() < deadline:
            line = decode(out.read_bytes()).split("\n", 1)
            if len(line) == 2:
                self.base_url = json.loads(line[0])["base_url"].rstrip("/")
                return self.base_url
            if self.proc.poll() is not None:
                break
            time.sleep(0.1)
        tail = decode(err.read_bytes())[-1500:]
        self.kill()
        raise DashboardError(f"дашборд не напечатал адрес за {START_TIMEOUT:.0f} с; stderr: {tail}")

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    @property
    def port(self) -> int:
        return int(self.base_url.rsplit(":", 1)[1])

    def stop(self) -> int:
        """Остановить, как агент; код выхода. Не остановился сам — убит и ошибка."""

        proc = self.proc
        if proc is None or proc.poll() is not None:
            return proc.returncode if proc else 0
        try:
            proc.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM)
        except OSError:
            proc.terminate()
        try:
            return proc.wait(timeout=STOP_TIMEOUT)
        except subprocess.TimeoutExpired:
            self.kill()
            raise DashboardError(f"дашборд не остановился за {STOP_TIMEOUT:.0f} с — пришлось убить")

    def kill(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(timeout=STOP_TIMEOUT)
