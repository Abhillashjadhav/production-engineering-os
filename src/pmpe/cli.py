"""pmpe — the CLI of PM Production Engineering OS.

Exit codes (part of the contract): 0 success · 1 failure · 2 malformed specification
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pmpe.config import packaged_schema_path
from pmpe.domain.errors import PmpeError, SpecError
from pmpe.ingestion import ingest


def _cmd_validate(args: argparse.Namespace) -> int:
    schema = Path(args.schema) if args.schema else packaged_schema_path()
    spec = ingest(Path(args.spec), schema)
    print(
        f"specification OK: {spec.product_name} ({len(spec.functional_requirements)} requirements)"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pmpe",
        description="Convert an approved product decision into tested, "
        "reviewed, deployable software.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p_validate = sub.add_parser("validate", help="validate a specification only")
    p_validate.add_argument("spec")
    p_validate.add_argument("--schema", default=None)
    p_validate.set_defaults(fn=_cmd_validate)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result: int = args.fn(args)
    except SpecError as exc:
        print(f"specification rejected:\n{exc}", file=sys.stderr)
        return 2
    except PmpeError as exc:
        print(f"pipeline error: {exc}", file=sys.stderr)
        return 1
    return result


if __name__ == "__main__":
    sys.exit(main())
