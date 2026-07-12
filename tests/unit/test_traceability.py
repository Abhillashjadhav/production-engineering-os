"""SYS-17: requirement-to-deployment traceability."""

from __future__ import annotations

from typing import Any

import pytest

from pmpe.audit.traceability import TraceabilityBuilder
from pmpe.domain.models import DeploymentResult, MvpSpec
from pmpe.ingestion.normalizer import normalize_spec
from pmpe.planning.planner import EngineeringPlanner


@pytest.fixture()
def spec(golden_spec_dict: dict[str, Any]) -> MvpSpec:
    return normalize_spec(golden_spec_dict)


def _inputs(spec: MvpSpec) -> dict[str, Any]:
    plan = EngineeringPlanner().plan(spec)
    fr_ids = [fr.id for fr in spec.functional_requirements]
    return {
        "plan": plan,
        "adr_ids_by_requirement": {rid: ["ADR-001"] for rid in fr_ids},
        "tests_by_requirement": {rid: [f"tests/test_{rid.lower()}.py"] for rid in fr_ids},
        "code_by_requirement": {rid: ["src/app.py"] for rid in fr_ids},
        "findings": [],
        "deployment": DeploymentResult(
            environment="local",
            url="http://127.0.0.1:0",
            healthy=True,
            journey_passed=True,
            rollback_instructions_path="deploy/ROLLBACK.md",
            details="ok",
        ),
    }


def test_complete_traceability_when_everything_maps(spec: MvpSpec) -> None:
    report = TraceabilityBuilder().build(spec=spec, **_inputs(spec))
    assert report.complete
    assert report.gaps == []
    assert {e.requirement_id for e in report.entries} == {
        fr.id for fr in spec.functional_requirements
    }


def test_entries_carry_the_full_chain(spec: MvpSpec) -> None:
    report = TraceabilityBuilder().build(spec=spec, **_inputs(spec))
    for entry in report.entries:
        assert entry.tasks, entry.requirement_id
        assert entry.adrs
        assert entry.code_files
        assert entry.tests
        assert entry.deployment_evidence


def test_requirement_without_tests_is_a_gap(spec: MvpSpec) -> None:
    inputs = _inputs(spec)
    inputs["tests_by_requirement"].pop("FR-003")
    report = TraceabilityBuilder().build(spec=spec, **inputs)
    assert not report.complete
    assert any("FR-003" in gap for gap in report.gaps)


def test_requirement_without_code_is_a_gap(spec: MvpSpec) -> None:
    inputs = _inputs(spec)
    inputs["code_by_requirement"]["FR-004"] = []
    report = TraceabilityBuilder().build(spec=spec, **inputs)
    assert not report.complete
    assert any("FR-004" in gap for gap in report.gaps)


def test_markdown_rendering_contains_every_requirement(spec: MvpSpec) -> None:
    report = TraceabilityBuilder().build(spec=spec, **_inputs(spec))
    md = report.to_markdown()
    for fr in spec.functional_requirements:
        assert fr.id in md
