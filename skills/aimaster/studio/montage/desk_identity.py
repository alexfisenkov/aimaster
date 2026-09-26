"""Тот ли это монтажный стол, что записан в montage/.desk.json.

Номер процесса ОС выдаёт заново: после смерти стола тот же pid может достаться
чужому процессу (на Windows — хоть Проводнику), а тот же порт — чужому серверу;
папку проекта могут скопировать вместе с записью. Останавливать можно только
доказанно свой процесс:

- запись сделана для этой папки: realpath папки montage в записи совпадает с
  текущей (копия проекта со старой записью — не её стол);
- отвечает — Studio HyperFrames 0.8.75 на `GET /__hyperframes_config` называет
  свой pid и папку проекта: наш, только если pid из записи и папка — current/;
- молчит — наш, только если это Popen этого же процесса для этого же проекта
  с тем же временем запуска (`desk_children`) или время запуска процесса
  совпало с записанным при открытии (`proc.process_started`).

Любое несовпадение или непроверяемость — запись забывается, никто не
останавливается («foreign»).
"""

from __future__ import annotations

import json
import os
import socket
import time

from .desk_children import EXITED, RUNNING, root_key

OPEN, HUNG, GONE, FOREIGN = "open", "hung", "gone", "foreign"
CONFIG_PATH = "/__hyperframes_config"
CONFIG_DEADLINE = 2.0
_REQUEST = (f"GET {CONFIG_PATH} HTTP/1.0\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n").encode()
_LIMIT = 65536


def _receive(port, deadline: float, clock) -> bytes | None:
    """Ответ целиком за общий срок: и подключение, и каждое чтение урезаются до
    остатка — сервер, отдающий по байту, не растянет проверку."""

    with socket.create_connection(("127.0.0.1", int(port)), timeout=max(deadline - clock(), 0.01)) as sock:
        sock.sendall(_REQUEST)
        data = b""
        while len(data) <= _LIMIT:
            remaining = deadline - clock()
            if remaining <= 0:
                return None
            sock.settimeout(remaining)
            chunk = sock.recv(_LIMIT)
            if not chunk:
                return data
            data += chunk
    return None  # больше, чем бывает у этого ответа


def fetch_config(port, timeout: float = CONFIG_DEADLINE, clock=time.monotonic) -> dict | None:
    """Ответ Studio о себе; None — не ответила вовремя, ответила не 200, не
    JSON-объектом или нарочно кривым JSON. Прямо на 127.0.0.1 сокетом: urllib
    подхватил бы прокси из окружения, http.client не держит общий срок."""

    try:
        data = _receive(port, clock() + timeout, clock)
    except (OSError, ValueError, TypeError, OverflowError):
        return None
    head, _, body = (data or b"").partition(b"\r\n\r\n")
    status = head.split(b"\r\n", 1)[0].split()
    if len(status) < 2 or status[1] != b"200":
        return None
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (ValueError, RecursionError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _same_dir(left, right) -> bool:
    def norm(path):
        return os.path.normcase(os.path.realpath(str(path)))
    try:
        return norm(left) == norm(right)
    except (OSError, ValueError):  # NUL в пути, слишком длинный путь — не наш
        return False


def serves_this_desk(config: dict, record: dict, paths) -> bool:
    return (config.get("isHyperframes") is True and config.get("pid") == record["pid"]
            and isinstance(config.get("projectDir"), str)
            and _same_dir(config["projectDir"], paths.current))


def verdict(record: dict, paths, *, config, alive, started, own) -> str:
    """OPEN — отвечает и назвался этим столом; HUNG — молчит (или назвался
    не так), но процесс доказанно наш; GONE — процесса нет; FOREIGN — номер
    занят чужим процессом или доказать, что он наш, нечем (Windows: нет
    доступа к процессу). `own` — `desk_children.own`: RUNNING, EXITED или None."""

    if record.get("montage_root") != root_key(paths):
        return FOREIGN  # запись из другой папки (проект скопировали вместе с ней)
    if own == EXITED:
        return GONE  # наш Popen завершился — номер мог уже достаться чужому
    answer = config(record["port"])
    if answer is not None and serves_this_desk(answer, record, paths):
        return OPEN
    if own == RUNNING:
        return HUNG
    if answer is not None:
        return FOREIGN  # на порту отвечает другой сервер или другой проект
    if not alive(record["pid"]):
        return GONE
    token = record.get("process_started")
    return HUNG if token and started(record["pid"]) == token else FOREIGN
