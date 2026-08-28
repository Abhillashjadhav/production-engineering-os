"""Ingestion → validation → planning → architecture on the real example spec."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pmpe.architecture.agent import ArchitectureAgent
from pmpe.domain.models import RiskLevel
from pmpe.ingestion import ingest
from pmpe.planning.planner import EngineeringPlanner
from pmpe.policies.engine import PolicyEngine
from pmpe.validation.validator import RequirementValidator


def test_yaml_golden_path(golden_spec_path: Path, schema_path: Path) -> None:
    spec = ingest(golden_spec_path, schema_path)
    report = RequirementValidator().validate(spec)
    assert report.ok and not report.questions

    plan = EngineeringPlanner().plan(spec)
    assert plan.tasks

    arch = ArchitectureAgent(PolicyEngine()).design(spec, plan)
    assert arch.doc.overview
    assert len(arch.adrs) >= 3
    assert arch.escalations == []


def test_json_input_is_equivalent(
    golden_spec_dict: dict[str, Any], schema_path: Path, tmp_path: Path
) -> None:
    json_path = tmp_path / "spec.json"
    json_path.write_text(json.dumps(golden_spec_dict))
    spec = ingest(json_path, schema_path)
    assert spec.product_name == "TaskFlow"
    plan = EngineeringPlanner().plan(spec)
    assert plan == EngineeringPlanner().plan(spec)


def test_architecture_adrs_are_substantive(golden_spec_path: Path, schema_path: Path) -> None:
    spec = ingest(golden_spec_path, schema_path)
    plan = EngineeringPlanner().plan(spec)
    arch = ArchitectureAgent(PolicyEngine()).design(spec, plan)
    for adr in arch.adrs:
        assert adr.context and adr.decision and adr.consequences, adr.id
        assert adr.risk is not None
        assert adr.reversibility in {"reversible", "irreversible"}


def test_architecture_covers_security_and_reliability_implications(
    golden_spec_path: Path, schema_path: Path
) -> None:
    spec = ingest(golden_spec_path, schema_path)
    plan = EngineeringPlanner().plan(spec)
    arch = ArchitectureAgent(PolicyEngine()).design(spec, plan)
    assert {"security", "scalability", "reliability", "maintainability"} <= set(
        arch.doc.implications
    )


def test_high_risk_spec_produces_product_decision_escalation(
    golden_spec_dict: dict[str, Any], schema_path: Path, tmp_path: Path
) -> None:
    """The escalation path in the positive direction: a HIGH product risk may not
    be absorbed silently — the architect must hand it back as an escalation."""
    golden_spec_dict["risks"].append(
        {"description": "Migration could destroy existing task records", "level": "high"}
    )
    json_path = tmp_path / "spec.json"
    json_path.write_text(json.dumps(golden_spec_dict))
    spec = ingest(json_path, schema_path)
    plan = EngineeringPlanner().plan(spec)
    arch = ArchitectureAgent(PolicyEngine()).design(spec, plan)
    assert arch.escalations, "a HIGH spec risk must produce an escalation"
    assert any(e.risk is RiskLevel.HIGH for e in arch.escalations)
    assert any("destroy" in e.reason for e in arch.escalations)
