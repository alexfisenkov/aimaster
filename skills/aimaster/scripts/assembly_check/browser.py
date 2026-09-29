"""Запуск браузерных фаз (`scripts/check_assembly_screen.mjs`) узлом движка.

Настройки — JSON-файлом; ответ — по строке JSON на каждую законченную фазу
(`{"phase", "checks", "shots", "data"}`), так что упавший или зависший узел
не уносит результаты уже пройденных фаз. Срок — `PHASE_BUDGET` на фазу: узел
сам отмечает фазу, не уложившуюся в него, а оркестратор останавливает узел
целиком (`kill_tree`), если тот не вышел за сумму сроков и запас на запуск.

Учёт процессов: у каждого запуска свой файл номеров браузера (пустой при
старте). Пока узел жив, он и все его потомки (браузер, его процессы)
записываются каждые полсекунды — потомки нашего живого узла не могут быть
чужими; номер из файла подписывается «браузер фаз», только если он среди них."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from smoke_kit import SCRIPTS, decode
from studio.montage.proc_tree import group_kwargs, kill_tree

MJS = SCRIPTS / "check_assembly_screen.mjs"
# Секунд на фазу — у узла и у оркестратора; обычная фаза идёт 1–35 с. Худший
# случай всех четырёх запусков (6 фаз): 6 × 150 + 4 × 60 = 1140 с — под него
# и срок шага в CI (timeout-minutes, .github/workflows/ci.yml).
PHASE_BUDGET = 150.0
LAUNCH_MARGIN = 60.0


def _pids(pid_file: Path) -> set[int]:
    try:
        return {int(line) for line in pid_file.read_text(encoding="ascii").split() if line.isdigit()}
    except OSError:
        return set()


def answers(out: str, phases: list[str], code: int, err: str) -> dict:
    """Строки фаз из вывода узла → {checks, shots, data}; фаза без строки — провал."""

    found = {}
    for line in out.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict) and item.get("phase") in phases and isinstance(item.get("checks"), list):
            found[item["phase"]] = item
    result = {"checks": [], "shots": [], "data": {}}
    for phase in phases:
        item = found.get(phase)
        if item is None:
            result["checks"].append({"id": f"{phase}.no_result", "ok": False, "detail": (
                f"фаза не прошла: узел завершился с кодом {code}; {err.strip()[-1200:] or 'без вывода'}")})
            continue
        result["checks"] += item["checks"]
        result["shots"] += item.get("shots") or []
        result["data"][phase] = item.get("data") or {}
    return result


def run_phases(node: str, settings: dict, work: Path, processes, env: dict, *,
               budget: float = PHASE_BUDGET) -> dict:
    name = "-".join(settings["phases"])
    config, out_file, err_file, pid_file = (work / f"фазы-{name}.{kind}" for kind in ("json", "out", "err", "pid"))
    pid_file.write_text("", encoding="ascii")
    settings = {**settings, "pidFile": str(pid_file), "phaseBudgetMs": int(budget * 1000)}
    config.write_text(json.dumps(settings, ensure_ascii=False), encoding="utf-8")
    with open(out_file, "wb") as out, open(err_file, "wb") as err:
        proc = subprocess.Popen([node, str(MJS), str(config)], cwd=str(SCRIPTS), env=env, stdin=subprocess.DEVNULL,
                                stdout=out, stderr=err, **group_kwargs())
    processes.add(proc.pid, "узел браузерных фаз")
    deadline = time.monotonic() + budget * len(settings["phases"]) + LAUNCH_MARGIN
    while proc.poll() is None and time.monotonic() < deadline:
        processes.add(proc.pid, "узел браузерных фаз", with_children=True)
        for pid in _pids(pid_file):
            if pid in processes.known and processes.known[pid][0].startswith("узел браузерных фаз → "):
                processes.known[pid] = ("браузер фаз", processes.known[pid][1])
        time.sleep(0.5)
    if proc.poll() is None:
        kill_tree(proc)
        proc.wait(timeout=30)
    return answers(decode(out_file.read_bytes()), settings["phases"], proc.returncode,
                   decode(err_file.read_bytes()))
