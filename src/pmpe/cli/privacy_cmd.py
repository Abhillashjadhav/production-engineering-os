"""Operational privacy commands designed for an external periodic scheduler."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pmpe.domain.errors import PmpeError
from pmpe.privacy.retention import purge_retained_runs


def _purge(args: argparse.Namespace) -> int:
    root = Path(args.runs_root)
    try:
        result = purge_retained_runs(root)
    except ValueError as exc:
        raise PmpeError(str(exc)) from exc
    print(
        json.dumps(
            {
                "deleted": list(result.deleted),
                "retained": list(result.retained),
                "runs_root": str(root.resolve()),
            },
            sort_keys=True,
        )
    )
    return 0


def register(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    retention = sub.add_parser(
        "retention",
        help="run privacy retention independently (schedule this command periodically)",
    )
    commands = retention.add_subparsers(dest="retention_command", required=True)
    purge = commands.add_parser("purge", help="delete expired terminal runs")
    purge.add_argument("--runs-root", required=True)
    purge.set_defaults(fn=_purge)
