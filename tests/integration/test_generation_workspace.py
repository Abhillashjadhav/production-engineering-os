"""SYS-07/SYS-08: tests generated first (red), implementation turns them green."""

from __future__ import annotations

from pathlib import Path

import pytest

from pmpe.domain.models import MvpSpec
from pmpe.ingestion import ingest
from pmpe.planning.planner import EngineeringPlanner
from pmpe.testing.architect import TestArchitect


@pytest.fixture()
def spec(golden_spec_path: Path, schema_path: Path) -> MvpSpec:
    return ingest(golden_spec_path, schema_path)


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
