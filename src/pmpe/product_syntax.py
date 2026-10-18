"""Bounded, trusted Python syntax compiler for sealed candidate source bytes.

The fixed child compiles source as data; it does not execute or import candidate
code. This process limit is a supervisor availability guard, not provider
isolation or a candidate runtime sandbox.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Mapping

_MAX_SOURCE_BYTES = 1_000_000
_MAX_TOTAL_SOURCE_BYTES = 2_000_000
_MAX_FILES = 64
_MAX_WALL_SECONDS = 5.0
_CHILD_SCRIPT = (
    "import os,sys,resource\n"
    "resource.setrlimit(resource.RLIMIT_AS, (268435456,268435456))\n"
    "resource.setrlimit(resource.RLIMIT_CPU, (2,2))\n"
    "resource.setrlimit(resource.RLIMIT_STACK, (8388608,8388608))\n"
    "resource.setrlimit(resource.RLIMIT_FSIZE, (0,0))\n"
    "try:\n"
    " compile(sys.stdin.buffer.read(1000001), '<sealed-source>', 'exec', dont_inherit=True)\n"
    "except (SyntaxError,UnicodeError,RecursionError,MemoryError,ValueError,TypeError):\n"
    " os.write(1,b'1')\n"
    "else:\n"
    " os.write(1,b'0')\n"
)


def check_python_syntax(source_files: Mapping[str, bytes]) -> tuple[str, str]:
    """REV_PYTHON_SYNTAX: return PASS only from the fixed child compiler."""

    python_files = [
        (name, content) for name, content in sorted(source_files.items()) if name.endswith(".py")
    ]
    if not python_files:
        return "BLOCKED", "Python source missing"
    if (
        len(python_files) > _MAX_FILES
        or any(len(content) > _MAX_SOURCE_BYTES for _, content in python_files)
        or sum(len(content) for _, content in python_files) > _MAX_TOTAL_SOURCE_BYTES
        or os.name != "posix"
    ):
        return "BLOCKED", "source syntax resource limit"
    deadline = time.monotonic() + _MAX_WALL_SECONDS
    for _, content in python_files:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return "BLOCKED", "source syntax resource limit"
        try:
            completed = subprocess.run(
                (sys.executable, "-I", "-S", "-B", "-c", _CHILD_SCRIPT),
                input=content,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=remaining,
                check=False,
                env={"LC_ALL": "C", "PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
                start_new_session=True,
            )
        except (subprocess.TimeoutExpired, OSError, ValueError):
            return "BLOCKED", "source syntax resource limit"
        if completed.returncode != 0 or completed.stdout not in {b"0", b"1"}:
            return "BLOCKED", "source syntax resource limit"
        if completed.stdout == b"1":
            return "FAIL", "source syntax invalid"
    return "PASS", "trusted bounded compiler accepted sealed Python source"
