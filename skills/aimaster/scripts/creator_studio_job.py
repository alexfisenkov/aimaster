#!/usr/bin/env python3
"""Apply one typed canonical operation for the exact active operator job."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio.job_authoring import apply_request, JobAuthoringError
from studio.store import RevisionConflict
from studio.platform_compat import ensure_utf8_stdio


def main(argv=None):
    ensure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("action_id")
    parser.add_argument("request_file", type=Path)
    args = parser.parse_args(argv)
    try:
        result = apply_request(args.workspace, args.action_id, args.request_file)
    except RevisionConflict as error:
        result = {"ok": False, "error": {"code": "revision_conflict", "current_revision": error.current_revision}}
    except JobAuthoringError as error:
        result = {"ok": False, "error": {"code": str(error)}}
    except (OSError, ValueError, RuntimeError, TypeError, KeyError):
        result = {"ok": False, "error": {"code": "authoring_refused"}}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
