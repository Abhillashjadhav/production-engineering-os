"""Decoders: persisted JSON artifacts back into typed domain models.

Only the models the engine must re-load across resumes get decoders; everything
else is recomputed deterministically from the spec (ADR-002).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pmpe.domain.models import (
    Approval,
    DeploymentResult,
    Escalation,
    Finding,
    GateResult,
    MergeDecision,
    MergeRecommendation,
    RiskLevel,
    Severity,
)


def gate_result_from_dict(raw: dict[str, Any]) -> GateResult:
    return GateResult(
        gate=raw["gate"],
        passed=bool(raw["passed"]),
        required=bool(raw["required"]),
        details=raw.get("details", ""),
        duration_s=float(raw.get("duration_s", 0.0)),
        skipped=bool(raw.get("skipped", False)),
    )


def finding_from_dict(raw: dict[str, Any]) -> Finding:
    return Finding(
        id=raw["id"],
        category=raw["category"],
        severity=Severity(raw["severity"]),
        blocking=bool(raw["blocking"]),
        safe_to_autofix=bool(raw["safe_to_autofix"]),
        file=raw["file"],
        line=int(raw["line"]),
        message=raw["message"],
        rule=raw["rule"],
    )


def escalation_from_dict(raw: dict[str, Any]) -> Escalation:
    return Escalation(
        id=raw["id"],
        risk=RiskLevel(raw["risk"]),
        reason=raw["reason"],
        step=raw["step"],
        context=raw.get("context", {}),
        created_at=raw.get("created_at", ""),
    )


def approval_from_dict(raw: dict[str, Any]) -> Approval:
    return Approval(
        escalation_id=raw["escalation_id"],
        approver=raw["approver"],
        reason=raw["reason"],
        approved=bool(raw["approved"]),
        timestamp=raw.get("timestamp", ""),
    )


def deployment_from_dict(raw: dict[str, Any]) -> DeploymentResult:
    return DeploymentResult(
        environment=raw["environment"],
        url=raw["url"],
        healthy=bool(raw["healthy"]),
        journey_passed=bool(raw["journey_passed"]),
        rollback_instructions_path=raw["rollback_instructions_path"],
        details=raw.get("details", ""),
    )


def load_escalations(run_dir: Path) -> list[Escalation]:
    """All escalations recorded for a run, in id order."""
    esc_dir = run_dir / "escalations"
    if not esc_dir.is_dir():
        return []
    return [
        escalation_from_dict(json.loads(p.read_text())) for p in sorted(esc_dir.glob("ESC-*.json"))
    ]


def load_approvals(run_dir: Path) -> dict[str, Approval]:
    """Recorded human decisions, keyed by escalation id."""
    appr_dir = run_dir / "approvals"
    if not appr_dir.is_dir():
        return {}
    approvals: dict[str, Approval] = {}
    for path in sorted(appr_dir.glob("ESC-*.json")):
        approval = approval_from_dict(json.loads(path.read_text()))
        approvals[approval.escalation_id] = approval
    return approvals


def merge_decision_from_dict(raw: dict[str, Any]) -> MergeDecision:
    return MergeDecision(
        recommendation=MergeRecommendation(raw["recommendation"]),
        reasons=list(raw.get("reasons", [])),
        checks=dict(raw.get("checks", {})),
    )
