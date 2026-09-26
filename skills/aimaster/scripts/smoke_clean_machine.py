#!/usr/bin/env python3
"""Смоук «чистой машины»: установка и полный путь автопилота на пустом HOME.

    python3 skills/aimaster/scripts/smoke_clean_machine.py      (macOS / Linux)
    py -3 skills\\aimaster\\scripts\\smoke_clean_machine.py      (Windows)
    … smoke_clean_machine.py --with-engine      (с поставленным движком монтажа)

Подменяет HOME / USERPROFILE / APPDATA / LOCALAPPDATA на временную папку,
ставит навык через install.py --json (без зависимостей), создаёт рабочую
папку с пробелом и кириллицей в имени и проходит: workspace init → library
add/match → проект в автопилоте → сценарий → сцены → одобрение стадии →
референс из библиотеки → платное действие в очередь → переход в guided
(очередь отменяется) → монтаж → сервер на свободном порту и три HTTP-запроса →
остановка → detect_tools.py --json. Шаг «монтаж» — smoke_montage.py (без
движка — команда установки в статусе и в отказе; с --with-engine — сборка v001
уже поставленным движком), общие запуск и проверки — smoke_kit.py. Провайдеры
не вызываются, сеть — только 127.0.0.1. Любое расхождение — код 1 и понятная
строка в логе.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

from smoke_kit import (CLI, REPO, SCRIPTS, SKILL, SmokeError, cli, decode, expect, log,
                       python_argv, run_json, write_png)
from smoke_montage import ENGINE_ENV, installed_engine_prefix, step_montage

PROJECT = "smoke-autopilot"


def clean_env(home: Path) -> dict:
    env = dict(os.environ)
    for name in ("CODEX_HOME", "CLAUDE_CONFIG_DIR", "XDG_CONFIG_HOME", "XDG_DATA_HOME",
                 "AIMASTER_WORKSPACE", "TELEGRAM_STUDIO_BOT_TOKEN", "TELEGRAM_STUDIO_OWNER_ID",
                 ENGINE_ENV):
        env.pop(name, None)
    env["HOME"] = env["USERPROFILE"] = str(home)
    env["APPDATA"] = str(home / "AppData" / "Roaming")
    env["LOCALAPPDATA"] = str(home / "AppData" / "Local")
    for key in ("APPDATA", "LOCALAPPDATA"):
        Path(env[key]).mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        env["HOMEDRIVE"], env["HOMEPATH"] = os.path.splitdrive(str(home))
    return env


# ---------- шаги ----------

def step_install(env: dict, home: Path) -> None:
    report = run_json(env, SCRIPTS / "install.py", "--repo", REPO, "--json")
    expect(report.get("ok") is True, "install.py: ok=false: %s" % json.dumps(report, ensure_ascii=False)[:1500])
    expect(report["python_cmd"], "install.py не назвал python_cmd")
    for item in report["targets"]:
        target = Path(item["path"])
        expect(str(target).startswith(str(home)), "навык поставлен вне временного HOME: %s" % target)
        expect((target / "SKILL.md").is_file(), "после установки нет %s/SKILL.md" % target)
    methods = ", ".join("%s=%s" % (t["agent"], t["method"]) for t in report["targets"])
    log("  установка: %s; python_cmd=%s" % (methods, report["python_cmd"]))
    again = run_json(env, SCRIPTS / "install.py", "--repo", REPO, "--json", "--skip-self-check")
    expect({t["status"] for t in again["targets"]} == {"already"},
           "повторная установка не идемпотентна: %s" % again["targets"])


def step_library(env: dict, workspace: Path, media: Path) -> str:
    init = cli(env, "workspace", "init", workspace)
    expect("projects/" in init["created"], "workspace init не создал projects/: %s" % init)
    png = media / "кот Барсик.png"
    write_png(png)
    added = cli(env, "library", "add", workspace, "--kind", "character", "--label", "Кот Барсик",
                "--alias", "Барсик", "--file", png)
    library_id = added["library_id"]
    matched = cli(env, "library", "match", workspace, "--text", "Ролик про Барсика в саду")
    expect(any(m["library_id"] == library_id for m in matched["matches"]),
           "library match не нашёл персонажа: %s" % matched)
    log("  библиотека: %s найден по фразе" % library_id)
    return library_id


def step_autopilot(env: dict, workspace: Path, media: Path, library_id: str) -> None:
    created = cli(env, "project", "create", workspace, PROJECT, "--title", "Проба «автопилот»",
                  "--type", "video", "--mode", "autopilot")
    expect(created.get("notice"), "автопилот включён без предупреждения: %s" % created)
    rev = created["revision"]
    rev = cli(env, "script", "add-version", workspace, PROJECT, "--text",
              "Кот Барсик гуляет по саду и находит клубок.", "--reason", "смоук",
              "--expected-revision", rev)["revision"]
    scenes = media / "сцены.json"
    scenes.write_text(json.dumps([{"scene_id": "scene-1", "title": "Сад",
                                   "text": "Барсик идёт по саду", "duration_ms": 4000}],
                                 ensure_ascii=False), encoding="utf-8")
    rev = cli(env, "scenes", "set", workspace, PROJECT, "--file", scenes,
              "--expected-revision", rev)["revision"]
    rev = cli(env, "stage", "approve", workspace, PROJECT, "--expected-revision", rev)["revision"]
    ref = cli(env, "reference", "add", workspace, PROJECT, "--from-library", library_id,
              "--all-scenes", "--expected-revision", rev)
    expect(ref.get("library_id") == library_id, "референс не из библиотеки: %s" % ref)
    rev = ref["revision"]
    action = cli(env, "action", "enqueue", workspace, PROJECT, "--type", "generate",
                 "--target", "scene-1", "--expected-revision", rev,
                 "--idempotency-key", "smoke-1")
    expect(action.get("status") == "queued" and action.get("issued_by") == "autopilot",
           "action enqueue: ждали queued/autopilot, получили %s" % action)
    switched = cli(env, "mode", "set", workspace, PROJECT, "--mode", "guided",
                   "--expected-revision", rev + 1)
    expect(action["action_id"] in switched.get("cancelled_actions", []),
           "переход в guided не отменил очередь: %s" % switched)
    log("  автопилот: действие %s поставлено и отменено переходом в guided" % action["action_id"])


def _read_first_line(proc, box):
    box.append(proc.stdout.readline())


def stop_server(proc) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
    except OSError:
        proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=15)
        raise SmokeError("сервер не остановился сам за 15 секунд — пришлось убить процесс")


def step_serve(env: dict, workspace: Path) -> None:
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    proc = subprocess.Popen(python_argv() + [str(CLI), "serve", str(workspace), "--port", "0"],
                            env=env, cwd=str(SKILL), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                            creationflags=flags)
    try:
        box: list = []
        reader = threading.Thread(target=_read_first_line, args=(proc, box), daemon=True)
        reader.start()
        reader.join(timeout=30)
        if not box or not box[0]:
            proc.kill()
            raise SmokeError("сервер не напечатал адрес за 30 секунд; stderr: %s"
                             % decode(proc.stderr.read() or b"")[-1500:])
        base_url = json.loads(decode(box[0]))["base_url"].rstrip("/")
        for path in ("/", "/api/projects", "/static/ui/v2/shell.js"):
            with urllib.request.urlopen(base_url + path, timeout=15) as response:
                body = response.read()
                expect(response.status == 200, "GET %s → %s" % (path, response.status))
            if path == "/api/projects":
                ids = json.dumps(json.loads(decode(body)), ensure_ascii=False)
                expect(PROJECT in ids, "в /api/projects нет проекта %s: %s" % (PROJECT, ids[:500]))
        log("  сервер %s: /, /api/projects, /static/ui/v2/shell.js — 200" % base_url)
    finally:
        stop_server(proc)
    # Windows: Ctrl+Break ends the process with STATUS_CONTROL_C_EXIT
    # (0xC000013A) unless it exits cleanly first; anything else is a crash.
    allowed = (0, 0xC000013A) if os.name == "nt" else (0,)
    expect(proc.returncode in allowed, "сервер завершился с кодом %s после сигнала остановки"
           % proc.returncode)
    log("  сервер остановлен (код %s)" % proc.returncode)


def step_detect_tools(env: dict) -> None:
    report = run_json(env, SCRIPTS / "detect_tools.py", "--json")
    expect(isinstance(report, dict) and "environments" in report,
           "detect_tools.py --json: неожиданная форма %s" % str(report)[:300])
    log("  detect_tools.py --json на пустом HOME: код 0")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    with_engine = "--with-engine" in sys.argv[1:]
    try:
        engine_prefix = installed_engine_prefix() if with_engine else None
    except SmokeError as error:
        log("✗ СМОУК НЕ ПРОЙДЕН: %s" % error)
        return 1
    root = Path(tempfile.mkdtemp(prefix="aimaster-smoke-"))
    home = root / "home"
    workspace = root / "Мои проекты ИИ" / "рабочая папка"
    media = root / "исходники"
    for folder in (home, media):
        folder.mkdir(parents=True)
    env = clean_env(home)
    if engine_prefix:
        env[ENGINE_ENV] = engine_prefix
    log("Смоук чистой машины: Python %s, %s, временная папка %s%s"
        % (sys.version.split()[0], sys.platform, root, ", движок монтажа — уже поставленный"
           if engine_prefix else ""))
    steps = (
        ("установка install.py --json", lambda: step_install(env, home)),
        ("библиотека", lambda: box.__setitem__("lib", step_library(env, workspace, media))),
        ("автопилотный проект", lambda: step_autopilot(env, workspace, media, box["lib"])),
        ("монтаж: %s" % ("черновик и сборка v001" if with_engine else "статус и отказ без движка"),
         lambda: step_montage(env, workspace, PROJECT, with_engine)),
        ("сервер serve --port 0", lambda: step_serve(env, workspace)),
        ("detect_tools на пустом HOME", lambda: step_detect_tools(env)),
    )
    box: dict = {}
    try:
        for name, action in steps:
            log("▶ %s" % name)
            action()
    except (SmokeError, OSError, subprocess.SubprocessError, ValueError, KeyError) as error:
        log("✗ СМОУК НЕ ПРОЙДЕН на шаге «%s»: %s: %s" % (name, type(error).__name__, error))
        return 1
    finally:
        shutil.rmtree(root, ignore_errors=True)
    log("✓ смоук пройден")
    return 0


if __name__ == "__main__":
    sys.exit(main())
