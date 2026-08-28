"""SYS-15: risk classification and approval requirements."""

from __future__ import annotations

import pytest

from pmpe.domain.models import RiskLevel
from pmpe.policies.engine import PolicyEngine


@pytest.fixture()
def engine() -> PolicyEngine:
    return PolicyEngine()


@pytest.mark.parametrize(
    ("decision", "expected"),
    [
        ("deployment.production_target", RiskLevel.HIGH),
        ("validation.contradiction", RiskLevel.HIGH),
        ("validation.unclear_acceptance_criteria", RiskLevel.HIGH),
        ("architecture.irreversible_choice", RiskLevel.HIGH),
        ("fix.unresolvable_test_failure", RiskLevel.HIGH),
        ("implementation.auth_token", RiskLevel.MEDIUM),
        ("codegen.crud_endpoint", RiskLevel.LOW),
        ("deployment.local", RiskLevel.LOW),
    ],
)
def test_default_risk_classification(
    engine: PolicyEngine, decision: str, expected: RiskLevel
) -> None:
    assert engine.classify(decision).level is expected


def test_unknown_decision_type_fails_closed(engine: PolicyEngine) -> None:
    assert engine.classify("something.never.seen").level is RiskLevel.HIGH
    assert engine.requires_approval(engine.classify("something.never.seen").level)


def test_only_high_requires_approval(engine: PolicyEngine) -> None:
    assert engine.requires_approval(RiskLevel.HIGH)
    assert not engine.requires_approval(RiskLevel.MEDIUM)
    assert not engine.requires_approval(RiskLevel.LOW)


def test_medium_requires_logged_justification(engine: PolicyEngine) -> None:
    decision = engine.classify("implementation.auth_token")
    assert decision.level is RiskLevel.MEDIUM
    assert decision.justification, "medium-risk decisions must carry a written justification"


def test_every_classification_names_its_rule(engine: PolicyEngine) -> None:
    decision = engine.classify("deployment.production_target")
    assert decision.rule_id, "every automated decision must be explainable via a rule id"
