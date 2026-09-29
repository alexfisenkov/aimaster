"""Шаги проверки экрана «Сборка» — то, что контролёр прошёл руками.

1. Своя папка движка, свой HOME, синтетический проект → v001 командами агента
   (без этого шага проверять нечего — дальше не идём).
2. Дашборд с движком: фазы desktop и desk (стол, правка мышью в Studio); агент:
   montage diff, ревизия из status, montage render --by owner → v002; фаза after
   («текущая v2», «Сделать текущей», «Закрыть стол»); порт стола закрыт.
3. Дашборд без движка: фаза noengine.
4. Дашборд с движком: фазы phone и exit; остановка дашборда (stop.py).
`run` — объект прогона (run.py): отчёт, окружение, дашборды, фазы."""

from __future__ import annotations

from studio.montage import engine
from . import project
from .dashboard import port_refused
from .engine_copy import make_own_engine
from .stop import read_desk, register_desk, stop_and_verify


def prepare(run) -> None:
    run.own = make_own_engine(run.found, run.root / "движок")
    run.env = project.check_env(run.root / "home", run.own.prefix)
    located, reason = engine.locate(environ=run.env)
    run.report.add("engine.own_copy", located is not None and located.prefix == run.own.prefix,
                   "своя папка движка проходит engine.locate()" if located else reason)
    built = project.v001(run.env, run.workspace)["render"]
    run.report.add("cli.v001", built.get("version") == "v001" and built.get("warnings") == [],
                   f"montage draft → render: {built.get('version')}, {built.get('duration')} с")


def owner_render(run) -> None:
    done = project.owner_render(run.env, run.workspace)
    changes = done["diff"].get("changes") or []
    run.report.add("cli.diff", bool(changes), "; ".join(changes) or "montage diff: изменений нет")
    version = done["render"].get("version")
    run.report.add("cli.v002", version == "v002", f"montage render --by owner → {version}")


def with_engine(run) -> None:
    with run.dashboard("engine", run.own.prefix) as board:
        run.phases(board, "desktop", "desk")
        desk = read_desk(run.workspace)
        register_desk(run.processes, desk)
        run.guard("cli", lambda: owner_render(run))
        run.phases(board, "after")
        port = (desk or {}).get("port")
        shut = bool(port) and port_refused(port, wait=15)
        run.report.add("desk.port_closed", shut, f"порт стола {port} после «Закрыть стол»: "
                       + ("закрыт" if shut else "принимает соединения" if port else "неизвестен"))


def without_engine(run) -> None:
    with run.dashboard("no-engine", project.empty_dir(run.root / "движка нет")) as board:
        run.phases(board, "noengine")


def phone_and_exit(run) -> None:
    with run.dashboard("exit", run.own.prefix) as board:
        run.phases(board, "phone", "exit")
        stop_and_verify(run, board)


def main_flow(run) -> None:
    if not run.guard("prepare", lambda: prepare(run), timed=True):
        return  # нет проекта — экран проверять не на чем
    run.guard("engine", lambda: with_engine(run), timed=True)
    run.guard("noengine", lambda: without_engine(run), timed=True)
    run.guard("exit", lambda: phone_and_exit(run), timed=True)
