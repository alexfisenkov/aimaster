"""Run family seam acceptance without accounts, global installs or paid calls."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parent
FILES = (
    "test_family_acceptance.py", "test_guide_catalog.py", "test_guide_bundle.py",
    "test_family_foundation.py", "test_family_setup.py", "test_family_update.py",
    "test_family_operator.py", "test_operator_repair.py", "test_family_transport.py",
    "test_telegram_transport.py", "test_montage_family.py",
)


def main() -> int:
    for filename in FILES:
        if not (SCRIPTS / filename).is_file():
            print(f"missing test file: {filename}", file=sys.stderr)
            return 2
        result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s",
                                 str(SCRIPTS), "-p", filename], check=False)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
