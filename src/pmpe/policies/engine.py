"""Declarative risk classification.

Levels (docs/human-approval-model.md):
- low    -> proceed automatically
- medium -> proceed with an explicit logged justification
- high   -> block until a human approves (pmpe approve)

Unknown decision types default to MEDIUM: conservative enough to leave a written
justification in the log, without stalling the pipeline on a taxonomy gap.
"""

from __future__ import annotations

from dataclasses import dataclass

from pmpe.domain.models import PolicyDecision, RiskLevel


@dataclass(frozen=True)
class PolicyRule:
    id: str
    decision_type: str
    level: RiskLevel
    justification: str


_DEFAULT_RULES: tuple[PolicyRule, ...] = (
    PolicyRule(
        "POL-001",
        "validation.contradiction",
        RiskLevel.HIGH,
        "Contradictory product requirements: only the PM can decide which side wins.",
    ),
    PolicyRule(
        "POL-002",
        "validation.missing_product_decision",
        RiskLevel.HIGH,
        "A required product decision is absent from the spec.",
    ),
    PolicyRule(
        "POL-003",
        "validation.unclear_acceptance_criteria",
        RiskLevel.HIGH,
        "An acceptance criterion cannot be expressed as a verifiable assertion.",
    ),
    PolicyRule(
        "POL-004",
        "validation.activity_only_nsm",
        RiskLevel.HIGH,
        "The North Star Metric measures activity, not an outcome.",
    ),
    PolicyRule(
        "POL-005",
        "architecture.irreversible_choice",
        RiskLevel.HIGH,
        "Irreversible architecture choices require human sign-off.",
    ),
    PolicyRule(
        "POL-006",
        "deployment.production_target",
        RiskLevel.HIGH,
        "Production deployment carries material risk and V1 has no production adapter.",
    ),
    PolicyRule(
        "POL-007",
        "fix.unresolvable_test_failure",
        RiskLevel.HIGH,
        "Failing checks the fix agent cannot safely resolve need an engineer.",
    ),
    PolicyRule(
        "POL-008",
        "data.destructive_migration",
        RiskLevel.HIGH,
        "Possible data loss; out of V1 scope entirely.",
    ),
    PolicyRule(
        "POL-009",
        "implementation.auth_token",
        RiskLevel.MEDIUM,
        "Auth work is security-sensitive but explicitly required by the spec (capability "
        "auth.bearer_token); templates use env-injected tokens with constant-time compare, "
        "and the security gate re-checks the result.",
    ),
    PolicyRule(
        "POL-010",
        "architecture.storage_choice",
        RiskLevel.MEDIUM,
        "Storage choice follows the declared data model and stack; reversible, logged.",
    ),
    PolicyRule(
        "POL-011",
        "codegen.crud_endpoint",
        RiskLevel.LOW,
        "Mechanical template expansion of a spec capability.",
    ),
    PolicyRule(
        "POL-012",
        "deployment.local",
        RiskLevel.LOW,
        "Local process deployment in an isolated workspace; fully reversible.",
    ),
    PolicyRule(
        "POL-013",
        "review.safe_autofix",
        RiskLevel.LOW,
        "Allow-listed formatting-level fix; all gates re-run afterwards.",
    ),
)

_DEFAULT = PolicyRule(
    "POL-DEFAULT",
    "*",
    RiskLevel.MEDIUM,
    "Unknown decision type: conservative default (medium) — proceeds, but only with "
    "this logged justification. Add an explicit rule for it.",
)


class PolicyEngine:
    def __init__(self, rules: tuple[PolicyRule, ...] = _DEFAULT_RULES) -> None:
        self._rules = {r.decision_type: r for r in rules}

    def classify(self, decision_type: str) -> PolicyDecision:
        rule = self._rules.get(decision_type, _DEFAULT)
        return PolicyDecision(
            decision_type=decision_type,
            level=rule.level,
            rule_id=rule.id,
            justification=rule.justification,
        )

    def requires_approval(self, level: RiskLevel) -> bool:
        return level is RiskLevel.HIGH
