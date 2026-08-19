"""pmpe — the CLI of PM Production Engineering OS.

Exit codes (part of the contract, see docs/usage.md):
0 success · 1 failure · 2 malformed input · 3 blocked on human gate / semantic
errors / non-runnable contract · 4 completed with NO_MERGE recommendation
"""

from __future__ import annotations

import argparse
import sys

from pmpe.cli import (
    contracts_cmd,
    core,
    demo_cmd,
    eng_cmd,
    evals_cmd,
    guided_cmd,
    personal_cmd,
    repository_cmd,
    support_cmd,
)
from pmpe.domain.errors import PmpeError, SpecError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pmpe",
        description="Convert an approved product decision into tested, "
        "reviewed, deployable software.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    core.register(sub)
    contracts_cmd.register(sub)
    demo_cmd.register(sub)
    eng_cmd.register(sub)
    evals_cmd.register(sub)
    guided_cmd.register(sub)
    personal_cmd.register(sub)
    repository_cmd.register(sub)
    support_cmd.register(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result: int = args.fn(args)
    except SpecError as exc:
        print(f"input rejected:\n{exc}", file=sys.stderr)
        return 2
    except PmpeError as exc:
        print(f"pipeline error: {exc}", file=sys.stderr)
        return 1
    return result


if __name__ == "__main__":
    sys.exit(main())
