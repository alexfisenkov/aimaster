"""Проверка экрана «Сборка» по шагам — то, что контролёр прошёл руками.

1. Своя папка движка, свой HOME, синтетический проект → v001 командами агента.
2. Дашборд с движком: фазы desktop и desk (стол, правка мышью в Studio).
3. Агент: montage diff, ревизия из status, montage render --by owner → v002.
4. Фаза after («текущая v2», «Сделать текущей», «Закрыть стол»); порт стола закрыт.
5. Дашборд без движка: фаза noengine.
6. Дашборд с движком: фазы phone и exit; остановка дашборда (stop.py).
Все процессы прогона — в учёте (`Processes`); что не остановилось само,
останавливается в конце — и это провал проверки."""

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
from .dashboard import STOP_CODES, Dashboard, DashboardError, port_refused
from .engine_copy import fingerprint, make_own_engine
from .processes import Processes
from .stop import finish, read_desk, register_desk, stop_and_verify

README = ("Временная папка проверки экрана «Сборка» (scripts/check_assembly_screen.py): "
          "рабочая папка, свой HOME, своя папка движка, журналы и снимки. Удаляется в конце, "
          "--keep оставляет.\n")


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

    @contextmanager
    def stage(self, name: str):
        started = time.monotonic()
        try:
            yield
        finally:
            self.report.seconds[name] = round(time.monotonic() - started, 1)

    def dashboard(self, name: str, engine_dir: Path) -> Dashboard:
        env = dict(self.env, AIMASTER_HYPERFRAMES_DIR=str(engine_dir))
        board = Dashboard(env, self.workspace, self.work, name)
        self.dashboards.append(board)
        board.start()
        self.processes.add(board.proc.pid, f"дашборд {name}")
        return board

    def phases(self, board: Dashboard, *names: str) -> dict:
        settings = {
            "phases": list(names), "baseUrl": board.base_url, "projectId": project.PROJECT,
            "title": project.TITLE, "workspace": str(self.workspace),
            "indexPath": str(project.index_path(self.workspace)), "enginePrefix": str(self.own.prefix),
            "shots": str(self.shots), "profile": str(self.root / "профиль браузера"),
            "pidFile": str(self.work / "браузер.pid"), "modules": str(self.own.modules),
            "browser": self.own.browser, "reveal": bool(self.args.reveal),
        }
        answer = run_phases(self.own.node, settings, self.work, self.processes, self.env)
        self.report.merge(answer)
        return answer.get("data") or {}

    def prepare(self) -> None:
        self.own = make_own_engine(self.found, self.root / "движок")
        self.env = project.check_env(self.root / "home", self.own.prefix)
        located, reason = engine.locate(environ=self.env)
        self.report.add("engine.own_copy", located is not None and located.prefix == self.own.prefix,
                        "своя папка движка проходит engine.locate()" if located else reason)
        built = project.v001(self.env, self.workspace)["render"]
        self.report.add("cli.v001", built.get("version") == "v001" and built.get("warnings") == [],
                        f"montage draft → render: {built.get('version')}, {built.get('duration')} с")

    def main_flow(self) -> None:
        with self.stage("проект и v001"):
            self.prepare()
        with self.stage("экран на компьютере и стол"):
            board = self.dashboard("engine", self.own.prefix)
            self.phases(board, "desktop", "desk")
            desk = read_desk(self.workspace)
            register_desk(self.processes, desk)
        with self.stage("сборка v002 агентом"):
            done = project.owner_render(self.env, self.workspace)
            changes = done["diff"].get("changes") or []
            self.report.add("cli.diff", bool(changes), "; ".join(changes) or "montage diff: изменений нет")
            built = done["render"]
            self.report.add("cli.v002", built.get("version") == "v002", f"montage render --by owner → {built.get('version')}")
        with self.stage("v2, возврат к v1, закрытие стола"):
            self.phases(board, "after")
            port = (desk or {}).get("port")
            shut = bool(port) and port_refused(port, wait=15)
            self.report.add("desk.port_closed", shut, f"порт стола {port} после «Закрыть стол»: "
                            + ("закрыт" if shut else "принимает соединения" if port else "неизвестен"))
            self.stop(board)
        with self.stage("без движка"):
            board = self.dashboard("no-engine", project.empty_dir(self.root / "движка нет"))
            self.phases(board, "noengine")
            self.stop(board)
        with self.stage("телефон и выход дашборда"):
            board = self.dashboard("exit", self.own.prefix)
            self.phases(board, "phone", "exit")
            stop_and_verify(self, board)

    def stop(self, board: Dashboard) -> None:
        code = board.stop()
        self.report.add(f"dashboard.stop.{board.name}", code in STOP_CODES, f"дашборд остановлен, код {code}")


def run(args, report) -> None:
    found, reason = engine.locate()
    if found is None:
        report.engine_missing = reason
        return
    before = fingerprint(found)
    run_ = Run(args, found, report)
    try:
        run_.main_flow()
    except (SmokeError, DashboardError, OSError, subprocess.SubprocessError) as error:
        report.add("run.crash", False, f"{type(error).__name__}: {error}")
    except Exception:  # noqa: BLE001 — ошибка самой проверки: отчёт всё равно нужен
        report.add("run.crash", False, traceback.format_exc()[-3000:])
    finally:
        finish(run_)
        report.add("engine.shared_untouched", fingerprint(found) == before,
                   "общая папка движка не менялась (пакеты, запись, браузер)")
        if args.keep:
            report.kept = str(run_.root)
