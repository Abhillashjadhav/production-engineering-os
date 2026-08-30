#!/usr/bin/env python3
"""Execute an admitted security entrypoint without ambient candidate startup hooks."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import runpy
import sys
from pathlib import Path

_ENTRYPOINTS = {
    "scripts/ci/evaluate_security_profile.py",
    "scripts/ci/verify_privacy_controls.py",
    "scripts/ci/verify_repository_secrets.py",
}


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _admitted_runner(report_path: Path) -> Path:
    value = json.loads(report_path.read_text())
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != "trusted-security-admission/v1"
    ):
        raise ValueError("trusted security admission report is malformed")
    claimed = value.get("report_digest")
    shell = dict(value)
    shell.pop("report_digest", None)
    if not isinstance(claimed, str) or _canonical_digest(shell) != claimed:
        raise ValueError("trusted security admission report digest is invalid")
    runner = value.get("runner_root")
    if not isinstance(runner, str):
        raise ValueError("trusted security runner root is missing")
    path = Path(runner).resolve()
    if not path.is_dir():
        raise ValueError("trusted security runner root is unavailable")
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--admission-report", type=Path, required=True)
    parser.add_argument("--entrypoint", choices=sorted(_ENTRYPOINTS), required=True)
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    runner = _admitted_runner(args.admission_report)
    entrypoint = runner / args.entrypoint
    if entrypoint.is_symlink() or not entrypoint.is_file():
        raise ValueError("trusted security entrypoint is unavailable")
    os.environ["PYTHONNOUSERSITE"] = "1"
    os.environ["PYTHONSAFEPATH"] = "1"
    sys.path.insert(0, str(runner / "src"))
    forwarded = list(args.arguments)
    if forwarded[:1] == ["--"]:
        forwarded = forwarded[1:]
    sys.argv = [str(entrypoint), *forwarded]
    runpy.run_path(str(entrypoint), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
