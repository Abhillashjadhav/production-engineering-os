from __future__ import annotations

import argparse

from pmpe.cli import build_parser


def test_default_cli_exposes_only_alpha_and_explicit_legacy_boundary() -> None:
    parser = build_parser()
    subparsers = next(
        action for action in parser._actions if hasattr(action, "choices") and action.choices
    )

    assert set(subparsers.choices) == {"barebones", "legacy"}
    assert "deployable software" not in parser.description

    barebones = subparsers.choices["barebones"]
    lifecycle = next(
        action for action in barebones._actions if isinstance(action, argparse._SubParsersAction)
    )
    assert set(lifecycle.choices) == {
        "compare",
        "compile",
        "run",
        "status",
        "evidence",
        "inspect",
    }


def test_legacy_commands_require_the_legacy_prefix() -> None:
    parser = build_parser()

    args = parser.parse_args(["legacy", "status", "example", "--runs-dir", "/tmp/runs"])

    assert args.command == "legacy"
    assert args.legacy_command == "status"


def test_historical_top_level_invocation_is_a_compatibility_alias() -> None:
    parser = build_parser()

    args = parser.parse_args(["status", "example", "--runs-dir", "/tmp/runs"])

    assert args.command == "legacy"
    assert args.legacy_command == "status"


def test_historical_barebones_invocation_is_a_compatibility_alias() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "barebones",
            "contract.json",
            "--workspace",
            "/tmp/candidate",
            "--run-id",
            "example",
            "--approval-receipt",
            "receipt.json",
            "--expected-approver",
            "human",
            "--provider-command",
            "provider",
        ]
    )

    assert args.command == "barebones"
    assert args.barebones_command == "run"
