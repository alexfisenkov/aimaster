"""Тот ли это монтажный стол, что записан в montage/.desk.json.

Номер процесса ОС выдаёт заново: после смерти стола тот же pid может достаться
чужому процессу (на Windows — хоть Проводнику), а тот же порт — чужому серверу.
Останавливать можно только доказанно свой процесс:

- отвечает — Studio HyperFrames 0.8.75 на `GET /__hyperframes_config` называет
  свой pid и папку проекта: наш, только если pid из записи и папка — current/;
- молчит — наш, только если это Popen этого же процесса или время запуска
  процесса совпало с записанным при открытии (`proc.process_started`).

Любое несовпадение или непроверяемость — запись забывается, никто не
останавливается («foreign»).
"""

from __future__ import annotations

import http.client
import json
import os

OPEN, HUNG, GONE, FOREIGN = "open", "hung", "gone", "foreign"
CONFIG_PATH = "/__hyperframes_config"


def fetch_config(port, timeout: float = 1.0) -> dict | None:
    """Ответ Studio о себе; None — не ответила. Прямо на 127.0.0.1 через
    http.client: urllib подхватил бы прокси из окружения."""

    connection = http.client.HTTPConnection("127.0.0.1", int(port), timeout=timeout)
    try:
        connection.request("GET", CONFIG_PATH)
        response = connection.getresponse()
        if response.status != 200:
            return None
        data = json.loads(response.read(65536).decode("utf-8"))
    except (OSError, ValueError, http.client.HTTPException):
        return None
    finally:
        connection.close()
    return data if isinstance(data, dict) else None


def _same_dir(left, right) -> bool:
    def norm(path):
        return os.path.normcase(os.path.realpath(str(path)))
    return norm(left) == norm(right)


def serves_this_desk(config: dict, record: dict, paths) -> bool:
    return (config.get("isHyperframes") is True and config.get("pid") == record["pid"]
            and isinstance(config.get("projectDir"), str)
            and _same_dir(config["projectDir"], paths.current))


def verdict(record: dict, paths, *, config, alive, started, child) -> str:
    """OPEN — отвечает и назвался этим столом; HUNG — молчит (или назвался
    не так), но процесс доказанно наш; GONE — процесса нет; FOREIGN — номер
    занят чужим процессом или доказать, что он наш, нечем."""

    if child is not None and child.poll() is not None:
        return GONE  # наш Popen завершился — номер мог уже достаться чужому
    answer = config(record["port"])
    if answer is not None and serves_this_desk(answer, record, paths):
        return OPEN
    if child is not None:
        return HUNG
    if answer is not None:
        return FOREIGN  # на порту отвечает другой сервер или другой проект
    if not alive(record["pid"]):
        return GONE
    token = record.get("process_started")
    return HUNG if token and started(record["pid"]) == token else FOREIGN
