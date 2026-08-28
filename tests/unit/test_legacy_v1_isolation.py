"""Issue #92: the V1 workflow is an explicit, test-only legacy harness."""

from __future__ import annotations

import argparse
import importlib
import importlib.util
from pathlib import Path

import pmpe.orchestration as orchestration
from pmpe.cli import build_parser

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_COMMANDS = {"run", "resume", "approve"}


def _top_level_commands() -> set[str]:
    parser = build_parser()
    subparsers = next(
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    )
    return set(subparsers.choices)


def test_shipped_cli_does_not_register_v1_execution_commands() -> None:
    commands = _top_level_commands()

    assert commands == {"barebones", "legacy"}
    assert FORBIDDEN_COMMANDS.isdisjoint(commands)


def test_shipped_package_does_not_export_or_contain_v1_workflow_engine() -> None:
    assert not hasattr(orchestration, "WorkflowEngine")
    assert importlib.util.find_spec("pmpe.orchestration.workflow") is None

    references = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "src" / "pmpe").rglob("*.py")
        if "WorkflowEngine" in path.read_text()
    }
    assert references == set()

    command_references = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "src" / "pmpe").rglob("*.py")
        if any(marker in path.read_text() for marker in ("pmpe run", "pmpe resume", "pmpe approve"))
    }
    assert command_references == set()


def test_legacy_workflow_requires_explicit_test_harness_import() -> None:
    legacy = importlib.import_module("tests.legacy_v1.workflow")

    assert legacy.WorkflowEngine.__module__ == "tests.legacy_v1.workflow"


def test_ci_and_current_user_docs_do_not_advertise_v1_execution() -> None:
    surfaces = [
        ROOT / ".github" / "workflows" / "ci.yml",
        ROOT / "ARCHITECTURE.md",
        ROOT / "README.md",
        ROOT / "SECURITY.md",
        ROOT / "examples" / "README.md",
        ROOT / "examples" / "taskflow_mvp_spec.yaml",
        ROOT / "docs" / "assumptions.md",
        ROOT / "docs" / "human-approval-model.md",
        ROOT / "docs" / "product-requirements-interpretation.md",
        ROOT / "docs" / "setup.md",
        ROOT / "docs" / "test-plan.md",
        ROOT / "docs" / "technical-requirements.md",
        ROOT / "docs" / "troubleshooting.md",
        ROOT / "docs" / "usage.md",
        ROOT / "docs" / "v2-production-engineering.md",
        ROOT / "docs" / "v3" / "current-state-assessment.md",
    ]

    violations: list[str] = []
    for path in surfaces:
        text = path.read_text()
        for marker in ("pmpe run", "pmpe resume", "pmpe approve", "WorkflowEngine"):
            if marker in text:
                violations.append(f"{path.relative_to(ROOT)} contains {marker!r}")

    assert violations == []
