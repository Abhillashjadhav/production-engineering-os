"""Optional observation only; PEOS dispatch and quality gates remain authoritative."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import import_module
from pathlib import Path
from typing import Any


@contextmanager
def observe_command(args: argparse.Namespace) -> Iterator[Any]:
    """Never replay work or suppress a task exception when observation fails."""
    context = None
    recording = None
    failure: tuple[Any, Any, Any] = (None, None, None)
    try:
        capture = import_module("workflow_beacon").capture

        root = getattr(args, "repository_root", None) or Path.cwd()
        context = capture("peos", project_root=root)
        recording = context.__enter__()
    except Exception:
        context = None
    try:
        yield recording
    except BaseException:
        failure = sys.exc_info()
        raise
    finally:
        if context is not None:
            try:
                context.__exit__(*failure)
            except Exception:
                pass


def record_result(recording: Any, result: int) -> None:
    if recording is not None:
        try:
            recording.set_result(result)
        except Exception:
            pass
