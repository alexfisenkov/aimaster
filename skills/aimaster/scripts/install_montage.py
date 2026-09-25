#!/usr/bin/env python3
"""Монтаж для install.py: собирает раздел `montage` отчёта из трёх частей —
Node.js 22+ (install_montage_node.py), HyperFrames и браузер для сборки
(install_montage_engine.py), скиллы HyperFrames (install_montage_skills.py).

Всё без оболочки: npm запускается как `node <npm-cli.js>`, HyperFrames — как
`node <prefix>/node_modules/hyperframes/bin/hyperframes.mjs`. Движок живёт в
<user_data_dir>/tools/hyperframes со своим HOME (home/): кэши и скачанный
браузер не попадают в домашнюю папку человека.

Отдельный запуск (CI):  python3 install_montage.py --json [--update] [--install-node]
install.py импортирует этот файл только после проверки версии Python.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
for _path in (str(_SCRIPTS), str(_SCRIPTS.parent)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import install  # noqa: E402
from studio.montage import engine  # noqa: E402
from install_montage_engine import browser_install, check_browser, check_package, engine_install  # noqa: E402
from install_montage_node import READY, item, node_check  # noqa: E402
import install_montage_skills  # noqa: E402

LABELS = (("node", "Node.js 22+"), ("hyperframes", "HyperFrames"),
          ("browser", "браузер для сборки"), ("skills", "скиллы HyperFrames"))
WORDS = {"installed": "поставлено", "found": "есть", "missing": "нет", "failed": "ОШИБКА",
         "timeout": "не успело", "conflict": "конфликт имён", "skipped_home": "пропущено (домашняя папка)"}


def montage_report(kind: str, *, install_missing: bool, update: bool, install_node: bool,
                   home: Path | None = None, skills=True) -> dict:
    """`install_missing` (--install-deps) ставит то, чего нет; `update`
    (--update) один, без --install-deps, только чинит уже стоящее на
    закреплённую версию и ничего не ставит с нуля (правило владельца
    2026-09-25, разбор 1/5) — распределение между «поставить» и «починить»
    целиком внутри engine_install/browser_install/skills_report."""

    pin = engine.load_pin()
    prefix = engine.tools_prefix(home=home)
    act = install_missing or update
    report = {"prefix": str(prefix), "node": node_check(kind, install_node)}
    node = report["node"].get("path") if report["node"]["status"] in READY else None
    if node is None:
        report["hyperframes"] = item("missing", f"сначала нужен Node.js {pin['node_min_major']}+")
    elif act:
        report["hyperframes"] = engine_install(node, prefix, pin, install_missing=install_missing,
                                               update=update)
    else:
        report["hyperframes"] = check_package(prefix, pin)
    if report["hyperframes"]["status"] not in READY or engine.installed_version(prefix) != pin["version"]:
        report["browser"] = item("missing", f"сначала нужен HyperFrames {pin['version']}")
    elif act:
        report["browser"] = browser_install(node, prefix, pin, install_missing=install_missing,
                                            update=update)
    else:
        report["browser"] = check_browser(prefix, pin)
    if skills:
        report["skills"] = install_montage_skills.skills_report(install_missing=install_missing,
                                                                 update=update, home=home)
    # ok — готовность движка; статус скиллов виден в report["skills"], сборку он не блокирует
    report["ok"] = all(report[key]["status"] in READY for key in ("node", "hyperframes", "browser"))
    return report


def render_montage_lines(report: dict) -> list[str]:
    lines = ["Монтаж (HyperFrames): " + ("готов" if report.get("ok") else "не готов")]
    if report.get("error"):
        lines.append("  " + report["error"])
    for key, label in LABELS:
        item = report.get(key)
        if not item:
            continue
        lines.append(f"  {label} — {WORDS.get(item['status'], item['status'])}")
        if item.get("message"):
            lines.append("      " + item["message"])
    return lines


def main(argv=None) -> int:
    install.ensure_utf8_output()
    parser = argparse.ArgumentParser(description="Поставить монтажный движок HyperFrames.")
    parser.add_argument("--json", action="store_true", help="вывод JSON")
    parser.add_argument("--update", action="store_true",
                        help="перевести уже стоящий движок/GSAP/браузер/кеш скиллов на версию из "
                             "engine.json; без --install-deps ничего не ставит с нуля")
    parser.add_argument("--install-node", action="store_true",
                        help="поставить Node.js через winget/brew, если его нет или он старый")
    parser.add_argument("--check", action="store_true", help="только проверить, ничего не ставить")
    parser.add_argument("--home", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    home = Path(args.home).expanduser() if args.home else None
    report = montage_report(install.platform_kind(), install_missing=not args.check,
                            update=args.update and not args.check,
                            install_node=args.install_node and not args.check, home=home)
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json
          else "\n".join(render_montage_lines(report)))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
