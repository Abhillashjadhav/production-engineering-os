"""Recommendations, remediation backlog, scorecards, dashboard (M6).

Pure functions of recorded evidence. The recommendation ladder is
deterministic and honors the locked guard: a numeric score never
overrides a material high-confidence finding — such a repository can
never be SHOWCASE or KEEP_AS_IS. Every backlog entry traces to a finding
id (AC-PA-006). Renderers take run metadata as parameters (no wall
clock), label broad-scan-only repositories honestly instead of inventing
verdicts, and can never contain secret values because everything they
render is already redacted upstream.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pmpe.portfolio.inspection import DeepInspection
from pmpe.portfolio.models import (
    RecommendationVerdict,
    Severity,
    prioritization_score,
)
from pmpe.portfolio.policy import AuditorPolicy, load_policy
from pmpe.portfolio.scanner import RepoScan
from pmpe.portfolio.selection import Strategy
from pmpe.portfolio.slop import SlopAssessment

REPORTER_VERSION = "pa-reporter-1"

_SEVERITY_WEIGHTS: dict[Severity, float] = {
    Severity.BLOCKING: 5.0,
    Severity.HIGH: 4.0,
    Severity.MEDIUM: 3.0,
    Severity.LOW: 2.0,
    Severity.INFO: 1.0,
}

#: Dimensions whose findings damage authority the most.
_HIGH_AUTHORITY_DIMENSIONS = frozenset(
    {"security_dependency_integrity", "claim_to_evidence_integrity"}
)

#: Mechanical effort estimates by dimension (denominator of the formula).
_EFFORT_BY_DIMENSION = {
    "security_dependency_integrity": 2.0,
    "claim_to_evidence_integrity": 3.0,
}
_DEFAULT_EFFORT = 2.0

_SHOWCASE_FLOOR = 80
_STALE_DAYS = 365


def severity_weight(severity: Severity) -> float:
    return _SEVERITY_WEIGHTS[severity]


@dataclass
class RepoReport:
    """Everything known about one repository, honestly labeled.

    ``inspection``/``assessment``/``recommendation`` are None for a
    repository that received only the broad scan — no verdict is invented
    for it.
    """

    repository: str
    scan: RepoScan
    inspection: DeepInspection | None
    assessment: SlopAssessment | None
    recommendation: RecommendationVerdict | None
    recommendation_reasoning: str
    strategic: bool = False
    reporter_version: str = REPORTER_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "scan": self.scan.to_dict(),
            "inspection": None if self.inspection is None else self.inspection.to_dict(),
            "assessment": None if self.assessment is None else self.assessment.to_dict(),
            "recommendation": (None if self.recommendation is None else self.recommendation.value),
            "recommendation_reasoning": self.recommendation_reasoning,
            "strategic": self.strategic,
            "reporter_version": self.reporter_version,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RepoReport:
        return cls(
            repository=str(d["repository"]),
            scan=RepoScan.from_dict(d["scan"]),
            inspection=(
                None if d.get("inspection") is None else DeepInspection.from_dict(d["inspection"])
            ),
            assessment=(
                None if d.get("assessment") is None else SlopAssessment.from_dict(d["assessment"])
            ),
            recommendation=(
                None
                if d.get("recommendation") is None
                else RecommendationVerdict(d["recommendation"])
            ),
            recommendation_reasoning=str(d.get("recommendation_reasoning", "")),
            strategic=bool(d.get("strategic", False)),
            reporter_version=str(d.get("reporter_version", REPORTER_VERSION)),
        )


def recommend(
    *,
    scan: RepoScan,
    inspection: DeepInspection,
    assessment: SlopAssessment,
    strategy: Strategy,
    policy: AuditorPolicy,
) -> tuple[RecommendationVerdict, str]:
    """The deterministic recommendation ladder.

    Order is product law: (1) an AI_SLOP verdict with multiple material
    findings means the artifact damages authority as-is — REBUILD; (2) any
    material high-confidence finding forces FIX — no score can override it
    (the locked guard); (3) a stale fork consolidates; (4) a clean repo at
    showcase-grade authority readiness is SHOWCASE; (5) otherwise
    KEEP_AS_IS.
    """
    material = [f for f in inspection.findings if f.is_high_impact]
    surfaced = inspection.must_surface_finding_ids
    if assessment.verdict.value == "AI_SLOP" and len(material) >= 2:
        return (
            RecommendationVerdict.REBUILD,
            f"classified AI_SLOP with {len(material)} material findings "
            f"({', '.join(f.finding_id for f in material)}) — repairing in place "
            "would keep the misleading surface; rebuild from the honest core",
        )
    if surfaced:
        return (
            RecommendationVerdict.FIX,
            f"{len(surfaced)} material high-confidence finding(s) "
            f"({', '.join(surfaced)}) must be fixed first — no numeric score "
            "overrides a material finding",
        )
    days = scan.freshness.days_since_pushed
    if scan.freshness.is_fork and days is not None and days > _STALE_DAYS:
        return (
            RecommendationVerdict.CONSOLIDATE,
            f"a fork untouched for {days} days adds noise, not authority — "
            "archive it or fold anything valuable into an owned repository",
        )
    authority = inspection.dimension_scores.get("authority_readiness", 0)
    if not inspection.findings and authority >= _SHOWCASE_FLOOR:
        return (
            RecommendationVerdict.SHOWCASE,
            f"zero findings and authority readiness {authority} >= "
            f"{_SHOWCASE_FLOOR} — worth featuring",
        )
    return (
        RecommendationVerdict.KEEP_AS_IS,
        f"no material findings; authority readiness {authority} below the "
        f"showcase floor {_SHOWCASE_FLOOR} — fine as it is, not featured",
    )


def build_repo_report(
    *,
    scan: RepoScan,
    inspection: DeepInspection,
    assessment: SlopAssessment,
    strategy: Strategy,
    policy: AuditorPolicy,
) -> RepoReport:
    verdict, reasoning = recommend(
        scan=scan,
        inspection=inspection,
        assessment=assessment,
        strategy=strategy,
        policy=policy,
    )
    return RepoReport(
        repository=inspection.repository,
        scan=scan,
        inspection=inspection,
        assessment=assessment,
        recommendation=verdict,
        recommendation_reasoning=reasoning,
        strategic=inspection.repository in strategy.always_deep_scan(),
    )


@dataclass(frozen=True)
class BacklogItem:
    finding_id: str
    repository: str
    dimension: str
    severity: str
    priority: float
    remediation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "repository": self.repository,
            "dimension": self.dimension,
            "severity": self.severity,
            "priority": self.priority,
            "remediation": self.remediation,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> BacklogItem:
        return cls(
            finding_id=str(d["finding_id"]),
            repository=str(d["repository"]),
            dimension=str(d["dimension"]),
            severity=str(d["severity"]),
            priority=float(d["priority"]),
            remediation=str(d["remediation"]),
        )


def build_backlog(
    reports: list[RepoReport], *, policy: AuditorPolicy, strategy: Strategy | None = None
) -> list[BacklogItem]:
    """Prioritized remediation backlog: one traceable entry per finding.

    Priority uses the contract formula (strategic importance x severity x
    authority impact x confidence / effort). Every finding is included —
    must-surface findings can never fall out of the backlog by score.
    """
    items: list[BacklogItem] = []
    for report in reports:
        if report.inspection is None:
            continue
        strategic = (
            2.0
            if report.strategic
            or (strategy is not None and report.repository in strategy.always_deep_scan())
            else 1.0
        )
        for finding in report.inspection.findings:
            priority = prioritization_score(
                strategic_importance=strategic,
                severity_weight=severity_weight(finding.severity),
                authority_impact=(2.0 if finding.dimension in _HIGH_AUTHORITY_DIMENSIONS else 1.0),
                confidence=finding.confidence,
                remediation_effort=_EFFORT_BY_DIMENSION.get(finding.dimension, _DEFAULT_EFFORT),
            )
            items.append(
                BacklogItem(
                    finding_id=finding.finding_id,
                    repository=report.repository,
                    dimension=finding.dimension,
                    severity=finding.severity.value,
                    priority=round(priority, 4),
                    remediation=finding.remediation_recommendation,
                )
            )
    return sorted(items, key=lambda b: (-b.priority, b.finding_id))


def render_scorecard(report: RepoReport, *, run: dict[str, str]) -> str:
    """One repository's markdown scorecard (deep-inspected repos only)."""
    if report.inspection is None or report.assessment is None:
        raise ValueError(
            f"{report.repository} received a broad scan only — a scorecard "
            "would invent judgments no inspection supports"
        )
    insp = report.inspection
    lines = [
        f"# Scorecard — {report.repository}",
        "",
        f"- run: {run['run_id']} · generated: {run['generated_at']}",
        f"- snapshot: {insp.snapshot_digest}",
        f"- recommendation: **{report.recommendation.value if report.recommendation else ''}**"
        f" — {report.recommendation_reasoning}",
        f"- AI-slop verdict: **{report.assessment.verdict.value}** "
        f"(confidence {report.assessment.confidence}, counter-evidence review recorded)",
        "",
        "## Dimension scores",
        "",
    ]
    lines += [f"- {dim}: {score}" for dim, score in sorted(insp.dimension_scores.items())]
    lines += ["", "## Findings", ""]
    if insp.findings:
        for f in insp.findings:
            lines.append(
                f"- `{f.finding_id}` [{f.severity.value}] {f.summary} — "
                f"{f.remediation_recommendation}"
            )
    else:
        lines.append("- none")
    if insp.claim_grades:
        lines += ["", "## Business claims", ""]
        lines += [
            f"- {g.verdict.value}: {g.claim.text} ({g.claim.location})" for g in insp.claim_grades
        ]
    return "\n".join(lines) + "\n"


def render_dashboard(
    reports: list[RepoReport], *, backlog: list[BacklogItem], run: dict[str, str]
) -> str:
    """The portfolio dashboard (markdown, deterministic, honestly labeled)."""
    policy = load_policy()
    lines = [
        "# Portfolio dashboard",
        "",
        f"- run: {run['run_id']} · generated: {run['generated_at']}",
        f"- policy digest: {policy.digest}",
        f"- repositories: {len(reports)} · backlog items: {len(backlog)}",
        "",
        "| repository | slop verdict | recommendation | authority | findings |",
        "|---|---|---|---|---|",
    ]
    for r in sorted(reports, key=lambda x: x.repository):
        if r.inspection is None or r.assessment is None:
            lines.append(f"| {r.repository} | broad scan only | — | — | — |")
            continue
        lines.append(
            f"| {r.repository} | {r.assessment.verdict.value} | "
            f"{r.recommendation.value if r.recommendation else '—'} | "
            f"{r.inspection.dimension_scores.get('authority_readiness', 0)} | "
            f"{len(r.inspection.findings)} |"
        )
    lines += ["", "## Remediation backlog (highest priority first)", ""]
    if backlog:
        lines += [
            f"1. `{b.finding_id}` ({b.repository}, {b.severity}, priority {b.priority:g}) "
            f"— {b.remediation}"
            for b in backlog
        ]
    else:
        lines.append("- empty")
    return "\n".join(lines) + "\n"
