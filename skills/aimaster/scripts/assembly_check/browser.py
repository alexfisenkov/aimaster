"""Запуск браузерных фаз (`scripts/check_assembly_screen.mjs`) узлом движка.

Настройки фаз — JSON-файлом, ответ — последней строкой stdout. Узел идёт своей
группой процессов (`proc_tree.group_kwargs`): не уложился в срок — узел
останавливается целиком, с браузером (`kill_tree`). Номер браузера узел
пишет в файл учёта сразу после запуска; пока узел работает, этот номер
записывается в учёт процессов вместе со временем запуска — после выхода
узла его номер мог бы уже достаться чужому процессу."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from smoke_kit import SCRIPTS, decode
from studio.montage.proc_tree import group_kwargs, kill_tree

MJS = SCRIPTS / "check_assembly_screen.mjs"
PHASE_TIMEOUT = 900.0  # все фазы одного запуска; обычно — десятки секунд


def _pids(pid_file: Path) -> list[int]:
    try:
        return [int(line) for line in pid_file.read_text(encoding="ascii").split() if line.isdigit()]
    except OSError:
        return []


def _answer(out: str, code: int, err: str) -> dict:
    for line in reversed(out.strip().splitlines()):
        try:
            answer = json.loads(line)
        except ValueError:
            continue
        if isinstance(answer, dict) and isinstance(answer.get("checks"), list):
            return answer
    return {"checks": [{"id": "browser.crash", "ok": False,
                        "detail": f"узел завершился с кодом {code} без ответа: {err.strip()[-1500:]}"}]}


def run_phases(node: str, settings: dict, work: Path, processes, env: dict, *,
               timeout: float = PHASE_TIMEOUT) -> dict:
    name = "-".join(settings["phases"])
    config, out_file, err_file = (work / f"фазы-{name}.{kind}" for kind in ("json", "out", "err"))
    config.write_text(json.dumps(settings, ensure_ascii=False), encoding="utf-8")
    pid_file = Path(settings["pidFile"])
    with open(out_file, "wb") as out, open(err_file, "wb") as err:
        proc = subprocess.Popen([node, str(MJS), str(config)], cwd=str(SCRIPTS), env=env, stdin=subprocess.DEVNULL,
                                stdout=out, stderr=err, **group_kwargs())
    processes.add(proc.pid, "узел браузерных фаз")
    deadline = time.monotonic() + timeout
    while proc.poll() is None and time.monotonic() < deadline:
        for pid in _pids(pid_file):
            processes.add(pid, "браузер фаз", with_children=True)
        time.sleep(0.5)
    if proc.poll() is None:
        kill_tree(proc)
        proc.wait(timeout=30)
        return {"checks": [{"id": f"{name}.timeout", "ok": False,
                            "detail": f"браузерные фазы не уложились в {timeout:.0f} с"}]}
    return _answer(decode(out_file.read_bytes()), proc.returncode, decode(err_file.read_bytes()))
