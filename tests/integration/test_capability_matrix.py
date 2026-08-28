"""Regression coverage for review findings: valid-but-non-golden specs must build.

Each case here reproduces a confirmed independent-review finding where a spec that
passes validation produced a broken generated product (status-default assumptions,
entity-less server import, missing health endpoint, falsy required values, auth
probe without entity.list).
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from pmpe.deployment.local import LocalProcessDeployer
from pmpe.domain.models import MvpSpec
from pmpe.implementation.agent import StdlibCrudGenerator
from pmpe.implementation.workspace import write_files
from pmpe.ingestion.normalizer import normalize_spec
from pmpe.planning.planner import EngineeringPlanner
from pmpe.testing.architect import TestArchitect
from pmpe.validation.validator import RequirementValidator


def _build_workspace(spec: MvpSpec, tmp_path: Path) -> Path:
    plan = EngineeringPlanner().plan(spec)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    write_files(workspace, TestArchitect().design(spec, plan).files)
    for files in StdlibCrudGenerator().implement(spec, plan).files_by_task.values():
        write_files(workspace, files)
    return workspace


def _run_generated_tests(workspace: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _assert_valid(spec: MvpSpec) -> None:
    report = RequirementValidator().validate(spec)
    assert report.ok and not report.questions, [i.message for i in report.errors]


def _variant(golden: dict[str, Any], mutate: Any) -> MvpSpec:
    data = copy.deepcopy(golden)
    mutate(data)
    spec = normalize_spec(data)
    _assert_valid(spec)
    return spec


def test_custom_status_default_builds_green(
    golden_spec_dict: dict[str, Any], tmp_path: Path
) -> None:
    def mutate(data: dict[str, Any]) -> None:
        for field in data["entities"][0]["fields"]:
            if field["name"] == "status":
                field["default"] = "todo"
        # AC-003 pins the literal default; keep the spec self-consistent
        for ac in data["acceptance_criteria"]:
            ac["criterion"] = ac["criterion"].replace('status "open"', 'status "todo"')

    spec = _variant(golden_spec_dict, mutate)
    workspace = _build_workspace(spec, tmp_path)
    result = _run_generated_tests(workspace)
    assert result.returncode == 0, result.stderr[-2000:]


def test_status_without_default_builds_green(
    golden_spec_dict: dict[str, Any], tmp_path: Path
) -> None:
    def mutate(data: dict[str, Any]) -> None:
        for field in data["entities"][0]["fields"]:
            if field["name"] == "status":
                field.pop("default", None)

    spec = _variant(golden_spec_dict, mutate)
    workspace = _build_workspace(spec, tmp_path)
    result = _run_generated_tests(workspace)
    assert result.returncode == 0, result.stderr[-2000:]


def test_entity_less_spec_builds_green_and_deploys(fixtures_dir: Path, tmp_path: Path) -> None:
    data = json.loads((fixtures_dir / "minimal_valid_spec.json").read_text())
    spec = normalize_spec(data)
    _assert_valid(spec)
    workspace = _build_workspace(spec, tmp_path)
    result = _run_generated_tests(workspace)
    assert result.returncode == 0, result.stderr[-2000:]

    deployer = LocalProcessDeployer()
    deployer.write_artifacts(workspace, spec)
    deployment = deployer.deploy(workspace, spec)
    assert deployment.healthy and deployment.journey_passed, deployment.details
    # a no-auth product's run script must not demand a token the app never reads
    assert "APP_TOKEN" not in (workspace / "deploy" / "run.sh").read_text()


def test_no_health_check_spec_builds_and_deploys_via_tcp(
    golden_spec_dict: dict[str, Any], tmp_path: Path
) -> None:
    def mutate(data: dict[str, Any]) -> None:
        data["functional_requirements"] = [
            fr for fr in data["functional_requirements"] if fr["id"] != "FR-007"
        ]
        data["acceptance_criteria"] = [
            ac for ac in data["acceptance_criteria"] if ac["requirement"] != "FR-007"
        ]

    spec = _variant(golden_spec_dict, mutate)
    workspace = _build_workspace(spec, tmp_path)
    result = _run_generated_tests(workspace)
    assert result.returncode == 0, result.stderr[-2000:]

    deployer = LocalProcessDeployer()
    deployer.write_artifacts(workspace, spec)
    deployment = deployer.deploy(workspace, spec)
    assert deployment.healthy and deployment.journey_passed, deployment.details
    assert "tcp-ready" in deployment.details


def test_auth_without_list_capability_builds_green(
    golden_spec_dict: dict[str, Any], tmp_path: Path
) -> None:
    def mutate(data: dict[str, Any]) -> None:
        data["functional_requirements"] = [
            fr for fr in data["functional_requirements"] if fr["id"] != "FR-003"
        ]
        data["acceptance_criteria"] = [
            ac for ac in data["acceptance_criteria"] if ac["requirement"] != "FR-003"
        ]

    spec = _variant(golden_spec_dict, mutate)
    workspace = _build_workspace(spec, tmp_path)
    result = _run_generated_tests(workspace)
    assert result.returncode == 0, result.stderr[-2000:]


def test_falsy_required_field_value_is_accepted(
    golden_spec_dict: dict[str, Any], tmp_path: Path
) -> None:
    def mutate(data: dict[str, Any]) -> None:
        data["entities"][0]["fields"].append(
            {"name": "priority_level", "type": "int", "required": True}
        )

    spec = _variant(golden_spec_dict, mutate)
    workspace = _build_workspace(spec, tmp_path)
    blob = "\n".join(p.read_text() for p in (workspace / "tests").rglob("test_*.py"))
    assert "test_create_task_accepts_falsy_priority_level" in blob
    result = _run_generated_tests(workspace)
    assert result.returncode == 0, result.stderr[-2000:]


@pytest.mark.parametrize("hostile_name", ['Bob\'s "Task" Manager', 'x""" import os'])
def test_hostile_product_name_still_compiles(
    golden_spec_dict: dict[str, Any], tmp_path: Path, hostile_name: str
) -> None:
    def mutate(data: dict[str, Any]) -> None:
        data["product_name"] = hostile_name

    spec = _variant(golden_spec_dict, mutate)
    workspace = _build_workspace(spec, tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "compileall", "-q", "app", "tests"],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr[-1000:]


def test_hostile_field_default_still_compiles_and_runs(
    golden_spec_dict: dict[str, Any], tmp_path: Path
) -> None:
    def mutate(data: dict[str, Any]) -> None:
        for field in data["entities"][0]["fields"]:
            if field["name"] == "status":
                field["default"] = "n/a — 'pending'"
        for ac in data["acceptance_criteria"]:
            ac["criterion"] = ac["criterion"].replace('status "open"', "status n/a — 'pending'")

    spec = _variant(golden_spec_dict, mutate)
    workspace = _build_workspace(spec, tmp_path)
    result = _run_generated_tests(workspace)
    assert result.returncode == 0, result.stderr[-2000:]
