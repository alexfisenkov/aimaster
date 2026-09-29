#!/usr/bin/env python3
"""Сквозная проверка экрана «Сборка» (монтаж на HyperFrames) — то, что
контролёр выпуска прошёл руками, повторяемо перед каждым выпуском.

    python3 skills/aimaster/scripts/check_assembly_screen.py [--json] [--reveal]
        [--shots ПАПКА] [--keep] [--require-engine]

Нужен поставленный монтажный движок (`engine.locate()`); без него — код 2 и
команда установки (с --require-engine — код 1). Общая папка движка только
читается: у проверки своя папка движка, свой HOME и временная рабочая папка
с синтетическим проектом (assembly_check/engine_copy.py, project.py). Команды
агента — `creator_studio.py montage …` отдельными процессами; дашборд —
`creator_studio.py serve --port 0`; браузер — chrome-headless-shell движка
через puppeteer-core движка (check_assembly_screen.mjs и фазы в
assembly_check/). Шаги — assembly_check/run.py.

--reveal нажимает «Показать в папке» по-настоящему (откроется Finder или
Проводник — только на своём компьютере); без него проверяется, что кнопка есть
и что запрос без CSRF отклонён. --shots — куда сложить снимки экрана (по
умолчанию — во временную папку, которая удаляется; --keep её оставляет).
Отчёт — JSON `{ok, checks: [{id, ok, detail, required}], shots, seconds}`
с --json, иначе — строки по-русски. Код 0 — все обязательные проверки прошли.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
for _path in (str(_SCRIPTS.parent), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from assembly_check.report import Report, exit_code  # noqa: E402
from studio.montage.engine import install_command  # noqa: E402
from studio.platform_compat import ensure_utf8_stdio  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Сквозная проверка экрана «Сборка» на настоящем движке.")
    parser.add_argument("--json", action="store_true", help="отчёт JSON в stdout")
    parser.add_argument("--reveal", action="store_true",
                        help="нажать «Показать в папке» по-настоящему (откроет файловый менеджер)")
    parser.add_argument("--shots", type=Path, default=None, help="папка для снимков экрана")
    parser.add_argument("--keep", action="store_true", help="оставить временную папку прогона")
    parser.add_argument("--require-engine", action="store_true",
                        help="нет движка — провал (код 1), а не пропуск (код 2)")
    return parser


def missing_text(reason: str) -> str:
    return (f"Монтажный движок не установлен ({reason}) — экран «Сборка» проверять не на чем. "
            f"Установка: {install_command()}")


def main(argv=None, *, run=None) -> int:
    ensure_utf8_stdio()
    args = build_parser().parse_args(argv)
    report = Report()
    if run is None:
        from assembly_check.run import run
    run(args, report)
    if report.engine_missing:
        report.engine_missing = missing_text(report.engine_missing)
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2) if args.json else report.text(),
          flush=True)
    return exit_code(report, require_engine=args.require_engine)


if __name__ == "__main__":
    sys.exit(main())
