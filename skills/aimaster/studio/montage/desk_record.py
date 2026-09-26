"""Запись монтажного стола montage/.desk.json и разбор ответа `preview --json`."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import urlsplit

from . import MontageError
from .index_io import write_text_atomic
from .paths import MontagePaths

LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


def read_record(paths: MontagePaths) -> dict | None:
    try:
        record = json.loads(paths.desk_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    valid = (isinstance(record, dict) and isinstance(record.get("pid"), int)
             and isinstance(record.get("port"), int) and isinstance(record.get("url"), str))
    return record if valid else None


def forget_record(paths: MontagePaths) -> None:
    try:
        paths.desk_file.unlink(missing_ok=True)
    except OSError:
        pass  # запись без процесса безвредна: status её снова проверит


def ready_line(log_path) -> dict | None:
    """Первая строка `preview --json`: {"ok": true, "result": {"studioUrl", "ready": true, …}}."""

    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        if not line.strip().startswith("{"):
            continue  # журнал Studio и браузера вперемешку с JSON
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        result = payload.get("result") if isinstance(payload, dict) and payload.get("ok") else None
        if isinstance(result, dict) and result.get("ready") and isinstance(result.get("studioUrl"), str):
            return result
    return None


def write_record(paths: MontagePaths, record: dict) -> None:
    write_text_atomic(paths.desk_file, json.dumps(record, ensure_ascii=False))


def record_from_ready(ready: dict, *, pid: int, port: int, process_started: str | None) -> dict:
    """Запись стола из строки готовности. Studio слушает только 127.0.0.1
    (engine_env ставит HYPERFRAMES_PREVIEW_HOST); иной адрес — отказ."""

    url = ready["studioUrl"]
    if not {urlsplit(url).hostname, ready.get("host") or "127.0.0.1"} <= set(LOOPBACK_HOSTS):
        raise MontageError(f"Монтажный стол открылся не на 127.0.0.1 ({url}) — остановлен")
    return {"pid": pid, "port": int(ready.get("port") or port), "url": url,
            "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "process_started": process_started}
