from __future__ import annotations

from pmpe.cli import build_parser


def test_default_cli_exposes_only_alpha_and_explicit_legacy_boundary() -> None:
    parser = build_parser()
    subparsers = next(
        action for action in parser._actions if hasattr(action, "choices") and action.choices
    )

    assert set(subparsers.choices) == {"barebones", "legacy"}
    assert "deployable software" not in parser.description


def test_legacy_commands_require_the_legacy_prefix() -> None:
    parser = build_parser()

    args = parser.parse_args(["legacy", "status", "example", "--runs-dir", "/tmp/runs"])

    assert args.command == "legacy"
    assert args.legacy_command == "status"
