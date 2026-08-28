"""SYS-09: the quality gate runner over a real generated workspace."""

from __future__ import annotations

from pathlib import Path

import pytest

from pmpe.domain.models import MvpSpec
from pmpe.implementation.agent import StdlibCrudGenerator
from pmpe.implementation.workspace import write_files
from pmpe.ingestion import ingest
from pmpe.planning.planner import EngineeringPlanner
from pmpe.quality.gates import QualityGateRunner
from pmpe.testing.architect import TestArchitect


@pytest.fixture()
def built_workspace(golden_spec_path: Path, schema_path: Path, tmp_path: Path) -> Path:
    spec: MvpSpec = ingest(golden_spec_path, schema_path)
    plan = EngineeringPlanner().plan(spec)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    write_files(workspace, TestArchitect().design(spec, plan).files)
    for files in StdlibCrudGenerator().implement(spec, plan).files_by_task.values():
        write_files(workspace, files)
    return workspace


def test_all_required_gates_pass_on_clean_workspace(built_workspace: Path) -> None:
    results = QualityGateRunner(built_workspace).run()
    failed = [r for r in results if r.required and not r.passed]
    assert failed == [], [f"{r.gate}: {r.details}" for r in failed]


def test_expected_gate_set_is_recorded(built_workspace: Path) -> None:
    results = QualityGateRunner(built_workspace).run()
    names = {r.gate for r in results}
    assert {"compile", "unit", "integration", "security"} <= names


def test_every_gate_result_has_details_and_duration(built_workspace: Path) -> None:
    for r in QualityGateRunner(built_workspace).run():
        assert r.details is not None
        assert r.duration_s >= 0


def test_planted_vulnerability_fails_security_gate(built_workspace: Path) -> None:
    (built_workspace / "app" / "danger.py").write_text("def run(x):\n    return eval(x)\n")
    results = QualityGateRunner(built_workspace).run()
    security = next(r for r in results if r.gate == "security")
    assert not security.passed
    assert "SEC_EVAL" in security.details


def test_broken_code_fails_unit_gate(built_workspace: Path) -> None:
    storage = built_workspace / "app" / "storage.py"
    storage.write_text(storage.read_text().replace("def create_task", "def create_task_broken", 1))
    results = QualityGateRunner(built_workspace).run()
    unit = next(r for r in results if r.gate == "unit")
    assert not unit.passed
