#!/usr/bin/env python3
"""Node.js 22+ для монтажа: найти, при --install-deps поставить (winget/brew) и
найти npm-cli.js рядом с этим Node — npm потом запускается как `node <npm-cli.js>`,
без npm.cmd и оболочки. Часть установщика монтажа (install_montage.py)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
for _path in (str(_SCRIPTS), str(_SCRIPTS.parent)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import install  # noqa: E402
from studio.montage import engine  # noqa: E402

NODE_INSTALL = {"windows": "winget install -e --id OpenJS.NodeJS.LTS",
                "macos": "brew install node", "linux": "sudo apt install nodejs"}
LINUX_NODE_HINT = ("в apt часто Node.js старее 22 — тогда поставьте 22+ по инструкции "
                   "https://nodejs.org/en/download")
READY = ("found", "installed")


def item(status: str, message: str = "", **extra) -> dict:
    return {"status": status, "message": message, **extra}


def node_check(kind: str, install_missing: bool) -> dict:
    wanted = engine.load_pin()["node_min_major"]
    node = engine.find_node()
    major = engine.node_major(node) if node else None
    if node and major and major >= wanted:
        return item("found", path=node, version=major)
    command = NODE_INSTALL[kind]
    why = "не найден" if not node else f"версии {major}, нужна {wanted}+"
    if not install_missing:
        return item("missing", f"Node.js {why}; поставить: {command}", path=node,
                     version=major, install_cmd=command)
    argv, reason = install._install_argv(kind, "node", command)
    if argv is None:
        hint = f"{reason}. {LINUX_NODE_HINT}" if kind == "linux" else reason
        return item("missing", hint, path=node, version=major, install_cmd=command)
    ok, status, reason = install._run_installer(kind, argv, command)
    if not ok:
        return item(status, reason, install_cmd=command)
    node = engine.find_node()
    major = engine.node_major(node) if node else None
    if node and major and major >= wanted:
        return item("installed", path=node, version=major)
    return item("failed", f"установщик отработал, но Node.js {wanted}+ не виден: откройте новый "
                 f"терминал и повторите или поставьте вручную: {command}", install_cmd=command)


def npm_cli_js(node: str) -> Path | None:
    """npm-cli.js рядом с этим Node: Windows, tar.gz/nvm/setup-node, Homebrew."""

    here = Path(node).parent
    real = Path(os.path.realpath(node)).parent
    tail = Path("node_modules") / "npm" / "bin" / "npm-cli.js"
    candidates = [here / tail, real.parent / "lib" / tail, here.parent / "lib" / tail]
    for npm in (here / "npm", real / "npm"):
        resolved = Path(os.path.realpath(npm))
        if resolved.suffix == ".js":
            candidates.append(resolved)
    return next((path for path in candidates if path.is_file()), None)
