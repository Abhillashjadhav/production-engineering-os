"""CLI entry point for the local guided PMOS web experience."""

from __future__ import annotations

import argparse
import ipaddress
from pathlib import Path

from pmpe.domain.errors import SpecError
from pmpe.guided.server import serve


def _cmd_serve(args: argparse.Namespace) -> int:
    address = ipaddress.ip_address(args.host)
    if not address.is_loopback:
        raise SpecError("guided local mode is loopback-only")
    serve(Path(args.workspace), args.host, args.port)
    return 0


def register(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    guided = sub.add_parser("guided", help="run the connector-free guided PMOS experience")
    commands = guided.add_subparsers(dest="guided_command", required=True)
    run = commands.add_parser("serve", help="serve the mobile-first local PMOS interface")
    run.add_argument("--workspace", default=".pmpe-guided")
    run.add_argument("--host", default="127.0.0.1")
    run.add_argument("--port", type=int, default=8765)
    run.set_defaults(fn=_cmd_serve)
