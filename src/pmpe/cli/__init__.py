"""pmpe — the CLI of the Production Engineering OS alpha platform.

The default surface exposes only the frozen six-state contract-to-RELEASE_READY
journey. Historical commands remain available under an explicit `legacy` boundary
while their surviving consumers are migrated.
"""

from __future__ import annotations

import argparse
import sys

from pmpe.cli import barebones_cmd
from pmpe.domain.errors import PmpeError, SpecError

_LEGACY_COMMANDS = frozenset(
    {
        "validate",
        "status",
        "report",
        "contract",
        "change-request",
        "demo",
        "eng",
        "evals",
        "drift",
        "full-product",
        "guided",
        "personal-demo",
        "personal-workflows",
        "personal-runtime",
        "repository",
        "support-demo",
    }
)


class PlatformArgumentParser(argparse.ArgumentParser):
    """Keep old invocations working without advertising them as platform paths."""

    def parse_known_args(  # type: ignore[override]
        self,
        args: list[str] | None = None,
        namespace: argparse.Namespace | None = None,
    ) -> tuple[argparse.Namespace, list[str]]:
        values = list(sys.argv[1:] if args is None else args)
        if self.prog == "pmpe" and values and values[0] in _LEGACY_COMMANDS:
            values.insert(0, "legacy")
        return super().parse_known_args(values, namespace)


def _register_legacy(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Register historical commands behind one visibly non-default boundary."""

    from pmpe.cli import (
        contracts_cmd,
        core,
        demo_cmd,
        eng_cmd,
        evals_cmd,
        full_product_cmd,
        guided_cmd,
        personal_cmd,
        repository_cmd,
        support_cmd,
    )

    parser = sub.add_parser(
        "legacy",
        help="historical compatibility commands; not part of the alpha platform",
    )
    legacy = parser.add_subparsers(dest="legacy_command", required=True)
    core.register(legacy)
    contracts_cmd.register(legacy)
    demo_cmd.register(legacy)
    eng_cmd.register(legacy)
    evals_cmd.register(legacy)
    full_product_cmd.register(legacy)
    guided_cmd.register(legacy)
    personal_cmd.register(legacy)
    repository_cmd.register(legacy)
    support_cmd.register(legacy)


def build_parser() -> argparse.ArgumentParser:
    parser = PlatformArgumentParser(
        prog="pmpe",
        description=(
            "Compile a machine-checkable product contract, drive one bounded Coder, "
            "verify the candidate, and stop at RELEASE_READY."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    barebones_cmd.register(sub)
    _register_legacy(sub)
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
