"""Build and independently verify the customer-support portable package."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pmpe.domain.errors import SpecError
from pmpe.support_package import (
    PackageContractError,
    assemble_support_package,
    verify_support_package,
)


def _build(args: argparse.Namespace) -> int:
    try:
        result = assemble_support_package(
            Path(args.contract),
            Path(args.approval_receipt),
            args.expected_approver,
            Path(args.output),
        )
    except PackageContractError as exc:
        raise SpecError(str(exc)) from exc
    print(
        json.dumps(
            {
                "bundle": str(result.bundle),
                "manifest_digest": result.manifest_digest,
                "state": result.state,
            },
            sort_keys=True,
        )
    )
    return 0


def _verify(args: argparse.Namespace) -> int:
    try:
        result = verify_support_package(
            Path(args.bundle), expected_manifest_digest=args.expected_manifest_digest
        )
    except PackageContractError as exc:
        raise SpecError(str(exc)) from exc
    print(
        json.dumps(
            {
                "bundle": str(result.bundle),
                "manifest_digest": result.manifest_digest,
                "state": result.state,
            },
            sort_keys=True,
        )
    )
    return 0


def register(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    package = sub.add_parser(
        "package",
        help="build or verify the portable customer-support reference package",
    )
    commands = package.add_subparsers(dest="support_package_command", required=True)
    build = commands.add_parser("build", help="assemble and seal a PACKAGE_READY bundle")
    build.add_argument("--contract", required=True)
    build.add_argument("--approval-receipt", required=True)
    build.add_argument("--expected-approver", required=True)
    build.add_argument("--output", required=True)
    build.set_defaults(fn=_build)
    verify = commands.add_parser("verify", help="verify a sealed support package")
    verify.add_argument("--bundle", required=True)
    verify.add_argument("--expected-manifest-digest")
    verify.set_defaults(fn=_verify)
