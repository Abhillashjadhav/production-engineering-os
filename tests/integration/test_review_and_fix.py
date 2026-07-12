"""SYS-10/SYS-11: deterministic PR review and the allow-listed fix agent."""

from __future__ import annotations

from pathlib import Path

import pytest

from pmpe.domain.models import MvpSpec, Severity
from pmpe.implementation.agent import StdlibCrudGenerator
from pmpe.implementation.workspace import write_files
from pmpe.ingestion import ingest
from pmpe.planning.planner import EngineeringPlanner
from pmpe.review.fixer import FixAgent
from pmpe.review.reviewer import PrReviewer


@pytest.fixture()
def spec(golden_spec_path: Path, schema_path: Path) -> MvpSpec:
    return ingest(golden_spec_path, schema_path)


@pytest.fixture()
def built_workspace(spec: MvpSpec, tmp_path: Path) -> Path:
    from pmpe.testing.architect import TestArchitect

    plan = EngineeringPlanner().plan(spec)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    write_files(workspace, TestArchitect().design(spec, plan).files)
    for files in StdlibCrudGenerator().implement(spec, plan).files_by_task.values():
        write_files(workspace, files)
    return workspace


def test_clean_workspace_has_no_blocking_findings(built_workspace: Path, spec: MvpSpec) -> None:
    plan = EngineeringPlanner().plan(spec)
    report = PrReviewer().review(built_workspace, spec, plan)
    assert [f for f in report.findings if f.blocking] == []


def test_planted_eval_is_a_blocking_security_finding(
    built_workspace: Path, spec: MvpSpec
) -> None:
    (built_workspace / "app" / "danger.py").write_text("def run(x):\n    return eval(x)\n")
    plan = EngineeringPlanner().plan(spec)
    report = PrReviewer().review(built_workspace, spec, plan)
    blocking = [f for f in report.findings if f.blocking]
    assert any(f.rule == "SEC_EVAL" for f in blocking)


def test_unplanned_file_is_flagged_as_architecture_drift(
    built_workspace: Path, spec: MvpSpec
) -> None:
    (built_workspace / "rogue_module.py").write_text("x = 1\n")
    plan = EngineeringPlanner().plan(spec)
    report = PrReviewer().review(built_workspace, spec, plan)
    assert any(f.rule == "REV_UNPLANNED_FILE" and f.blocking for f in report.findings)


def test_missing_requirement_coverage_is_blocking(built_workspace: Path, spec: MvpSpec) -> None:
    for test_file in (built_workspace / "tests").rglob("test_*.py"):
        content = test_file.read_text()
        if "Covers: FR-006" in content:
            test_file.write_text(content.replace("Covers: FR-006", "Covers: FR-XXX"))
    plan = EngineeringPlanner().plan(spec)
    report = PrReviewer().review(built_workspace, spec, plan)
    assert any(f.rule == "REV_UNCOVERED_REQUIREMENT" and f.blocking for f in report.findings)


def test_todo_and_debug_print_are_non_blocking(built_workspace: Path, spec: MvpSpec) -> None:
    api = built_workspace / "app" / "api.py"
    api.write_text(api.read_text() + '\n# TODO: revisit\nprint("debug")\n')
    plan = EngineeringPlanner().plan(spec)
    report = PrReviewer().review(built_workspace, spec, plan)
    rules = {f.rule: f for f in report.findings}
    assert "REV_TODO" in rules and not rules["REV_TODO"].blocking
    assert "REV_DEBUG_PRINT" in rules and not rules["REV_DEBUG_PRINT"].blocking


def test_fixer_fixes_only_safe_findings_and_escalates_blockers(
    built_workspace: Path, spec: MvpSpec
) -> None:
    storage = built_workspace / "app" / "storage.py"
    storage.write_text(storage.read_text().rstrip("\n") + "   \n")  # trailing whitespace
    (built_workspace / "app" / "danger.py").write_text("def run(x):\n    return eval(x)\n")

    plan = EngineeringPlanner().plan(spec)
    report = PrReviewer().review(built_workspace, spec, plan)
    result = FixAgent().apply(built_workspace, report)

    assert any(f.rule == "REV_TRAILING_WHITESPACE" for f in result.fixed)
    assert any(f.rule == "SEC_EVAL" for f in result.escalated)
    assert not any(line.rstrip("\n") != line.rstrip() for line in storage.read_text().splitlines())

    # the fixer never edits what it cannot safely fix
    assert (built_workspace / "app" / "danger.py").read_text().count("eval") == 1


def test_fixer_is_idempotent(built_workspace: Path, spec: MvpSpec) -> None:
    plan = EngineeringPlanner().plan(spec)
    report = PrReviewer().review(built_workspace, spec, plan)
    first = FixAgent().apply(built_workspace, report)
    report2 = PrReviewer().review(built_workspace, spec, plan)
    second = FixAgent().apply(built_workspace, report2)
    assert second.fixed == []
    assert {f.severity for f in first.fixed} <= {Severity.MINOR, Severity.INFO}
