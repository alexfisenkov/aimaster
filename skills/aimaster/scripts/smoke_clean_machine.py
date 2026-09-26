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
остановка → detect_tools.py --json. Монтаж: на чистой машине движка нет —
`montage status` и отказ `montage draft` (код 3) называют одну и ту же команду
установки; с --with-engine смоук берёт движок, уже поставленный на этой машине
(engine.locate до подмены HOME), доводит второй проект через CLI до сборки
(клипы — ffmpeg) и проходит montage draft → render v001 → status. Провайдеры
не вызываются, сеть — только 127.0.0.1. Любое расхождение — код 1 и понятная
строка в логе.
"""

from __future__ import annotations

import json
import locale
import os
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import urllib.request
import zlib
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
SKILL = SCRIPTS.parent
REPO = SKILL.parent.parent
CLI = SCRIPTS / "creator_studio.py"
PROJECT = "smoke-autopilot"
MONTAGE_PROJECT = "smoke-montage"
ENGINE_ENV = "AIMASTER_HYPERFRAMES_DIR"


class SmokeError(Exception):
    pass


def log(message: str) -> None:
    print(message, flush=True)


def decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode(locale.getpreferredencoding(False), errors="replace")


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


def python_argv() -> list:
    argv = [sys.executable]
    if sys.flags.utf8_mode:
        argv += ["-X", "utf8"]
    return argv


def run(env: dict, *argv, expect_code: int = 0) -> str:
    cmd = python_argv() + [str(item) for item in argv]
    proc = subprocess.run(cmd, env=env, cwd=str(SKILL), stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, timeout=180)
    out, err = decode(proc.stdout), decode(proc.stderr)
    if proc.returncode != expect_code:
        raise SmokeError("команда %s завершилась с кодом %s (ожидали %s)\nstdout: %s\nstderr: %s"
                         % (" ".join(str(a) for a in argv[:3]), proc.returncode, expect_code,
                            out.strip()[-1500:], err.strip()[-1500:]))
    return out


def run_json(env: dict, *argv) -> dict:
    out = run(env, *argv)
    try:
        return json.loads(out)
    except ValueError:
        raise SmokeError("не JSON в выводе %s: %r" % (" ".join(map(str, argv[:3])), out[:500]))


def cli(env: dict, *argv) -> dict:
    return run_json(env, CLI, *argv)


def run_refused(env: dict, *argv) -> str:
    """Команда должна отказать кодом 3 (доменный отказ) без traceback; возвращает stderr."""

    cmd = python_argv() + [str(item) for item in argv]
    proc = subprocess.run(cmd, env=env, cwd=str(SKILL), stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, timeout=180)
    err = decode(proc.stderr)
    expect(proc.returncode == 3 and "Traceback" not in err,
           "команда %s: ждали отказ с кодом 3, получили код %s; stderr: %s"
           % (" ".join(str(a) for a in argv[1:4]), proc.returncode, err[-800:]))
    return err


def expect(condition, message: str) -> None:
    if not condition:
        raise SmokeError(message)


def write_png(path: Path) -> None:
    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\x20\x80\xc0" * 8 for _ in range(8))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


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


def montage_without_engine(env: dict, workspace: Path, status: dict) -> None:
    install = status["engine"].get("install") or ""
    expect(install.endswith("--install-deps") and "install.py" in install,
           "montage status: без движка нет команды установки: %s" % status["engine"])
    expect(status["skills"].get("status") == "missing",
           "montage status: скиллов HyperFrames на чистой машине быть не может: %s" % status["skills"])
    err = run_refused(env, CLI, "montage", "draft", workspace, PROJECT,
                      "--expected-revision", status["revision"])
    expect("Монтажный движок не готов" in err and install in err,
           "montage draft: ждали отказ с командой установки «%s», получили %s" % (install, err[-800:]))
    log("  монтаж: движка нет — status и отказ montage draft называют одну команду установки")


def make_clip(ffmpeg: str, path: Path, seconds: float, color: str, freq: int) -> None:
    subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=%s:s=180x320:r=30:d=%s" % (color, seconds), "-f", "lavfi", "-i",
                    "sine=frequency=%s:duration=%s" % (freq, seconds), "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-g", "30", "-c:a", "aac", "-shortest", str(path)],
                   check=True, stdin=subprocess.DEVNULL, timeout=120)


def project_ready_for_assembly(env: dict, workspace: Path) -> int:
    """Видеопроект в автопилоте, доведённый через CLI до сборки: две сцены с
    принятыми картинками и видео (клипы — ffmpeg); возвращает ревизию."""

    ffmpeg = shutil.which("ffmpeg")
    expect(ffmpeg, "движок монтажа стоит, а ffmpeg нет — нечем сделать клипы для черновика")
    folder = workspace / "media" / "монтаж"
    folder.mkdir(parents=True, exist_ok=True)
    write_png(folder / "кадр.png")
    make_clip(ffmpeg, folder / "клип 1.mp4", 2.0, "red", 440)
    make_clip(ffmpeg, folder / "клип 2.mp4", 1.0, "blue", 660)
    ids = {name: cli(env, "asset", "register", workspace, "--path", "media/монтаж/" + name,
                     "--role", "result")["asset_id"] for name in ("кадр.png", "клип 1.mp4", "клип 2.mp4")}
    p = MONTAGE_PROJECT
    rev = cli(env, "project", "create", workspace, p, "--title", "Проба «монтаж»", "--type", "video",
              "--mode", "autopilot")["revision"]
    rev = cli(env, "script", "add-version", workspace, p, "--text", "Кот Барсик находит клубок.",
              "--reason", "смоук", "--expected-revision", rev)["revision"]
    scenes = folder / "сцены.json"
    scenes.write_text(json.dumps([{"scene_id": "s1", "title": "Сад", "text": "Барсик идёт по саду",
                                   "duration_ms": 2000},
                                  {"scene_id": "s2", "title": "Клубок", "text": "Находит клубок",
                                   "duration_ms": 1000}], ensure_ascii=False), encoding="utf-8")
    rev = cli(env, "scenes", "set", workspace, p, "--file", scenes, "--expected-revision", rev)["revision"]
    rev = cli(env, "stage", "approve", workspace, p, "--expected-revision", rev)["revision"]
    for kind in ("image", "motion"):
        for scene in ("s1", "s2"):
            rev = cli(env, "prompt", "add-version", workspace, p, "--scene", scene, "--kind", kind,
                      "--text", "кадр " + scene, "--reason", "смоук", "--expected-revision", rev)["revision"]
    rev = cli(env, "stage", "approve", workspace, p, "--expected-revision", rev)["revision"]
    for kind, files in (("image", ("кадр.png", "кадр.png")), ("video", ("клип 1.mp4", "клип 2.mp4"))):
        for scene, name in zip(("s1", "s2"), files):
            rev = cli(env, "result", "add-version", workspace, p, "--scene", scene, "--kind", kind,
                      "--asset-id", ids[name], "--expected-revision", rev)["revision"]
        for scene in ("s1", "s2"):
            rev = cli(env, "decide", workspace, p, "approve", "--target",
                      "result:scene:%s:%s-v1" % (scene, kind), "--expected-revision", rev)["revision"]
        rev = cli(env, "stage", "approve", workspace, p, "--expected-revision", rev)["revision"]
    return cli(env, "stage", "approve", workspace, p, "--expected-revision", rev)["revision"]  # звук


def montage_with_engine(env: dict, workspace: Path) -> None:
    rev = project_ready_for_assembly(env, workspace)
    p = MONTAGE_PROJECT
    drafted = cli(env, "montage", "draft", workspace, p, "--expected-revision", rev)
    expect(drafted.get("clips") == 2 and drafted.get("duration") == 3.0,
           "montage draft: неожиданный черновик %s" % json.dumps(drafted, ensure_ascii=False)[:800])
    built = cli(env, "montage", "render", workspace, p, "--expected-revision", drafted["revision"])
    expect(built.get("version") == "v001" and built.get("warnings") == [] and Path(built["path"]).is_file(),
           "montage render: неожиданная сборка %s" % json.dumps(built, ensure_ascii=False)[:800])
    status = cli(env, "montage", "status", workspace, p, "--json")
    expect((status.get("current_version"), status.get("unrendered_changes")) == ("v001", False)
           and status["paths"].get("output") == built["path"],
           "montage status после сборки: %s" % json.dumps(status, ensure_ascii=False)[:800])
    log("  монтаж: движок %s, черновик → v001 (%s с), скиллы HyperFrames: %s"
        % (status["engine"]["version"], built["duration"], drafted["skills"]["status"]))


def step_montage(env: dict, workspace: Path, with_engine: bool) -> None:
    status = cli(env, "montage", "status", workspace, PROJECT, "--json")
    expect(status.get("exists") is False and status.get("current_version") is None
           and status.get("layers") == [],
           "montage status: неожиданная форма %s" % json.dumps(status, ensure_ascii=False)[:800])
    state = status["engine"]["state"]
    expect(state == ("installed" if with_engine else "missing"),
           "montage status: engine.state=%s, а смоук %s движка" % (state, "с" if with_engine else "без"))
    if with_engine:
        montage_with_engine(env, workspace)
    else:
        montage_without_engine(env, workspace, status)


def installed_engine_prefix() -> str:
    """--with-engine: движок, уже поставленный на этой машине, — до подмены HOME."""

    sys.path.insert(0, str(SKILL))
    from studio.montage.engine import locate
    found, reason = locate()
    if found is None:
        raise SmokeError("--with-engine: монтажный движок не найден: %s" % reason)
    return str(found.prefix)


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
         lambda: step_montage(env, workspace, with_engine)),
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
