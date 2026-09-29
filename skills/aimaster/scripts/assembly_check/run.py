"""Прогон проверки экрана «Сборка»: временная папка, учёт процессов, дашборд
шага (останавливается в конце шага при любом исходе), браузерные фазы и
защита шага — сбой шага становится проверкой «<шаг>.crash», а следующие
независимые шаги всё равно идут. Сами шаги — stages.py; уборка в конце при
любом исходе — stop.finish: что не остановилось само, останавливается — и
это провал проверки."""

from __future__ import annotations

import subprocess
import tempfile
import time
import traceback
from contextlib import contextmanager
from pathlib import Path

from smoke_kit import SmokeError
from studio.montage import engine
from . import project
from .browser import run_phases
from .dashboard import STOP_CODES, Dashboard, DashboardError
from .engine_copy import fingerprint
from .processes import Processes
from .stages import main_flow
from .stop import finish

README = ("Временная папка проверки экрана «Сборка» (scripts/check_assembly_screen.py): "
          "рабочая папка, свой HOME, своя папка движка, журналы и снимки. Удаляется в конце, "
          "--keep оставляет.\n")
EXPECTED = (SmokeError, DashboardError, OSError, subprocess.SubprocessError)


class Run:
    def __init__(self, args, found: engine.Engine, report):
        self.args, self.found, self.report = args, found, report
        self.root = Path(tempfile.mkdtemp(prefix="aimaster-screencheck-"))
        (self.root / "README.txt").write_text(README, encoding="utf-8")
        self.work = self.root / "журналы"
        self.work.mkdir()
        self.shots = Path(args.shots).resolve() if args.shots else self.root / "снимки"
        self.shots.mkdir(parents=True, exist_ok=True)
        self.workspace = self.root / "Мои проекты ИИ" / "рабочая папка"
        self.processes = Processes()
        self.own = None
        self.env = None
        self.dashboards: list[Dashboard] = []

    def guard(self, name: str, step, *, timed: bool = False) -> bool:
        started = time.monotonic()
        try:
            step()
            return True
        except EXPECTED as error:
            self.report.add(f"{name}.crash", False, f"{type(error).__name__}: {error}")
        except Exception:  # noqa: BLE001 — ошибка самой проверки: отчёт всё равно нужен
            self.report.add(f"{name}.crash", False, traceback.format_exc()[-3000:])
        finally:
            if timed:
                self.report.seconds[name] = round(time.monotonic() - started, 1)
        return False

    @contextmanager
    def dashboard(self, name: str, engine_dir: Path):
        env = dict(self.env, AIMASTER_HYPERFRAMES_DIR=str(engine_dir))
        board = Dashboard(env, self.workspace, self.work, name)
        self.dashboards.append(board)
        board.start()
        self.processes.add(board.proc.pid, f"дашборд {name}")
        try:
            yield board
        finally:
            if board.running():
                self.stop(board)

    def stop(self, board: Dashboard) -> int:
        code = board.stop()
        self.report.add(f"dashboard.stop.{board.name}", code in STOP_CODES, f"дашборд остановлен, код {code}")
        return code

    def phases(self, board: Dashboard, *names: str) -> dict:
        settings = {
            "phases": list(names), "baseUrl": board.base_url, "projectId": project.PROJECT,
            "title": project.TITLE, "workspace": str(self.workspace),
            "indexPath": str(project.index_path(self.workspace)), "enginePrefix": str(self.own.prefix),
            "shots": str(self.shots), "profile": str(self.root / "профиль браузера"),
            "modules": str(self.own.modules), "browser": self.own.browser, "reveal": bool(self.args.reveal),
        }
        answer = run_phases(self.own.node, settings, self.work, self.processes, self.env)
        self.report.merge(answer)
        return answer.get("data") or {}


def run(args, report) -> None:
    found, reason = engine.locate()
    if found is None:
        report.engine_missing = reason
        return
    before = fingerprint(found)
    run_ = None
    try:
        run_ = Run(args, found, report)
        main_flow(run_)
    except Exception:  # noqa: BLE001 — Ctrl+C уходит дальше, но только после уборки
        report.add("run.crash", False, traceback.format_exc()[-3000:])
    finally:
        if run_ is not None:
            try:
                finish(run_)
            except Exception:  # noqa: BLE001 — уборка не должна съесть отчёт
                report.add("run.finish_crash", False, traceback.format_exc()[-3000:])
            if args.keep:
                report.kept = str(run_.root)
        report.add("engine.shared_untouched", fingerprint(found) == before,
                   "общая папка движка не менялась (пакеты, запись, браузер)")
