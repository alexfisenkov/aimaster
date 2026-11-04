#!/usr/bin/env python3
"""Run the repository's existing offline checks without installing anything.

Full: python3 skills/aimaster/scripts/check_project.py
Targeted: python3 skills/aimaster/scripts/check_project.py --test test_library.py
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", help="run one test_*.py file, plus compile and whitespace checks")
    args = parser.parse_args(argv)
    if args.test and (Path(args.test).name != args.test or not args.test.startswith("test_") or not args.test.endswith(".py")):
        parser.error("--test must be a test_*.py basename")
    root = Path(__file__).resolve().parents[3]
    scripts = "skills/aimaster/scripts"
    if args.test and not (root / scripts / args.test).is_file():
        parser.error("requested test file does not exist")
    commands = [
        [sys.executable, "-m", "unittest", "discover", "-s", scripts, "-p", args.test or "test_*.py"],
        [sys.executable, "-m", "compileall", "-q", "skills/aimaster"],
    ]
    if not args.test:
        commands.extend([
            ["node", "--experimental-vm-modules", "--no-warnings", scripts + "/check_static_modules.mjs"],
            ["node", "--test", *[str(path.relative_to(root)) for path in sorted(
                (root / "skills/aimaster/studio/static/ui/v2").glob("*.test.mjs"))]],
        ])
    commands.append(["git", "diff", "--check"])
    failures = []
    for command in commands:
        print("CHECK:", " ".join(command), flush=True)
        try:
            result = subprocess.run(command, cwd=root, check=False)
            code = result.returncode
        except OSError as error:
            print(f"Could not start {command[0]}: {type(error).__name__}", file=sys.stderr)
            code = 127
        print(f"EXIT: {code}", flush=True)
        if code:
            failures.append(command)
    print(f"Checks: {len(commands) - len(failures)} passed, {len(failures)} failed", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
