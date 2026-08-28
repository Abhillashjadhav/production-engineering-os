"""Typed review findings with an enforced lifecycle (PD-06/PD-07).

Originals are append-only: each reviewer's raw report is stored verbatim under
``reviews/`` and never rewritten; reconciliation and fixing operate on working
copies under ``findings/``. Status machine:

    PROPOSED -> ACCEPTED | REJECTED | DUPLICATE | PRODUCT_DECISION_REQUIRED
    ACCEPTED -> FIXED (fixer recorded)
    FIXED    -> VERIFIED (verifier, never the fixer)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pmpe.domain.errors import PmpeError
from pmpe.domain.serialize import atomic_write_json, jsonable

STATUSES = (
    "PROPOSED",
    "ACCEPTED",
    "REJECTED",
    "DUPLICATE",
    "PRODUCT_DECISION_REQUIRED",
    "FIXED",
    "VERIFIED",
)

_DECISION_TARGETS = ("ACCEPTED", "REJECTED", "DUPLICATE", "PRODUCT_DECISION_REQUIRED")


class FindingTransitionError(PmpeError):
    """An illegal finding status transition was attempted."""


class SameCandidateViolation(PmpeError):  # noqa: N818 — deliberate: it is a violation
    """Reviewers must all report against the same frozen candidate digest."""


@dataclass
class ReviewFinding:
    finding_id: str
    reviewer: str
    candidate_digest: str
    severity: str
    blocking: bool
    file: str
    line: int
    evidence: str
    failure_mechanism: str
    affected_requirement: str | None
    recommended_fix_direction: str
    mechanically_fixable: bool
    requires_product_decision: bool
    title: str
    status: str = "PROPOSED"
    duplicate_of: str | None = None
    decided_by: str | None = None
    decision_reason: str = ""
    fixed_by: str | None = None
    fix_commits: list[str] = field(default_factory=list)
    verified_by: str | None = None


class FindingsStore:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = Path(run_dir)
        self.reviews_dir = self.run_dir / "reviews"
        self.findings_dir = self.run_dir / "findings"
        self.reviews_dir.mkdir(parents=True, exist_ok=True)
        self.findings_dir.mkdir(parents=True, exist_ok=True)

    # --- intake -----------------------------------------------------------------

    def intake(
        self, reviewer: str, candidate_digest: str, findings_raw: list[dict[str, Any]]
    ) -> list[ReviewFinding]:
        for existing in self.all():
            if existing.candidate_digest != candidate_digest:
                raise SameCandidateViolation(
                    f"reviewer '{reviewer}' reports candidate {candidate_digest} but "
                    f"{existing.reviewer} reported {existing.candidate_digest} — all four "
                    "reviews must inspect the same frozen candidate (PD-06)"
                )
        atomic_write_json(
            self.reviews_dir / f"{reviewer}.json",
            {"reviewer": reviewer, "candidate_digest": candidate_digest, "findings": findings_raw},
        )
        created: list[ReviewFinding] = []
        next_number = len(self.all()) + 1
        for raw in findings_raw:
            finding = ReviewFinding(
                finding_id=f"RF-{next_number:03d}",
                reviewer=reviewer,
                candidate_digest=candidate_digest,
                severity=str(raw.get("severity", "medium")),
                blocking=bool(raw.get("blocking", False)),
                file=str(raw.get("file", "")),
                line=int(raw.get("line", 0)),
                evidence=str(raw.get("evidence", "")),
                failure_mechanism=str(raw.get("failure_mechanism", "")),
                affected_requirement=raw.get("affected_requirement"),
                recommended_fix_direction=str(raw.get("recommended_fix_direction", "")),
                mechanically_fixable=bool(raw.get("mechanically_fixable", False)),
                requires_product_decision=bool(raw.get("requires_product_decision", False)),
                title=str(raw.get("title", "")),
            )
            self._save(finding)
            created.append(finding)
            next_number += 1
        return created

    def originals(self, reviewer: str) -> dict[str, Any]:
        loaded: dict[str, Any] = json.loads((self.reviews_dir / f"{reviewer}.json").read_text())
        return loaded

    # --- lifecycle ---------------------------------------------------------------

    def set_status(
        self,
        finding_id: str,
        status: str,
        *,
        decided_by: str,
        reason: str,
        duplicate_of: str | None = None,
    ) -> ReviewFinding:
        if status not in _DECISION_TARGETS:
            raise FindingTransitionError(f"'{status}' is not a reconciliation decision status")
        finding = self.get(finding_id)
        if finding.status != "PROPOSED":
            raise FindingTransitionError(
                f"{finding_id} is {finding.status}; only PROPOSED findings can be decided"
            )
        if not decided_by.strip() or not reason.strip():
            raise FindingTransitionError(
                f"deciding {finding_id} requires a named decider and a reason"
            )
        finding.status = status
        finding.decided_by = decided_by
        finding.decision_reason = reason
        finding.duplicate_of = duplicate_of
        self._save(finding)
        return finding

    def record_fixed(self, finding_id: str, *, fixer: str, commits: list[str]) -> ReviewFinding:
        finding = self.get(finding_id)
        if finding.status != "ACCEPTED":
            raise FindingTransitionError(
                f"{finding_id} is {finding.status}; only ACCEPTED findings may be fixed (PD-07)"
            )
        finding.status = "FIXED"
        finding.fixed_by = fixer
        finding.fix_commits = list(commits)
        self._save(finding)
        return finding

    def record_verified(self, finding_id: str, *, verifier: str) -> ReviewFinding:
        finding = self.get(finding_id)
        if finding.status != "FIXED":
            raise FindingTransitionError(
                f"{finding_id} is {finding.status}; only FIXED findings can be verified"
            )
        if verifier == finding.fixed_by:
            raise FindingTransitionError(
                f"{finding_id}: the verifier cannot be the fixer ('{verifier}')"
            )
        finding.status = "VERIFIED"
        finding.verified_by = verifier
        self._save(finding)
        return finding

    # --- access ------------------------------------------------------------------

    def get(self, finding_id: str) -> ReviewFinding:
        path = self.findings_dir / f"{finding_id}.json"
        if not path.exists():
            raise PmpeError(f"unknown finding '{finding_id}'")
        return _from_dict(json.loads(path.read_text()))

    def all(self) -> list[ReviewFinding]:
        return [
            _from_dict(json.loads(p.read_text()))
            for p in sorted(self.findings_dir.glob("RF-*.json"))
        ]

    def _save(self, finding: ReviewFinding) -> None:
        atomic_write_json(self.findings_dir / f"{finding.finding_id}.json", jsonable(finding))


def _from_dict(raw: dict[str, Any]) -> ReviewFinding:
    return ReviewFinding(
        finding_id=raw["finding_id"],
        reviewer=raw["reviewer"],
        candidate_digest=raw["candidate_digest"],
        severity=raw["severity"],
        blocking=bool(raw["blocking"]),
        file=raw["file"],
        line=int(raw["line"]),
        evidence=raw["evidence"],
        failure_mechanism=raw["failure_mechanism"],
        affected_requirement=raw.get("affected_requirement"),
        recommended_fix_direction=raw.get("recommended_fix_direction", ""),
        mechanically_fixable=bool(raw.get("mechanically_fixable", False)),
        requires_product_decision=bool(raw.get("requires_product_decision", False)),
        title=raw.get("title", ""),
        status=raw.get("status", "PROPOSED"),
        duplicate_of=raw.get("duplicate_of"),
        decided_by=raw.get("decided_by"),
        decision_reason=raw.get("decision_reason", ""),
        fixed_by=raw.get("fixed_by"),
        fix_commits=list(raw.get("fix_commits", [])),
        verified_by=raw.get("verified_by"),
    )
