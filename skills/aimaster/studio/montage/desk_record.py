"""Запись монтажного стола montage/.desk.json и разбор ответа `preview --json`."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from urllib.parse import urlsplit

from . import MontageError
from .index_io import write_text_atomic
from .paths import MontagePaths

LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


MAX_PID = 2 ** 31 - 1


def _number(value, low: int, high: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def record_text(paths: MontagePaths) -> str | None:
    try:
        return paths.desk_file.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None


def read_record(paths: MontagePaths, text: str | None = None) -> dict | None:
    """Запись стола или None — нет, битая или с номерами вне допустимого
    (pid и порт из файла потом уходят в ОС и в сокет)."""

    text = record_text(paths) if text is None else text
    try:
        record = json.loads(text) if text is not None else None
    except (ValueError, RecursionError):
        return None
    valid = (isinstance(record, dict) and _number(record.get("pid"), 1, MAX_PID)
             and _number(record.get("port"), 1, 65535) and isinstance(record.get("url"), str))
    return record if valid else None


FORGOTTEN, REPLACED, KEPT = "forgotten", "replaced", "kept"
FORGET_TEXT = {FORGOTTEN: "запись забыта", REPLACED: "запись уже заменена новой",
               KEPT: "запись забыть не удалось (montage/.desk.json не удаляется)",
               None: "запись будет забыта при следующей проверке"}  # None: open/close держат замок
KEPT_NOTE = "запись montage/.desk.json удалить не удалось — montage status проверит её снова"


def forget_record(paths: MontagePaths, *, if_text: str | None = None) -> str:
    """Удалить запись. FORGOTTEN — записи больше нет; REPLACED — с `if_text`:
    файл уже не этот текст, его переписал параллельный open (новая запись не
    наша, не трогаем); KEPT — удалить не вышло (нет прав, файл занят) — запись
    без процесса безвредна, status её снова проверит."""

    try:
        now = record_text(paths) if if_text is not None else None
        if if_text is not None and now != if_text:
            if now is None:  # убрал параллельный close — или файл не читается
                return KEPT if os.path.lexists(paths.desk_file) else FORGOTTEN
            return REPLACED
        paths.desk_file.unlink(missing_ok=True)
    except OSError:
        return KEPT
    return FORGOTTEN


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


def record_from_ready(ready: dict, *, pid: int, port: int, process_started: str | None,
                      montage_root: str) -> dict:
    """Запись стола из строки готовности. Studio слушает только 127.0.0.1
    (engine_env ставит HYPERFRAMES_PREVIEW_HOST); иной адрес — отказ."""

    url = ready["studioUrl"]
    if not {urlsplit(url).hostname, ready.get("host") or "127.0.0.1"} <= set(LOOPBACK_HOSTS):
        raise MontageError(f"Монтажный стол открылся не на 127.0.0.1 ({url}) — остановлен")
    return {"pid": pid, "port": int(ready.get("port") or port), "url": url,
            "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "process_started": process_started, "montage_root": montage_root}
