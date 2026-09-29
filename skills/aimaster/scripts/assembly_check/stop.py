"""Выход дашборда с открытым столом и уборка в конце прогона.

`stop_and_verify`: остановить дашборд так, как его останавливает агент
(SIGTERM; на Windows — Ctrl+Break своей группе), и проверить, что стол ушёл
вместе с ним — порт стола больше не принимает соединения — и что ни одного
процесса прогона не осталось. На всех системах это обязательно: на macOS и
Linux стол закрывает сам дашборд (`desk_keeper`), на Windows — ОС, закрывая
задание дашборда (`studio/montage/desk_job.py`). Не ушёл — стол закрывает
команда агента `montage close`, чтобы не оставить процессов, а проверка
остаётся проваленной.

Стол — из записи `montage/.desk.json`: номер процесса, порт и время запуска;
в учёт он попадает, только если время запуска совпало с записью (иначе это
уже чужой процесс с тем же номером), вместе с потомками — пока он жив.

`finish` — при любом исходе: сперва стол из записи — в учёт (сбой посреди
шага мог оставить его открытым), потом дашборды — штатно, потом то, что не
ушло само, — останавливается, и это провал; ссылка на общие пакеты движка
снимается до удаления временной папки; не удалилась — тоже провал."""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

from smoke_kit import cli
from . import project
from .dashboard import STOP_CODES, DashboardError, port_refused
from .engine_copy import release

DESK_GONE_WAIT = 20.0
GONE_WAIT = 10.0


def read_desk(workspace: Path) -> dict | None:
    try:
        record = json.loads(project.desk_file(workspace).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) and isinstance(record.get("pid"), int) else None


def register_desk(processes, desk: dict | None) -> None:
    if desk:
        processes.add(desk["pid"], "монтажный стол", with_children=True, expected=desk.get("process_started"))


def desk_gone(run, port: int) -> None:
    gone = port_refused(port, wait=DESK_GONE_WAIT)
    run.report.add("exit.desk_stopped_with_dashboard", gone, f"порт стола {port} закрыт вместе с дашбордом"
                   if gone else f"порт стола {port} ещё принимает соединения через {DESK_GONE_WAIT:.0f} с")
    if not gone:  # уборка за провалом: стол — командой агента, как человек из чата
        closed = cli(run.env, "montage", "close", run.workspace, project.PROJECT)
        shut = port_refused(port, wait=DESK_GONE_WAIT)
        run.report.add("exit.desk_closed_by_agent", shut, required=False,
                       detail=f"montage close: {closed.get('state')}; порт {port} {'закрыт' if shut else 'открыт'}")


def stop_and_verify(run, board) -> None:
    report, processes = run.report, run.processes
    desk = read_desk(run.workspace)
    register_desk(processes, desk)
    report.add("exit.desk_record", bool(desk) and desk["pid"] in processes.known,
               f"стол открыт дашбордом: pid {desk['pid']}, порт {desk['port']}" if desk else "записи стола нет")
    code = board.stop()
    report.add("exit.dashboard_stopped", code in STOP_CODES, f"дашборд остановлен, код {code:#x}"
               if code and code > 255 else f"дашборд остановлен, код {code}")
    if desk:
        desk_gone(run, desk["port"])
    left = processes.wait_gone(GONE_WAIT)
    report.add("exit.no_processes", not left, "процессов прогона не осталось" if not left
               else f"через {GONE_WAIT:.0f} с остались: " + ", ".join(left))


def remove_tree(root: Path, *, tries: int = 5, sleep=time.sleep) -> bool:
    """Удалить временную папку; Windows может держать файл секунду-другую."""

    for attempt in range(tries):
        shutil.rmtree(root, ignore_errors=True)
        if not os.path.lexists(root):
            return True
        if attempt + 1 < tries:
            sleep(1.0)
    return False


def finish(run) -> None:
    register_desk(run.processes, read_desk(run.workspace))
    for board in run.dashboards:
        if board.running():
            try:
                board.stop()
            except DashboardError:
                pass  # не остановился штатно — stop() уже убил его
    left = run.processes.wait_gone(GONE_WAIT)
    stopped, still = run.processes.stop_left() if left else ([], [])
    run.report.add("processes.none_left", not left, "процессов прогона не осталось" if not left else
                   "пришлось остановить: " + ", ".join(stopped)
                   + (f"; не остановились: {', '.join(still)}" if still else ""))
    release(run.root / "движок")
    if run.args.shots and not run.report.ok:  # CI выгружает папку снимков — с журналами
        try:
            shutil.copytree(run.work, run.shots / "журналы", dirs_exist_ok=True)
        except OSError as error:
            run.report.add("run.logs_copied", False, f"журналы не скопированы: {error}", required=False)
    if not run.args.keep:
        removed = remove_tree(run.root)
        run.report.add("run.temp_removed", removed, "временная папка удалена" if removed
                       else f"временная папка не удалилась: {run.root}")
