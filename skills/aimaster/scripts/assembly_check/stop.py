"""Выход дашборда с открытым столом: остановить дашборд так, как его
останавливает агент, и проверить, что стол ушёл вместе с ним (порт стола
больше не принимает соединения) и что ни одного процесса прогона не осталось.

Стол — из записи `montage/.desk.json`: номер процесса, порт и время запуска;
в учёт он попадает, только если время запуска совпало с записью (иначе это
уже чужой процесс с тем же номером), вместе с потомками — пока он жив.

Windows: SIGTERM там — TerminateProcess, а Ctrl+Break (им смоук чистой
машины останавливает дашборд) завершает Python без его `finally`: дашборд не
успевает закрыть свой стол (так же и `test_montage_http` пропускает этот
случай на Windows). Там проверка «стол ушёл вместе с дашбордом» — к
сведению, а стол закрывает команда агента `montage close`; обязательно —
чтобы после неё порт стола был закрыт и процессов не осталось."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from smoke_kit import cli
from . import project
from .dashboard import STOP_CODES, port_refused
from .engine_copy import release

DESK_GONE_WAIT = 20.0


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
    windows = os.name == "nt"
    run.report.add("exit.desk_stopped_with_dashboard", gone,
                   f"порт стола {port} закрыт вместе с дашбордом" if gone else
                   f"порт стола {port} ещё принимает соединения через {DESK_GONE_WAIT:.0f} с",
                   required=not windows)
    if windows and not gone:
        closed = cli(run.env, "montage", "close", run.workspace, project.PROJECT)
        shut = port_refused(port, wait=DESK_GONE_WAIT)
        run.report.add("exit.desk_closed_by_agent", shut,
                       f"montage close: {closed.get('state')}; порт {port} {'закрыт' if shut else 'открыт'}")


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
    left = processes.left()
    report.add("exit.no_processes", not left, "процессов прогона не осталось" if not left
               else "остались: " + ", ".join(left))


def finish(run) -> None:
    """Конец прогона при любом исходе: дашборды, оставшиеся наши процессы
    (остались — провал), ссылка на общие пакеты движка — до удаления
    временной папки; при провале журналы — к снимкам (их выгружает CI)."""

    for board in run.dashboards:
        board.kill()
    left = run.processes.stop_left()
    run.report.add("processes.none_left", not left,
                   "процессов прогона не осталось" if not left else "пришлось остановить: " + ", ".join(left))
    release(run.root / "движок")
    if run.args.shots and not run.report.ok:
        try:
            shutil.copytree(run.work, run.shots / "журналы", dirs_exist_ok=True)
        except OSError as error:
            run.report.add("run.logs_copied", False, f"журналы не скопированы: {error}")
    if not run.args.keep:
        shutil.rmtree(run.root, ignore_errors=True)
