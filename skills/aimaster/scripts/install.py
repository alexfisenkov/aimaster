#!/usr/bin/env python3
"""Установщик aimaster одной командой — macOS, Linux и Windows (без WSL).

    macOS / Linux:  python3 skills/aimaster/scripts/install.py
    Windows:        py -3 skills\\aimaster\\scripts\\install.py

Что делает (только стандартная библиотека Python):
  1. проверяет Python 3.11+ (иначе печатает точную команду установки, код 2);
  2. подключает папку skills/aimaster в каталоги навыков агентов:
     Claude Code — ~/.claude/skills/aimaster, Codex и другие — ~/.agents/skills/aimaster.
     macOS/Linux — символическая ссылка; Windows — directory junction
     (прав администратора не нужно), затем symlink, в крайнем случае копия;
  3. проверяет необязательные программы (ffmpeg, cloudflared, git) и монтаж
     (Node.js 22+, движок HyperFrames, браузер для сборки, скиллы HyperFrames —
     scripts/install_montage.py) и ставит их только с флагом --install-deps;
  4. делает самопроверку во временной папке и удаляет её;
  5. печатает python_cmd — как запускать Python на этой машине.

Ничего не перезаписывает: чужая папка на месте навыка не трогается никогда,
своя старая ссылка или копия заменяется только с --force (копия — ещё и с --update).
Не трогает токены, аккаунты и настройки MCP. `--json` — вывод для агента.

Синтаксис файла совместим со старыми Python 3, чтобы проверка версии успела
сказать, что делать.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MIN_PYTHON = (3, 11)
OFFICIAL_ORIGIN = "https://github.com/alexfisenkov/aimaster.git"
OFFICIAL_BRANCH = "main"
MARKER = ".aimaster-install.json"
AGENT_DIRS = (
    ("claude", "Claude Code", (".claude", "skills")),
    ("codex", "Codex и другие агенты (~/.agents)", (".agents", "skills")),
)
PYTHON_INSTALL = {
    "windows": "winget install -e --id Python.Python.3.12",
    "macos": "brew install python@3.12",
    "linux": "sudo apt install python3.12",
}
# name, purpose, install-group, {platform: command}; group None = только подсказка
DEPS = (
    ("ffmpeg", "звук и сборка ролика", "ffmpeg", {
        "windows": "winget install -e --id Gyan.FFmpeg",
        "macos": "brew install ffmpeg", "linux": "sudo apt install ffmpeg"}),
    ("ffprobe", "проверка медиафайлов, ставится вместе с ffmpeg", "ffmpeg", {
        "windows": "winget install -e --id Gyan.FFmpeg",
        "macos": "brew install ffmpeg", "linux": "sudo apt install ffmpeg"}),
    ("cloudflared", "Mini App в Telegram, HTTPS-туннель", "cloudflared", {
        "windows": "winget install -e --id Cloudflare.cloudflared",
        "macos": "brew install cloudflared",
        "linux": "см. https://pkg.cloudflare.com/ (пакет cloudflared)"}),
    ("git", "обновление навыка", "git", {
        "windows": "winget install -e --id Git.Git",
        "macos": "brew install git", "linux": "sudo apt install git"}),
)
WINGET_FLAGS = ["--accept-package-agreements", "--accept-source-agreements",
                "--disable-interactivity"]
INSTALL_TIMEOUT = 900  # секунд на одну программу: winget/brew качают сотни мегабайт
TIMEOUT_CODE = 124
# cmd.exe толкует эти знаки даже внутри кавычек (% и !) или вне их; путь с ними
# в команду mklink не передаём.
CMD_UNSAFE = set('&^%!|<>"')


def _is_windows():
    return os.name == "nt"


def _version_info():
    return tuple(sys.version_info[:3])


def platform_kind():
    if _is_windows():
        return "windows"
    return "macos" if sys.platform == "darwin" else "linux"


def ensure_utf8_output():
    """Русский текст не должен падать на консоли Windows с кодовой страницей."""
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
        if encoding != "utf8" and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def _run(argv, cwd=None, timeout=None, env=None):
    """Запуск без оболочки; вывод как байты, декодируем сами (UTF-8 с заменой).

    Код TIMEOUT_CODE — программа не уложилась в timeout и остановлена."""
    try:
        proc = subprocess.run(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              stdin=subprocess.DEVNULL, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return TIMEOUT_CODE, "", "не завершилась за %s с" % timeout
    except (OSError, subprocess.SubprocessError) as error:
        return 127, "", str(error)
    decode = lambda raw: (raw or b"").decode("utf-8", errors="replace")  # noqa: E731
    return proc.returncode, decode(proc.stdout), decode(proc.stderr)


# ---------- поиск программ ----------

def _search_dirs():
    """Каталоги PATH, только абсолютные: пустой или относительный элемент PATH
    означал бы текущую папку, а в ней может лежать чужой git.exe."""
    dirs = []
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        entry = entry.strip().strip('"')
        if entry and os.path.isabs(entry) and entry not in dirs:
            dirs.append(entry)
    return dirs


def _find_program(name):
    """Полный путь к программе или None. Голое имя в subprocess на Windows
    сначала ищется в текущей папке (CreateProcess), поэтому запускаем только
    по полному пути; shutil.which на Windows тоже подставляет текущую папку."""
    dirs = _search_dirs()
    if not _is_windows():
        return shutil.which(name, path=os.pathsep.join(dirs)) if dirs else None
    # .bat/.cmd запускаются через cmd.exe — берём только настоящие программы
    suffixes = ("",) if os.path.splitext(name)[1] else (".exe", ".com")
    for folder in dirs:
        for suffix in suffixes:
            candidate = os.path.join(folder, name + suffix)
            # лишний lexists: псевдонимы из WindowsApps (winget) — точки повторной обработки
            if (os.path.isfile(candidate) or os.path.lexists(candidate)) \
                    and not os.path.isdir(candidate):
                return candidate
    return None


def _system_program(name):
    """Программа из System32 (cmd.exe) — не из PATH и не из текущей папки."""
    root = os.environ.get("SystemRoot") or os.environ.get("windir") or "C:\\Windows"
    return os.path.join(root, "System32", name)


# ---------- Python ----------

def _probe_python(argv):
    code, out, _ = _run(argv + ["-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
                        timeout=20)
    if code != 0:
        return None
    try:
        major, minor = out.strip().splitlines()[-1].split(".")
        return int(major), int(minor)
    except (ValueError, IndexError):
        return None


def python_cmd():
    """Команда, которой агент будет запускать Python на этой машине."""
    if _is_windows():
        candidates = [["py", "-3"], ["python"], ["python3"]]
    else:
        candidates = [["python3"], ["python"]]
    for argv in candidates:
        found = _find_program(argv[0])
        if found is None:
            continue
        version = _probe_python([found] + argv[1:])
        if version is not None and version >= MIN_PYTHON:
            return " ".join(argv)
    exe = sys.executable
    return '"%s"' % exe if " " in exe else exe


# ---------- ссылки и копии ----------

def _norm(path):
    return os.path.normcase(os.path.realpath(str(path)))


def _is_link_like(path):
    path = str(path)
    if os.path.islink(path):
        return True
    isjunction = getattr(os.path, "isjunction", None)
    if isjunction is not None and isjunction(path):
        return True
    if _is_windows() and os.path.isdir(path):
        try:
            os.readlink(path)
            return True
        except (OSError, ValueError, AttributeError):
            return False
    return False


def _looks_like_aimaster(path):
    skill = Path(path) / "SKILL.md"
    try:
        head = skill.read_text(encoding="utf-8", errors="replace")[:400]
    except OSError:
        return False
    return "name: aimaster" in head


def inspect_target(target, source):
    """missing | ours_link | old_link | ours_copy | foreign."""
    target = Path(target)
    if _is_link_like(target):
        if _norm(target) == _norm(source):
            return "ours_link"
        dangling = not os.path.exists(str(target))
        return "old_link" if dangling or _looks_like_aimaster(target) else "foreign"
    if not target.exists():
        return "missing"
    if target.is_dir() and (target / MARKER).is_file():
        return "ours_copy"
    return "foreign"


def _make_symlink(source, target):
    os.symlink(str(source), str(target), target_is_directory=True)


def _winapi_module():
    try:
        import _winapi
    except ImportError:
        return None
    return _winapi if hasattr(_winapi, "CreateJunction") else None


def _mklink_command(source, target):
    """Строка для cmd.exe или OSError, если путь cmd испортит."""
    for path in (str(source), str(target)):
        bad = sorted(set(path) & CMD_UNSAFE)
        if bad:
            raise OSError("в пути есть знаки %s, которые cmd.exe толкует как команды; "
                          "junction через cmd не создаю: %s" % (" ".join(bad), path))
    return '"%s" /d /c mklink /J "%s" "%s"' % (_system_program("cmd.exe"), target, source)


def _make_junction(source, target):
    """Junction без оболочки (_winapi.CreateJunction), иначе cmd — только для
    путей без спецзнаков cmd (& ^ % ! | < >)."""
    winapi = _winapi_module()
    if winapi is not None:
        winapi.CreateJunction(str(source), str(target))
        return
    command = _mklink_command(source, target)
    code, out, err = _run(command, timeout=60)
    if code != 0:
        raise OSError((err or out).strip() or "mklink /J завершился с кодом %s" % code)


def _make_copy(source, target, version):
    shutil.copytree(str(source), str(target),
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))
    marker = {"installed_by": "install.py", "method": "copy", "source": str(source),
              "version": version}
    (Path(target) / MARKER).write_text(json.dumps(marker, ensure_ascii=False, indent=2) + "\n",
                                       encoding="utf-8")


def connect(source, target, version):
    """Подключает навык на пустое место; возвращает (метод, заметки о неудачных
    способах). Всё, что неудачная попытка успела создать, убирается перед
    следующей; если не удалась и копия — OSError, на месте ничего не остаётся."""
    attempts = []
    makers = [("symlink", _make_symlink)]
    if _is_windows():
        makers = [("junction", _make_junction), ("symlink", _make_symlink)]
    for method, make in makers:
        try:
            make(source, target)
        except (OSError, NotImplementedError) as error:
            attempts.append("%s: %s" % (method, error))
            _discard_partial(target)
            continue
        if _norm(target) == _norm(source):
            return method, attempts
        attempts.append("%s: ссылка создана, но ведёт не туда" % method)
        _discard_partial(target)
    try:
        _make_copy(source, target, version)
    except (OSError, shutil.Error) as error:
        _discard_partial(target)
        attempts.append("copy: %s" % _short_error(error))
        raise OSError("; ".join(attempts))
    return "copy", attempts


def _short_error(error):
    text = str(error)
    return text if len(text) <= 400 else text[:400] + "…"


def _discard_partial(target):
    """Убирает недоделанную ссылку или копию, созданную этим запуском."""
    if _is_link_like(target) or os.path.islink(str(target)):
        _remove_link(target)
    elif os.path.isdir(str(target)):
        shutil.rmtree(str(target))
    elif os.path.lexists(str(target)):
        os.unlink(str(target))


def _remove_link(target):
    try:
        os.unlink(str(target))
    except OSError:
        os.rmdir(str(target))  # junction и dir-symlink на Windows


def _inside(path, folder):
    path, folder = _norm(path), _norm(folder)
    return path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)


def _leave(folder):
    """Если текущая папка процесса внутри folder — выйти из неё: Windows не даёт
    переименовать или удалить папку, в которой стоит чей-то cwd."""
    try:
        cwd = os.getcwd()
    except OSError:
        cwd = None
    if cwd is None or _inside(cwd, folder):
        os.chdir(str(Path(folder).parent))


def replace_installed(source, target, version):
    """Меняет свою старую ссылку или копию на новую без окна «навыка нет».

    Новое собирается рядом во временной папке (…/new), старое переименовывается
    туда же (…/old), новое встаёт на место, старое удаляется последним. Если
    замена сорвалась — старое возвращается на место. Возвращает (метод,
    заметки, путь к недоудалённому старому или None)."""
    target = Path(target)
    _leave(target)
    work = Path(tempfile.mkdtemp(prefix=".aimaster-update-", dir=str(target.parent)))
    fresh, old = work / "new", work / "old"
    try:
        method, attempts = connect(source, fresh, version)
        os.rename(str(target), str(old))  # ссылка переименовывается сама, не её цель
        try:
            os.rename(str(fresh), str(target))
        except OSError:
            if not os.path.lexists(str(target)):
                os.rename(str(old), str(target))
            raise
    finally:
        leftover = _cleanup_work(work)
    return method, attempts, leftover


def _cleanup_work(work):
    """Удаляет временную папку замены; путь, если удалить не вышло."""
    for child in ("new", "old"):
        path = work / child
        if os.path.lexists(str(path)):
            try:
                _discard_partial(path)
            except OSError:
                pass
    try:
        os.rmdir(str(work))
    except OSError:
        return str(work) if os.path.lexists(str(work)) else None
    return None


def install_target(agent, label, target, source, version, force, update):
    item = {"agent": agent, "label": label, "path": str(target), "method": None,
            "status": None, "message": ""}
    state = inspect_target(target, source)
    if state == "ours_link":
        item.update(status="already", method="link",
                    message="уже подключено к этой копии aimaster")
        return item
    if state == "foreign":
        item.update(status="conflict", message=(
            "на этом месте лежит чужая папка или ссылка; ничего не тронуто. "
            "Перенесите её сами или выберите другой путь"))
        return item
    if state == "old_link" and not force:
        item.update(status="conflict", message=(
            "здесь ссылка на другую копию aimaster (%s); ничего не тронуто. "
            "Заменить: повторите с --force" % os.path.realpath(str(target))))
        return item
    if state == "ours_copy" and not (force or update):
        item.update(status="already", method="copy", message=(
            "стоит копия; обновить её: повторите с --update"))
        return item
    replaced = state in ("old_link", "ours_copy")
    try:
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        leftover = None
        if replaced:
            method, attempts, leftover = replace_installed(source, target, version)
        else:
            method, attempts = connect(source, target, version)
    except (OSError, shutil.Error) as error:
        message = "подключить не удалось: %s." % _short_error(error)
        if replaced:
            message += (" Прежняя версия оставлена на месте. Если папка навыка открыта в "
                        "другом окне или терминале (на Windows это мешает замене), закройте "
                        "его и повторите из другой папки")
        item.update(status="failed", message=message)
        return item
    item["method"] = method
    item["status"] = "refreshed" if replaced else "linked"
    if method == "copy":
        item["message"] = ("ссылку создать не удалось, поставлена копия. Обновлять её "
                           "повторным запуском install.py --update")
        if attempts:
            item["message"] += " (" + "; ".join(attempts) + ")"
    else:
        item["message"] = "подключено (%s)" % method
    if leftover:
        item["message"] += ("; старую версию удалить не удалось — удалите папку %s сами"
                            % leftover)
    return item


# ---------- обновление клона ----------

def normalize_origin(url):
    """https://github.com/a/b(.git)(/), git@github.com:a/b(.git), ssh://git@github.com/a/b
    → «github.com/a/b» в нижнем регистре (GitHub к регистру не чувствителен)."""
    url = (url or "").strip()
    lowered = url.lower()
    for prefix in ("https://", "http://", "ssh://", "git://"):
        if lowered.startswith(prefix):
            url = url[len(prefix):]
            break
    else:
        if "@" in url.split("/", 1)[0] and ":" in url:
            url = url.replace(":", "/", 1)  # scp-вид: git@github.com:a/b
    url = url.split("@", 1)[-1] if "@" in url.split("/", 1)[0] else url
    url = url.rstrip("/")
    if url.lower().endswith(".git"):
        url = url[:-4]
    return url.lower()


def git_update(repo):
    git = _find_program("git")
    if git is None:
        return {"status": "skipped", "message": "git не найден; обновите папку вручную"}
    code, out, _ = _run([git, "-C", str(repo), "rev-parse", "--is-inside-work-tree"])
    if code != 0 or out.strip() != "true":
        return {"status": "skipped", "message": "папка не git-клон (например, из zip); "
                "скачайте новый архив и запустите install.py --update из него"}
    _, origin, _ = _run([git, "-C", str(repo), "remote", "get-url", "origin"])
    _, branch, _ = _run([git, "-C", str(repo), "symbolic-ref", "--short", "HEAD"])
    _, dirty, _ = _run([git, "-C", str(repo), "status", "--porcelain"])
    if normalize_origin(origin) != normalize_origin(OFFICIAL_ORIGIN) \
            or branch.strip() != OFFICIAL_BRANCH:
        return {"status": "blocked", "message": "клон не официальный или не на ветке main; "
                "ничего не сделано"}
    if dirty.strip():
        return {"status": "blocked", "message": "в клоне есть локальные изменения; ничего "
                "не сброшено. Перенесите свои файлы из клона и повторите"}
    for argv in (["pull", "--ff-only", "origin", OFFICIAL_BRANCH], ["fetch", "--tags", "origin"]):
        code, out, err = _run([git, "-C", str(repo)] + argv, timeout=300)
        if code != 0:
            return {"status": "failed", "message": "git %s: %s" % (" ".join(argv),
                                                                   (err or out).strip())}
    _, tag, _ = _run([git, "-C", str(repo), "describe", "--tags", "--exact-match", "HEAD"])
    return {"status": "updated", "message": "клон обновлён", "tag": tag.strip() or None}


# ---------- зависимости ----------

def _which(name):
    found = _find_program(name)
    if found or not _is_windows():
        return found
    links = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links"
    candidate = links / (name + ".exe")
    return str(candidate) if os.environ.get("LOCALAPPDATA") and candidate.is_file() else None


def _install_argv(kind, group, command):
    """argv с полным путём к winget/brew или (None, причина)."""
    if kind == "windows":
        winget = _find_program("winget")
        if winget is None:
            return None, "winget не найден (установите «Установщик приложений» из Microsoft Store)"
        return [winget] + command.split()[1:] + WINGET_FLAGS, None
    if kind == "macos":
        brew = _find_program("brew")
        if brew is None:
            return None, "Homebrew не найден: https://brew.sh/"
        return [brew] + command.split()[1:], None
    return None, "на Linux ставьте сами командой выше (нужен sudo)"


def _run_installer(kind, argv, command):
    """(ok, статус, сообщение); статус installed | timeout | failed."""
    code, out, err = _run(argv, timeout=INSTALL_TIMEOUT)
    if code == 0:
        return True, "installed", ""
    if code == TIMEOUT_CODE:
        why = ("установщик не завершился за %d мин и остановлен — возможно, ждал "
               "подтверждения. Поставьте вручную в обычном терминале: %s"
               % (INSTALL_TIMEOUT // 60, command))
        return False, "timeout", why
    why = "%s (код %s)" % ((err or out).strip()[-400:] or "установщик завершился с ошибкой", code)
    if kind == "windows":
        why += ("; если Windows спрашивала разрешение администратора (UAC) и оно не дано — "
                "поставьте вручную: %s" % command)
    return False, "failed", why


def check_deps(kind, install):
    report, done = [], {}
    for name, purpose, group, commands in DEPS:
        path = _which(name)
        item = {"name": name, "purpose": purpose, "found": bool(path), "path": path,
                "install_cmd": commands[kind], "installed": None, "install_status": None,
                "message": ""}
        if not path and install and group is not None:
            if group not in done:
                argv, why = _install_argv(kind, group, commands[kind])
                if argv is None:
                    done[group] = (False, "unavailable", why)
                else:
                    done[group] = _run_installer(kind, argv, commands[kind])
            ok, status, why = done[group]
            item["installed"] = ok
            item["install_status"] = status
            item["path"] = _which(name)
            item["found"] = bool(item["path"])
            if ok and not item["found"]:
                item["message"] = "установлено; откройте новый терминал, чтобы программа нашлась"
            elif not ok:
                item["message"] = why
        report.append(item)
    return report


# ---------- самопроверка ----------

def self_check(skill_dir):
    py, scripts = sys.executable, skill_dir / "scripts"
    checks = []

    def record(name, argv, parse_json=False):
        code, out, err = _run(argv, cwd=str(skill_dir), timeout=120)
        ok, detail = code == 0, ""
        if ok and parse_json:
            try:
                json.loads(out)
            except ValueError:
                ok, detail = False, "вывод не JSON"
        if not ok and not detail:
            detail = (err or out).strip()[-600:] or "код %s" % code
        checks.append({"name": name, "ok": ok, "detail": detail})
        return out

    record("import studio", [py, "-c", "import studio, studio.server, studio.authoring"])
    record("creator_studio.py --help", [py, str(scripts / "creator_studio.py"), "--help"])
    record("detect_tools.py --json", [py, str(scripts / "detect_tools.py"), "--json"], True)
    temp = tempfile.mkdtemp(prefix="aimaster-check-")
    try:
        workspace = Path(temp) / "Проверка aimaster"
        record("workspace init", [py, str(scripts / "creator_studio.py"), "workspace", "init",
                                  str(workspace)], True)
    finally:
        shutil.rmtree(temp, ignore_errors=True)
    return checks


# ---------- вывод ----------

STATUS_WORDS = {"linked": "подключено", "already": "уже на месте", "refreshed": "обновлено",
                "conflict": "НЕ подключено", "failed": "ОШИБКА, не подключено"}


def render_text(report):
    lines = []
    if report.get("update"):
        lines.append("Обновление клона: %s" % report["update"]["message"])
    lines.append("Навык aimaster %s — %s" % (report["version"], report["skill_dir"]))
    for item in report["targets"]:
        lines.append("  %s: %s — %s" % (item["label"], STATUS_WORDS.get(item["status"],
                     item["status"]), item["path"]))
        if item["message"]:
            lines.append("      " + item["message"])
    lines.append("Программы (необязательные):")
    for dep in report["deps"]:
        mark = "есть" if dep["found"] else "нет"
        line = "  %s — %s (%s)" % (dep["name"], mark, dep["purpose"])
        if not dep["found"]:
            line += "; поставить: " + dep["install_cmd"]
        lines.append(line)
        if dep["message"]:
            lines.append("      " + dep["message"])
    if report.get("montage") is not None:
        import install_montage
        lines.extend(install_montage.render_montage_lines(report["montage"]))
    if report["self_check"] is not None:
        bad = [c for c in report["self_check"] if not c["ok"]]
        lines.append("Самопроверка: %s" % ("всё в порядке" if not bad else "ОШИБКИ"))
        for check in bad:
            lines.append("  %s: %s" % (check["name"], check["detail"]))
    lines.append("Команда Python на этой машине (python_cmd): %s" % report["python_cmd"])
    lines.append("Готово." if report["ok"] else "Установка не завершена — см. сообщения выше.")
    for step in report["next_steps"]:
        lines.append("  • " + step)
    return "\n".join(lines)


def too_old_python(kind, as_json):
    have = ".".join(str(part) for part in _version_info())
    command = PYTHON_INSTALL[kind]
    if as_json:
        print(json.dumps({"ok": False, "error": "python_too_old", "python": have,
                          "required": "3.11", "install_cmd": command}, ensure_ascii=False))
    else:
        print("Нужен Python 3.11 или новее, а запущен %s." % have)
        print("Поставьте его командой:  %s" % command)
        if kind == "windows":
            print("Затем закройте и снова откройте терминал и запустите: "
                  "py -3 skills\\aimaster\\scripts\\install.py")
    return 2


def default_repo():
    """Клон, из которого запущен файл; для установленной копии — из её пометки."""
    skill = Path(__file__).resolve().parents[1]
    marker = skill / MARKER
    if marker.is_file():
        try:
            return Path(json.loads(marker.read_text(encoding="utf-8"))["source"]).parents[1]
        except (OSError, ValueError, KeyError, IndexError):
            pass
    return skill.parents[1]


def _montage_report(kind, install_deps, update, home):
    """Раздел montage отчёта. Модуль импортируется здесь, а не в начале файла:
    install_montage.py написан для Python 3.11+, а проверка версии — в main.

    Неожиданная ошибка внутри монтажа (сеть, повреждённый кеш, что угодно) не
    должна ронять всю установку: подключение навыка и остальные разделы
    отчёта обязаны напечататься. Ожидаемые сбои (таймаут npm, битый файл и
    т.п.) уже приходят статусом из montage_report — сюда попадают только
    непредвиденные исключения."""
    import install_montage
    try:
        return install_montage.montage_report(kind, install_missing=install_deps, update=update,
                                              install_node=install_deps, home=home)
    except Exception as error:  # noqa: BLE001 — намеренно широкий предохранитель
        return {"ok": False, "error": _short_error(error)}


def _montage_next_step(montage):
    """Что дописать в next_steps, если монтаж не готов — называет реальный
    затор, а не слепо повторяет --install-deps там, где это не поможет
    (например, на Linux без Node.js установщик его сам не ставит)."""
    if montage.get("error"):
        return "Монтаж не готов: %s" % montage["error"]
    node = montage.get("node") or {}
    if node.get("status") not in ("found", "installed"):
        blocker = node.get("message") or "нужен Node.js 22+"
        return "Монтаж не готов: %s" % blocker
    return ("Монтаж не готов — повторите: install.py --install-deps "
            "(подробности в разделе «Монтаж» выше)")


def build_parser():
    parser = argparse.ArgumentParser(description="Установить навык aimaster для агентов.")
    parser.add_argument("--repo", help="папка клона aimaster (по умолчанию — та, где лежит этот файл)")
    parser.add_argument("--agent", choices=("all", "claude", "codex"), default="all",
                        help="куда подключать навык (по умолчанию — всем)")
    parser.add_argument("--update", action="store_true",
                        help="обновить клон через git (если это безопасно), переписать копии и "
                             "перевести уже стоящий монтажный движок/GSAP/браузер/кеш скиллов на "
                             "закреплённую версию; без --install-deps ничего не ставит заново")
    parser.add_argument("--force", action="store_true",
                        help="заменить свою старую ссылку или копию aimaster (чужое не трогается)")
    parser.add_argument("--install-deps", action="store_true",
                        help="поставить недостающие ffmpeg, cloudflared, git (winget/brew), "
                             "Node.js 22+ и монтажный движок HyperFrames")
    parser.add_argument("--skip-self-check", action="store_true", help="не запускать самопроверку")
    parser.add_argument("--json", action="store_true", help="вывод JSON для агента")
    parser.add_argument("--print-python-cmd", action="store_true",
                        help="только напечатать python_cmd, ничего не устанавливать")
    parser.add_argument("--home", help=argparse.SUPPRESS)
    return parser


def main(argv=None):
    ensure_utf8_output()
    args = build_parser().parse_args(argv)
    kind = platform_kind()
    if _version_info() < MIN_PYTHON:
        return too_old_python(kind, args.json)
    if args.print_python_cmd:
        command = python_cmd()
        print(json.dumps({"python_cmd": command}, ensure_ascii=False) if args.json else command)
        return 0
    repo = Path(args.repo).expanduser() if args.repo else default_repo()
    repo = repo.resolve()
    source = repo / "skills" / "aimaster"
    if not _looks_like_aimaster(source):
        message = "В %s нет skills/aimaster/SKILL.md — укажите клон через --repo" % repo
        print(json.dumps({"ok": False, "error": "repo_not_found", "message": message},
                         ensure_ascii=False) if args.json else message)
        return 3
    report = {"ok": True, "platform": kind, "repo": str(repo), "skill_dir": str(source),
              "python": {"version": ".".join(str(p) for p in _version_info()),
                         "executable": sys.executable}}
    if args.update:
        report["update"] = git_update(repo)
    version_file = source / "VERSION"
    report["version"] = version_file.read_text(encoding="utf-8").strip() if version_file.is_file() else "?"
    # абсолютный путь: при замене копии процесс может сменить текущую папку
    # (abspath, не resolve: путь в отчёте остаётся тем, что дал пользователь)
    home = Path(os.path.abspath(str(Path(args.home).expanduser() if args.home else Path.home())))
    report["targets"] = [
        install_target(agent, label, home.joinpath(*parts) / "aimaster", source,
                       report["version"], args.force, args.update)
        for agent, label, parts in AGENT_DIRS if args.agent in ("all", agent)]
    report["deps"] = check_deps(kind, args.install_deps)
    report["montage"] = _montage_report(kind, args.install_deps, args.update, home)
    report["self_check"] = None if args.skip_self_check else self_check(source)
    report["python_cmd"] = python_cmd()
    failed = [t for t in report["targets"] if t["status"] in ("conflict", "failed")]
    failed += [c for c in (report["self_check"] or []) if not c["ok"]]
    if report.get("update", {}).get("status") in ("blocked", "failed"):
        failed.append(report["update"])
    report["ok"] = not failed
    report["next_steps"] = [
        "Во всех командах навыка вместо python3 используйте: %s" % report["python_cmd"],
        "Откройте новый чат: в Claude Code напишите /aimaster, в Codex — $aimaster",
    ]
    if any(t["method"] == "copy" for t in report["targets"]):
        report["next_steps"].append("Навык стоит копией: после обновления клона запускайте "
                                    "install.py --update")
    if not report["montage"].get("ok"):
        report["next_steps"].append(_montage_next_step(report["montage"]))
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else render_text(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
