#!/usr/bin/env python3
"""List MCP servers configured for local AI agents, without network access.

Reads Claude Code, Codex, Gemini CLI and Cursor configuration files plus the
aimaster provider preferences. Prints only server names, transport types,
URL hosts and the source file. Never prints env/header values, tokens,
command arguments or full URLs. A broken file is skipped with a note.

A configured server is not proof that the current chat session exposes it,
and a missing entry is not proof that no tool exists (hosted connectors are
not stored in these files). See references/autopilot.md, "Tool check".
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

_SKILL_ROOT = Path(__file__).resolve().parent.parent
if str(_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ROOT))

from studio.platform_compat import IS_WINDOWS, ensure_utf8_stdio, user_config_dir  # noqa: E402

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    tomllib = None

MAX_BYTES = 20 * 1024 * 1024

# provider id -> tokens matched against server names, URL hosts, package names
# and environment variable *names* (values are never read into the output).
PROVIDERS: dict[str, tuple[str, ...]] = {
    "higgsfield": ("higgsfield",),
    "magnific": ("magnific", "freepik"),
    "syntx": ("syntx",),
    "fal": ("fal",),
    "replicate": ("replicate",),
    "elevenlabs": ("elevenlabs", "eleven"),
    "kling": ("kling", "klingai"),
    "runway": ("runway", "runwayml"),
    "luma": ("luma", "lumalabs"),
    "openai": ("openai",),
    "google": ("gemini", "vertex", "imagen", "veo", "generativelanguage", "aiplatform"),
    "minimax": ("minimax", "minimaxi"),
    "hailuo": ("hailuo", "hailuoai"),
    "pika": ("pika", "pikalabs"),
}

ENV_TITLES = {
    "claude_code": "Claude Code",
    "codex": "Codex",
    "gemini": "Gemini CLI",
    "cursor": "Cursor",
}

DOC_TOKENS = {"docs", "doc", "documentation"}

PACKAGE_RE = re.compile(r"^(@[\w.-]+/)?[\w.-]+(@[\w.^~<>=-]+)?$")


def words(text: str) -> set[str]:
    parts = {w for w in re.split(r"[^a-z0-9]+", text.lower()) if w}
    return parts | {text.lower()}


def match_providers(tokens: set[str]) -> set[str]:
    found = set()
    for pid, names in PROVIDERS.items():
        for token in tokens:
            for name in names:
                if token == name or (len(name) >= 6 and name in token):
                    found.add(pid)
    return found


def safe_host(url: object) -> str | None:
    if not isinstance(url, str):
        return None
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return None
    if not host or "$" in host or "{" in host:
        return None
    return host


def short(path: Path, home: Path) -> str:
    try:
        return "~/" + path.relative_to(home).as_posix()
    except ValueError:
        return str(path)


def read_file(path: Path, kind: str):
    """Return (data, error). error is a short class name, never file content."""
    try:
        if not path.is_file():
            return None, None
        if path.stat().st_size > MAX_BYTES:
            return None, "file too large"
        raw = path.read_bytes()
    except OSError as exc:
        return None, type(exc).__name__
    try:
        if kind == "toml":
            if tomllib is None:
                return None, "tomllib unavailable (Python 3.11+ required)"
            return tomllib.loads(raw.decode("utf-8")), None
        return json.loads(raw.decode("utf-8")), None
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        return None, "invalid " + kind.upper() + " (" + type(exc).__name__ + ")"


def server_type(cfg: dict) -> str:
    declared = str(cfg.get("type") or cfg.get("transport") or "").lower()
    if declared in ("sse",):
        return "sse"
    if declared in ("http", "streamable-http", "streamable_http", "streamablehttp"):
        return "http"
    if declared == "stdio" or cfg.get("command"):
        return "stdio"
    if cfg.get("httpUrl"):
        return "http"
    url = cfg.get("url") or cfg.get("serverUrl")
    if isinstance(url, str):
        try:
            path = urlsplit(url).path
        except ValueError:  # malformed URL; never echo it (it may carry userinfo)
            return "http"
        return "sse" if path.rstrip("/").endswith("/sse") else "http"
    return "unknown"


def describe(name: str, cfg: object, source: str) -> dict:
    cfg = cfg if isinstance(cfg, dict) else {}
    host = safe_host(cfg.get("httpUrl") or cfg.get("url") or cfg.get("serverUrl"))
    tokens = words(name)
    if tokens & DOC_TOKENS:
        # documentation servers (e.g. "openai-docs") do not generate media
        return {"name": name, "type": server_type(cfg), "source": source,
                **({"host": host} if host else {})}
    matched_by = {pid: "name" for pid in match_providers(tokens)}
    if host:
        for pid in match_providers(words(host)):
            matched_by.setdefault(pid, "host")
    cmd_tokens: set[str] = set()
    command = cfg.get("command")
    if isinstance(command, str):
        cmd_tokens |= words(Path(command).name)
    args = cfg.get("args")
    if isinstance(args, list):
        for arg in args:
            if not isinstance(arg, str) or len(arg) > 100:
                continue
            arg_host = safe_host(arg) if "://" in arg else None
            if arg_host:
                cmd_tokens |= words(arg_host)
            elif PACKAGE_RE.match(arg) and not arg.startswith("-"):
                cmd_tokens |= words(arg)
    for pid in match_providers(cmd_tokens):
        matched_by.setdefault(pid, "package")
    env = cfg.get("env")
    if isinstance(env, dict):
        env_tokens = set()
        for key in env:
            if isinstance(key, str):
                env_tokens |= words(key)
        for pid in match_providers(env_tokens):
            matched_by.setdefault(pid, "env-name")
    entry = {"name": name, "type": server_type(cfg), "source": source}
    if host:
        entry["host"] = host
    if cfg.get("disabled") is True or cfg.get("enabled") is False:
        entry["disabled"] = True
    if matched_by:
        entry["providers"] = dict(sorted(matched_by.items()))
    return entry


def servers_from(mapping: object, source: str, prefix: str = "") -> list[dict]:
    if not isinstance(mapping, dict):
        return []
    return [
        describe(prefix + str(name), cfg, source)
        for name, cfg in mapping.items()
        if isinstance(cfg, dict)
    ]


def mcp_json_servers(data: object) -> object:
    if isinstance(data, dict) and isinstance(data.get("mcpServers"), dict):
        return data["mcpServers"]
    if isinstance(data, dict) and data and all(
        isinstance(v, dict) and ("command" in v or "url" in v or "type" in v)
        for v in data.values()
    ):
        return data
    return {}


def ancestors(cwd: Path) -> list[Path]:
    seen, result = set(), []
    for base in (cwd.absolute(), cwd.resolve()):
        for path in (base, *base.parents):
            if path not in seen:
                seen.add(path)
                result.append(path)
    return result


class Collector:
    def __init__(self, home: Path):
        self.home = home
        self.envs = {key: {"servers": [], "files": [], "errors": []} for key in ENV_TITLES}

    def load(self, env: str, path: Path, kind: str = "json"):
        data, error = read_file(path, kind)
        label = short(path, self.home)
        if error:
            self.envs[env]["errors"].append({"file": label, "error": error})
            return None, label
        if data is not None:
            self.envs[env]["files"].append(label)
        return data, label

    def add(self, env: str, servers: list[dict]):
        self.envs[env]["servers"].extend(servers)


def plugin_mcp_files(plugins: Path) -> list[tuple[str, Path]]:
    installed: dict[Path, str] = {}
    data, _ = read_file(plugins / "installed_plugins.json", "json")
    records = data.get("plugins") if isinstance(data, dict) else None
    if isinstance(records, dict):
        for key, entries in records.items():
            name = str(key).split("@", 1)[0]
            for entry in entries if isinstance(entries, list) else [entries]:
                if isinstance(entry, dict) and isinstance(entry.get("installPath"), str):
                    installed[Path(entry["installPath"])] = name
    found: dict[Path, str] = {}
    for base, name in installed.items():
        if (base / ".mcp.json").is_file():
            found[base / ".mcp.json"] = name
    if plugins.is_dir():
        for path in sorted(plugins.rglob(".mcp.json")):
            rel = path.relative_to(plugins).parts
            if not rel or rel[0] in (".trash", "marketplaces") or path in found:
                continue
            if rel[0] == "cache" and installed:
                continue  # cached but not installed
            parent = path.parent.name
            if rel[0] == "cache" and len(rel) >= 4:
                parent = rel[2]
            found[path] = parent.split("~", 1)[0]
    return sorted(((name, path) for path, name in found.items()), key=lambda x: str(x[1]))


def collect(home: Path, cwd: Path, env_vars: dict[str, str]) -> dict:
    col = Collector(home)

    data, label = col.load("claude_code", home / ".claude.json")
    if isinstance(data, dict):
        col.add("claude_code", servers_from(data.get("mcpServers"), label))
        projects = data.get("projects")
        if isinstance(projects, dict):
            for folder in ancestors(cwd):
                cfg = projects.get(str(folder))
                if isinstance(cfg, dict):
                    col.add("claude_code", servers_from(
                        cfg.get("mcpServers"), label + " projects[" + str(folder) + "]"))
    for folder in ancestors(cwd):
        data, label = col.load("claude_code", folder / ".mcp.json")
        col.add("claude_code", servers_from(mcp_json_servers(data), label))
    for plugin, path in plugin_mcp_files(home / ".claude" / "plugins"):
        data, label = col.load("claude_code", path)
        col.add("claude_code", servers_from(mcp_json_servers(data), label, "plugin:" + plugin + ":"))

    codex_home = Path(env_vars["CODEX_HOME"]) if env_vars.get("CODEX_HOME") else home / ".codex"
    data, label = col.load("codex", codex_home / "config.toml", "toml")
    if isinstance(data, dict):
        col.add("codex", servers_from(data.get("mcp_servers"), label))

    data, label = col.load("gemini", home / ".gemini" / "settings.json")
    if isinstance(data, dict):
        col.add("gemini", servers_from(data.get("mcpServers"), label))

    data, label = col.load("cursor", home / ".cursor" / "mcp.json")
    col.add("cursor", servers_from(mcp_json_servers(data), label))

    return {
        "schema_version": 1,
        "environments": col.envs,
        "aimaster_preferences": read_preferences(home, env_vars),
        "providers": summarize(col.envs),
        "note": "Configured is not the same as exposed in this chat; "
                "hosted connectors are not in these files. Verify with the "
                "session tool list and a free probe call.",
    }


def read_preferences(home: Path, env_vars: dict[str, str]) -> dict:
    # ~/.config/aimaster (or $XDG_CONFIG_HOME) on macOS/Linux,
    # %APPDATA%\aimaster on Windows, where ~/.config/aimaster still counts.
    path = user_config_dir(home=home, environ=env_vars) / "preferences.json"
    if IS_WINDOWS and not path.exists():
        xdg = env_vars.get("XDG_CONFIG_HOME")
        base = Path(xdg) if xdg and Path(xdg).is_absolute() else home / ".config"
        if (base / "aimaster" / "preferences.json").exists():
            path = base / "aimaster" / "preferences.json"
    data, error = read_file(path, "json")
    result: dict = {"file": short(path, home)}
    if error:
        result["status"] = "error"
        result["error"] = error
        return result
    if data is None:
        result["status"] = "absent"
        return result
    if not isinstance(data, dict):
        result["status"] = "error"
        result["error"] = "unexpected shape"
        return result
    result["status"] = "ok"
    preferred = data.get("preferred_provider_id")
    result["preferred_provider_id"] = preferred if isinstance(preferred, str) else None
    providers = []
    raw_providers = data.get("providers")
    for item in raw_providers if isinstance(raw_providers, list) else []:
        if not isinstance(item, dict):
            continue
        caps = item.get("declared_capabilities")
        providers.append({
            "id": str(item.get("id", ""))[:80],
            "name": str(item.get("name", ""))[:80],
            "transport": str(item.get("transport", ""))[:40],
            "declared_capabilities": [str(c)[:40] for c in caps] if isinstance(caps, list) else [],
        })
    result["providers"] = providers
    return result


def summarize(envs: dict) -> dict:
    summary: dict[str, list] = {}
    for env, info in envs.items():
        for server in info["servers"]:
            for pid, how in server.get("providers", {}).items():
                summary.setdefault(pid, []).append(
                    {"environment": env, "server": server["name"], "matched_by": how})
    return dict(sorted(summary.items()))


def render_text(report: dict) -> str:
    lines = ["Подключения MCP в конфигурациях (без сети, значения ключей не читаются)", ""]
    for env, info in report["environments"].items():
        title = ENV_TITLES[env]
        if not info["files"] and not info["errors"]:
            lines.append(title + ": конфигурация не найдена")
            continue
        lines.append(title + ": серверов " + str(len(info["servers"])))
        for s in info["servers"]:
            extra = " · " + s["host"] if s.get("host") else ""
            off = " · выключен" if s.get("disabled") else ""
            lines.append("  - " + s["name"] + " [" + s["type"] + extra + off + "] ← " + s["source"])
        for err in info["errors"]:
            lines.append("  ! пропущен " + err["file"] + ": " + err["error"])
    prefs = report["aimaster_preferences"]
    lines.append("")
    status = {"ok": "прочитаны", "absent": "файла нет", "error": "ошибка"}[prefs["status"]]
    lines.append("Предпочтения aimaster (" + prefs["file"] + "): " + status)
    if prefs.get("error"):
        lines.append("  ! " + prefs["error"])
    for p in prefs.get("providers", []):
        mark = " (основной)" if p["id"] == prefs.get("preferred_provider_id") else ""
        lines.append("  - " + (p["name"] or p["id"]) + mark)
    lines.append("")
    if report["providers"]:
        lines.append("Провайдеры генерации, видимые по конфигурации:")
        for pid, hits in report["providers"].items():
            where = ", ".join(ENV_TITLES[h["environment"]] + ": " + h["server"] for h in hits)
            lines.append("  - " + pid + " — " + where)
    else:
        lines.append("Провайдеры генерации по конфигурации не распознаны.")
    lines.append("")
    lines.append("Наличие в конфиге не значит, что сервер виден в этом чате; облачные "
                 "коннекторы в эти файлы не попадают. Проверь список инструментов "
                 "сессии и сделай бесплатный пробный вызов.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ensure_utf8_stdio()
    parser = argparse.ArgumentParser(description="List configured MCP servers without secrets.")
    parser.add_argument("--json", action="store_true", help="print JSON instead of Russian text")
    parser.add_argument("--cwd", default=os.getcwd(), help="folder whose project configs to read")
    parser.add_argument("--home", default=None, help="home directory to read (for tests)")
    args = parser.parse_args(argv)
    home = Path(args.home) if args.home else Path.home()
    env_vars = {} if args.home else dict(os.environ)
    try:
        report = collect(home.absolute(), Path(args.cwd), env_vars)
    except Exception as exc:  # noqa: BLE001 - never print a message or traceback: they may hold secrets
        print(f"detect_tools: internal error ({type(exc).__name__})", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_text(report))
    envs = report["environments"].values()
    read_any = any(info["files"] for info in envs) or report["aimaster_preferences"]["status"] == "ok"
    failed_any = any(info["errors"] for info in envs) or report["aimaster_preferences"]["status"] == "error"
    return 1 if failed_any and not read_any else 0


if __name__ == "__main__":
    sys.exit(main())
