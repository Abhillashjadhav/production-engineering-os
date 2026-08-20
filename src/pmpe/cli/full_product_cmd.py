"""CLI for the one-command full product workflow."""

from __future__ import annotations

import argparse
from pathlib import Path

from pmpe.full_product import run_full_product_quickstart, verify_full_product_quickstart


def _cmd_quickstart(args: argparse.Namespace) -> int:
    manifest = run_full_product_quickstart(
        Path(args.output), repo_root=Path(args.repo_root), seed=args.seed
    )
    print("full PMOS-to-local-product workflow verified")
    print(f"workflow packs: {manifest['workflow_pack_count']}")
    print(f"pending approvals: {manifest['pending_approvals']}")
    print("external provider writes: 0")
    print(f"manifest: {Path(args.output) / 'full-product-manifest.json'}")
    print(f"trusted manifest digest (retain outside the output): {manifest['manifest_digest']}")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    digest = verify_full_product_quickstart(Path(args.output), expected_digest=args.expected_digest)
    print(f"full-product evidence verified: {digest}")
    return 0


def register(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    full = sub.add_parser(
        "full-product", help="run or verify the complete PMOS-to-local-product quickstart"
    )
    commands = full.add_subparsers(dest="full_product_command", required=True)
    quickstart = commands.add_parser("quickstart", help="run all stages with synthetic input")
    quickstart.add_argument("--output", required=True)
    quickstart.add_argument("--repo-root", default=".")
    quickstart.add_argument("--seed", type=int, default=2026)
    quickstart.set_defaults(fn=_cmd_quickstart)
    verify = commands.add_parser("verify", help="reverify an existing full-product manifest")
    verify.add_argument("--output", required=True)
    verify.add_argument("--expected-digest", required=True)
    verify.set_defaults(fn=_cmd_verify)
