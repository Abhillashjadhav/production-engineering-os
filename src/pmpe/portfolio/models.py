"""Evidence model, verdict vocabulary, and scoring guards for the auditor.

Reimplements the archived prototype's locked vocabulary against pmpe
conventions. Everything serializes to plain dicts (file-backed JSON state).
``EvidenceRef.origin`` is the independence key: two pieces of evidence
corroborate each other only when their origins differ — a README quoted
twice is still one origin (PD-PA-07: no finding without structured
evidence and confidence).

The guards here are product law, not heuristics:
- a numeric prioritization score never overrides a material
  high-confidence finding (:func:`must_surface`);
- hard AI-slop verdicts require the confidence floor AND a completed
  counter-evidence review, and may never rest solely on a forbidden basis
  (:func:`gate_slop_verdict`) — the verdict applies to the repository
  artifact, never to the person who created it (PD-PA-01).
"""

from __future__ import annotations

import enum
from dataclasses import asdict, dataclass, field
from typing import Any

CONFIDENCE_MIN = 0
CONFIDENCE_MAX = 100


class RecommendationVerdict(enum.StrEnum):
    """The five portfolio decisions the auditor may recommend per repository."""

    FIX = "FIX"
    SHOWCASE = "SHOWCASE"
    CONSOLIDATE = "CONSOLIDATE"
    REBUILD = "REBUILD"
    KEEP_AS_IS = "KEEP_AS_IS"


class AISlopVerdict(enum.StrEnum):
    """Repository-level AI-slop verdict — three values, never a personal judgment."""

    AI_SLOP = "AI_SLOP"
    NOT_AI_SLOP = "NOT_AI_SLOP"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class BusinessAccuracyVerdict(enum.StrEnum):
    """Claim-to-evidence grade for business/product accuracy (absence != falsehood)."""

    PROVEN = "PROVEN"
    LIKELY = "LIKELY"
    NOT_PROVEN = "NOT_PROVEN"
    CONTRADICTED = "CONTRADICTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class RemediationClosure(enum.StrEnum):
    """Post-remediation status of an originally-recorded finding."""

    FIXED = "FIXED"
    PARTIALLY_FIXED = "PARTIALLY_FIXED"
    NOT_FIXED = "NOT_FIXED"
    REGRESSED = "REGRESSED"


class InspectionDepth(enum.StrEnum):
    BROAD = "BROAD"
    DEEP = "DEEP"


class RepoVisibility(enum.StrEnum):
    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"


class Severity(enum.StrEnum):
    BLOCKING = "BLOCKING"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


#: Lower rank == more severe (used for deterministic sorting).
_SEVERITY_RANK: dict[Severity, int] = {
    Severity.BLOCKING: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
    Severity.INFO: 4,
}


def severity_rank(severity: Severity) -> int:
    return _SEVERITY_RANK[severity]


def clamp_confidence(value: float) -> int:
    """Clamp any confidence into the closed 0..100 integer band."""
    return max(CONFIDENCE_MIN, min(CONFIDENCE_MAX, int(value)))


@dataclass(frozen=True)
class EvidenceRef:
    """One piece of evidence backing a finding.

    ``origin`` is the independence key (e.g. "readme" vs "source_code" vs
    "commit_history"); ``kind`` is one of the contract's valid evidence
    kinds; ``reference`` locates the evidence (path#line, sha, url);
    ``content_digest`` pins what was actually seen.
    """

    evidence_id: str
    kind: str
    origin: str
    reference: str
    content_digest: str
    excerpt: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvidenceRef:
        return cls(
            evidence_id=str(data["evidence_id"]),
            kind=str(data["kind"]),
            origin=str(data["origin"]),
            reference=str(data["reference"]),
            content_digest=str(data["content_digest"]),
            excerpt=str(data.get("excerpt", "")),
        )


@dataclass
class Finding:
    """One material audit finding.

    Carries exactly the fields the product contract requires for every
    delivered finding: id, evidence, confidence, severity, affected
    capability, reasoning, and a remediation recommendation.
    ``repository``/``dimension`` locate it; ``tags`` are free annotations.
    """

    finding_id: str
    repository: str
    dimension: str
    summary: str
    evidence: list[EvidenceRef]
    confidence: int
    severity: Severity
    affected_capability: str
    reasoning: str
    remediation_recommendation: str
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.evidence:
            raise ValueError(
                f"finding {self.finding_id!r} has no evidence — no finding is delivered "
                "without structured evidence (PD-PA-07)"
            )
        self.confidence = clamp_confidence(self.confidence)

    @property
    def is_blocking(self) -> bool:
        return self.severity is Severity.BLOCKING

    @property
    def is_high_impact(self) -> bool:
        return severity_rank(self.severity) <= severity_rank(Severity.HIGH)

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "repository": self.repository,
            "dimension": self.dimension,
            "summary": self.summary,
            "evidence": [e.to_dict() for e in self.evidence],
            "confidence": self.confidence,
            "severity": self.severity.value,
            "affected_capability": self.affected_capability,
            "reasoning": self.reasoning,
            "remediation_recommendation": self.remediation_recommendation,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Finding:
        return cls(
            finding_id=str(data["finding_id"]),
            repository=str(data["repository"]),
            dimension=str(data["dimension"]),
            summary=str(data["summary"]),
            evidence=[EvidenceRef.from_dict(e) for e in data.get("evidence", [])],
            confidence=int(data["confidence"]),
            severity=Severity(data["severity"]),
            affected_capability=str(data["affected_capability"]),
            reasoning=str(data["reasoning"]),
            remediation_recommendation=str(data["remediation_recommendation"]),
            tags=[str(t) for t in data.get("tags", [])],
        )


def blocking_findings(findings: list[Finding]) -> list[Finding]:
    """The subset that blocks delivery / auto-merge (BLOCKING severity)."""
    return [f for f in findings if f.is_blocking]


def distinct_origins(evidence: list[EvidenceRef]) -> int:
    """Independent corroborating origins — the same origin never counts twice."""
    return len({e.origin for e in evidence})


def is_corroborated(
    finding: Finding, *, min_origins_normal: int, min_origins_high_impact: int
) -> bool:
    """Whether a finding meets the contract's corroboration threshold.

    High-impact findings (BLOCKING/HIGH) need the higher floor; a README is
    never corroboration for itself because origins are deduplicated.
    """
    needed = min_origins_high_impact if finding.is_high_impact else min_origins_normal
    return distinct_origins(finding.evidence) >= needed


def must_surface(finding: Finding, *, high_confidence_floor: int) -> bool:
    """Guard: a numeric score must never override a material finding.

    A finding that is both *material* (BLOCKING or HIGH severity) and
    *high-confidence* (>= floor) must always be surfaced regardless of any
    numeric prioritization or dimension score.
    """
    return finding.is_high_impact and finding.confidence >= high_confidence_floor


def prioritization_score(
    *,
    strategic_importance: float,
    severity_weight: float,
    authority_impact: float,
    confidence: float,
    remediation_effort: float,
) -> float:
    """Deterministic priority: strategic * severity * authority * confidence / effort.

    The score *ranks* remediation work; it never overrides a material
    high-confidence finding (see :func:`must_surface`).
    """
    if remediation_effort <= 0:
        raise ValueError("remediation_effort must be > 0 (it is the denominator)")
    return (
        strategic_importance * severity_weight * authority_impact * confidence
    ) / remediation_effort


@dataclass(frozen=True)
class SlopPolicy:
    """The gating half of the AI-slop policy (thresholds pinned by the contract)."""

    hard_verdict_min_confidence: int
    require_counter_evidence_review: bool
    forbidden_sole_bases: tuple[str, ...]


def gate_slop_verdict(
    proposed: AISlopVerdict,
    *,
    confidence: int,
    counter_evidence_reviewed: bool,
    sole_basis: str | None,
    policy: SlopPolicy,
) -> AISlopVerdict:
    """Apply the locked AI-slop gating rules to a proposed verdict.

    Hard verdicts (AI_SLOP / NOT_AI_SLOP) are downgraded to
    INSUFFICIENT_EVIDENCE unless confidence meets the floor AND a
    counter-evidence review has run; a verdict resting *solely* on a
    forbidden basis (writing style, disclosed AI assistance, commit volume,
    repository size, generated-file count, lack of popularity) is always
    downgraded, whatever the confidence. INSUFFICIENT_EVIDENCE passes
    through untouched — uncertainty is always expressible.
    """
    if sole_basis == "":
        raise ValueError(
            "sole_basis must be None (no sole basis) or a named basis — "
            "an empty string is ambiguous caller input"
        )
    if proposed is AISlopVerdict.INSUFFICIENT_EVIDENCE:
        return proposed
    if sole_basis is not None and sole_basis in policy.forbidden_sole_bases:
        return AISlopVerdict.INSUFFICIENT_EVIDENCE
    if clamp_confidence(confidence) < policy.hard_verdict_min_confidence:
        return AISlopVerdict.INSUFFICIENT_EVIDENCE
    if policy.require_counter_evidence_review and not counter_evidence_reviewed:
        return AISlopVerdict.INSUFFICIENT_EVIDENCE
    return proposed
