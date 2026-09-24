"""Deployment environment ladder and digest-bound production approval (PD-09).

- local/test: automatic once required checks pass
- staging: automatic once every assurance gate passes
- production: a named, recorded human approval bound to the exact candidate
  digest; a changed candidate invalidates the approval (fail closed)

No cloud adapter exists in this slice; the production path executes only in
fixture mode (see pmpe.deployment.simulated).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from pmpe.domain.errors import PmpeError
from pmpe.domain.serialize import atomic_write_json, jsonable

ENVIRONMENTS = ("local", "test", "staging", "production")


@dataclass(frozen=True)
class ProductionApproval:
    owner: str
    reason: str
    target: str
    candidate_digest: str
    approved_at: str


@dataclass
class DeploymentDecision:
    environment: str
    allowed: bool
    reasons: list[str] = field(default_factory=list)


@dataclass
class ReadinessResult:
    ready: bool
    missing: list[str] = field(default_factory=list)


class DeploymentPolicy:
    def authorize(
        self,
        environment: str,
        *,
        required_checks_passed: bool,
        assurance_gates_passed: bool = False,
        candidate_digest: str = "",
        approval: ProductionApproval | None = None,
    ) -> DeploymentDecision:
        if environment not in ENVIRONMENTS:
            raise PmpeError(
                f"unknown deployment environment '{environment}' (valid: {', '.join(ENVIRONMENTS)})"
            )
        reasons: list[str] = []
        if not required_checks_passed:
            reasons.append("required checks have not passed")
        if environment in ("staging", "production") and not assurance_gates_passed:
            reasons.append("assurance gates have not all passed")
        if environment == "production":
            reasons.extend(_approval_problems(approval, candidate_digest))
        return DeploymentDecision(environment=environment, allowed=not reasons, reasons=reasons)


def _approval_problems(approval: ProductionApproval | None, candidate_digest: str) -> list[str]:
    if approval is None:
        return ["production requires a named, recorded human approval"]
    problems: list[str] = []
    if not approval.owner.strip():
        problems.append("approval has no named owner")
    if not approval.reason.strip():
        problems.append("approval has no reason")
    if not approval.approved_at.strip():
        problems.append("approval has no timestamp")
    if approval.target != "production":
        problems.append(f"approval targets '{approval.target}', not production")
    if approval.candidate_digest != candidate_digest:
        problems.append(
            f"approval is bound to candidate digest {approval.candidate_digest}, but the "
            f"current candidate is {candidate_digest} — a changed candidate invalidates "
            "the approval"
        )
    return problems


def write_production_approval(run_dir: Path, approval: ProductionApproval) -> Path:
    path = Path(run_dir) / "production-approval.json"
    atomic_write_json(path, jsonable(approval))
    return path


def load_production_approval(run_dir: Path) -> ProductionApproval | None:
    path = Path(run_dir) / "production-approval.json"
    if not path.exists():
        return None
    raw = json.loads(path.read_text())
    return ProductionApproval(
        owner=raw["owner"],
        reason=raw["reason"],
        target=raw["target"],
        candidate_digest=raw["candidate_digest"],
        approved_at=raw["approved_at"],
    )


def production_readiness(
    workspace: Path, *, health_verified: bool, journey_verified: bool
) -> ReadinessResult:
    """READY needs rollback instructions, a runnable artifact, and verified
    health + user-journey checks — before production execution can even be
    considered."""
    missing: list[str] = []
    workspace = Path(workspace)
    if not (workspace / "deploy" / "ROLLBACK.md").exists():
        missing.append("deploy/ROLLBACK.md (rollback instructions)")
    if not (workspace / "deploy" / "run.sh").exists():
        missing.append("deploy/run.sh (runnable artifact)")
    if not health_verified:
        missing.append("verified health check")
    if not journey_verified:
        missing.append("verified user journey")
    return ReadinessResult(ready=not missing, missing=missing)
