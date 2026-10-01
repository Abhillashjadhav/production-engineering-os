#!/usr/bin/env python3
"""Run a standalone command with optional Beacon; missing adapter runs it directly."""
from __future__ import annotations

from importlib import import_module
import os
from pathlib import Path
import sys


def main() -> int:
    command = sys.argv[1:]
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        print("Usage: python scripts/run_with_beacon.py -- COMMAND [ARGUMENTS]", file=sys.stderr)
        return 2
    try:
        adapter_main = import_module("workflow_beacon.cli").main
    except Exception:
        try:
            os.execvp(command[0], command)
        except FileNotFoundError:
            return 127
        except PermissionError:
            return 126
    return adapter_main([
        "run", "--workflow", "peos", "--project-root",
        str(Path(__file__).resolve().parents[1]), "--", *command,
    ])


if __name__ == "__main__":
    raise SystemExit(main())

