"""SYS-07/SYS-08: tests generated first (red), implementation turns them green."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from pmpe.domain.errors import StepFailure
from pmpe.domain.models import GeneratedFile, MvpSpec
from pmpe.implementation.agent import StdlibCrudGenerator
from pmpe.implementation.workspace import write_files
from pmpe.ingestion import ingest
from pmpe.planning.planner import EngineeringPlanner
from pmpe.testing.architect import TestArchitect


@pytest.fixture()
def spec(golden_spec_path: Path, schema_path: Path) -> MvpSpec:
    return ingest(golden_spec_path, schema_path)


def _run_unittests(workspace: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_generated_tests_cover_every_requirement(spec: MvpSpec) -> None:
    plan = EngineeringPlanner().plan(spec)
    generated = TestArchitect().design(spec, plan)
    blob = "\n".join(f.content for f in generated.files)
    for fr in spec.functional_requirements:
        assert f"Covers: {fr.id}" in blob, f"{fr.id} has no generated test"
    assert set(generated.tests_by_requirement) == {fr.id for fr in spec.functional_requirements}


def test_generated_tests_include_negative_cases(spec: MvpSpec) -> None:
    plan = EngineeringPlanner().plan(spec)
    generated = TestArchitect().design(spec, plan)
    blob = "\n".join(f.content for f in generated.files)
    for marker in ("401", "404", "400"):
        assert marker in blob, f"no negative case asserting {marker}"


def test_red_then_green(spec: MvpSpec, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    plan = EngineeringPlanner().plan(spec)

    generated = TestArchitect().design(spec, plan)
    write_files(workspace, generated.files)

    red = _run_unittests(workspace)
    assert red.returncode != 0, "tests must FAIL before implementation (red)"

    implementation = StdlibCrudGenerator().implement(spec, plan)
    for files in implementation.files_by_task.values():
        write_files(workspace, files)

    green = _run_unittests(workspace)
    assert green.returncode == 0, f"tests must pass after implementation:\n{green.stderr}"


def test_implementation_only_writes_planned_paths(spec: MvpSpec) -> None:
    plan = EngineeringPlanner().plan(spec)
    implementation = StdlibCrudGenerator().implement(spec, plan)
    allowed_roots = {"app", "tests", "README.md", ".gitignore", "deploy"}
    for files in implementation.files_by_task.values():
        for f in files:
            root = f.path.split("/", 1)[0]
            assert root in allowed_roots, f"unplanned path: {f.path}"


def test_implementation_maps_code_to_requirements(spec: MvpSpec) -> None:
    plan = EngineeringPlanner().plan(spec)
    implementation = StdlibCrudGenerator().implement(spec, plan)
    for fr in spec.functional_requirements:
        assert implementation.code_by_requirement.get(fr.id), f"{fr.id} maps to no code"


def test_workspace_writer_rejects_escaping_paths(tmp_path: Path) -> None:
    """The path boundary is fail-closed: absolute, parent-relative, and
    symlinked targets outside the workspace must never write."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (workspace / "link").symlink_to(outside)
    for path in ("/etc/escape.txt", "../escape.txt", "app/../../escape.txt", "link/escape.txt"):
        with pytest.raises(StepFailure):
            write_files(workspace, [GeneratedFile(path=path, content="x", kind="code")])
    assert not (outside / "escape.txt").exists()
