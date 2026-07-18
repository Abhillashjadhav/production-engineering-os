"""AI-slop classifier with counter-evidence review and stability check (M5).

The verdict applies to the repository artifact and its observable evidence
discipline — never to the person who created it (PD-PA-01). The classifier
uses only evidence-quality signals; the six forbidden bases (writing
style, disclosed AI assistance, commit volume, repository size,
generated-file count, lack of popularity) are not signals at all, so no
verdict can rest on them, solely or otherwise.

Gating (locked): a hard verdict requires >= 3 distinct signals on its own
side, the policy confidence floor, and a completed counter-evidence
review — the review is the opposing-side search itself, and its searched
categories and findings are recorded on the assessment. The accusatory
verdict (AI_SLOP) additionally demands ZERO exculpatory evidence, while
NOT_AI_SLOP tolerates at most one slop signal — the asymmetry runs in the
subject-protective direction and is disclosed in each assessment's
reasoning. Anything less is INSUFFICIENT_EVIDENCE; uncertainty is always
expressible and never penalized.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pmpe.portfolio.inspection import DeepInspection
from pmpe.portfolio.models import AISlopVerdict, BusinessAccuracyVerdict, gate_slop_verdict
from pmpe.portfolio.policy import AuditorPolicy
from pmpe.portfolio.scanner import RepoScan

CLASSIFIER_VERSION = "pa-slop-1"

#: Signals suggesting slop (evidence-discipline absences and incidents).
SLOP_SIGNAL_NAMES = (
    "claims_without_evidence",
    "no_tests",
    "no_ci",
    "missing_lockfile",
    "unpinned_dependencies",
    "committed_secret",
    "no_license",
)

#: Exculpatory signals (observable engineering discipline).
EXCULPATORY_SIGNAL_NAMES = (
    "tests_present",
    "ci_present",
    "lockfile_present",
    "dependencies_pinned",
    "license_present",
    "docs_dir_present",
)

_HARD_VERDICT_MIN_SIGNALS = 3


def _slop_signals(scan: RepoScan, inspection: DeepInspection) -> tuple[str, ...]:
    signals: list[str] = []
    ungrounded = [
        g for g in inspection.claim_grades if g.verdict is not BusinessAccuracyVerdict.LIKELY
    ]
    if ungrounded:
        signals.append("claims_without_evidence")
    if not scan.tests_ci.has_tests:
        signals.append("no_tests")
    if not scan.tests_ci.has_ci:
        signals.append("no_ci")
    if scan.security.dependency_manifests and not scan.security.has_lockfile:
        signals.append("missing_lockfile")
    if scan.security.pinned_dependencies is False:
        signals.append("unpinned_dependencies")
    if scan.security.secret_hits:
        signals.append("committed_secret")
    if not scan.docs.license_name:
        signals.append("no_license")
    return tuple(signals)


def _exculpatory_signals(scan: RepoScan) -> tuple[str, ...]:
    signals: list[str] = []
    if scan.tests_ci.has_tests:
        signals.append("tests_present")
    if scan.tests_ci.has_ci:
        signals.append("ci_present")
    if scan.security.has_lockfile:
        signals.append("lockfile_present")
    if scan.security.pinned_dependencies is True:
        signals.append("dependencies_pinned")
    if scan.docs.license_name:
        signals.append("license_present")
    if scan.docs.has_docs_dir:
        signals.append("docs_dir_present")
    return tuple(signals)


@dataclass(frozen=True)
class SlopAssessment:
    """The gated AI-slop verdict for one repository artifact."""

    repository: str
    verdict: AISlopVerdict
    confidence: int
    signals: tuple[str, ...]
    counter_evidence_reviewed: bool
    counter_evidence_searched: tuple[str, ...]
    counter_evidence_found: tuple[str, ...]
    reasoning: str
    snapshot_digest: str
    classifier_version: str = CLASSIFIER_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "verdict": self.verdict.value,
            "confidence": self.confidence,
            "signals": list(self.signals),
            "counter_evidence_reviewed": self.counter_evidence_reviewed,
            "counter_evidence_searched": list(self.counter_evidence_searched),
            "counter_evidence_found": list(self.counter_evidence_found),
            "reasoning": self.reasoning,
            "snapshot_digest": self.snapshot_digest,
            "classifier_version": self.classifier_version,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SlopAssessment:
        return cls(
            repository=str(d["repository"]),
            verdict=AISlopVerdict(d["verdict"]),
            confidence=int(d["confidence"]),
            signals=tuple(str(s) for s in d.get("signals", [])),
            counter_evidence_reviewed=bool(d["counter_evidence_reviewed"]),
            counter_evidence_searched=tuple(str(s) for s in d.get("counter_evidence_searched", [])),
            counter_evidence_found=tuple(str(s) for s in d.get("counter_evidence_found", [])),
            reasoning=str(d["reasoning"]),
            snapshot_digest=str(d["snapshot_digest"]),
            classifier_version=str(d.get("classifier_version", CLASSIFIER_VERSION)),
        )


def classify_slop(
    scan: RepoScan, inspection: DeepInspection, *, policy: AuditorPolicy
) -> SlopAssessment:
    """Classify one repository artifact, counter-evidence review included."""
    slop = _slop_signals(scan, inspection)
    exculpatory = _exculpatory_signals(scan)
    searched: tuple[str, ...]
    found: tuple[str, ...]

    if len(slop) >= _HARD_VERDICT_MIN_SIGNALS and not exculpatory:
        proposed = AISlopVerdict.AI_SLOP
        confidence = min(60 + 5 * len(slop), 95)
        searched, found = EXCULPATORY_SIGNAL_NAMES, exculpatory
        reasoning = (
            f"{len(slop)} independent evidence-discipline signals "
            f"({', '.join(slop)}) with zero exculpatory engineering signals "
            f"after searching all {len(EXCULPATORY_SIGNAL_NAMES)} categories; "
            "the verdict describes the repository artifact only"
        )
    elif len(exculpatory) >= _HARD_VERDICT_MIN_SIGNALS and len(slop) <= 1:
        proposed = AISlopVerdict.NOT_AI_SLOP
        confidence = min(60 + 5 * len(exculpatory), 95)
        searched, found = SLOP_SIGNAL_NAMES, slop
        reasoning = (
            f"{len(exculpatory)} independent engineering-discipline signals "
            f"({', '.join(exculpatory)}) with at most one slop signal after "
            f"searching all {len(SLOP_SIGNAL_NAMES)} slop categories; the "
            "verdict describes the repository artifact only"
        )
    else:
        proposed = AISlopVerdict.INSUFFICIENT_EVIDENCE
        confidence = 50
        searched = SLOP_SIGNAL_NAMES + EXCULPATORY_SIGNAL_NAMES
        found = slop + exculpatory
        reasoning = (
            f"mixed evidence — {len(slop)} slop signal(s) ({', '.join(slop) or 'none'}) "
            f"against {len(exculpatory)} exculpatory signal(s) "
            f"({', '.join(exculpatory) or 'none'}); neither side clears the "
            f"{_HARD_VERDICT_MIN_SIGNALS}-signal hard-verdict floor, so the honest "
            "answer is uncertainty"
        )

    verdict = gate_slop_verdict(
        proposed,
        confidence=confidence,
        counter_evidence_reviewed=True,
        sole_basis=None,
        policy=policy.slop,
    )
    return SlopAssessment(
        repository=inspection.repository,
        verdict=verdict,
        confidence=confidence,
        signals=slop,
        counter_evidence_reviewed=True,
        counter_evidence_searched=searched,
        counter_evidence_found=found,
        reasoning=reasoning,
        snapshot_digest=inspection.snapshot_digest,
    )


@dataclass(frozen=True)
class StabilityReport:
    """Cross-run verdict agreement: any flip is a HOLD (quality guardrail)."""

    status: str  # "OK" | "HOLD"
    runs: int
    disagreements: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "runs": self.runs,
            "disagreements": list(self.disagreements),
        }


def verify_stability(runs: list[list[SlopAssessment]]) -> StabilityReport:
    """Compare repeated classification runs; a verdict flip is a HOLD."""
    if len(runs) < 2:
        raise ValueError("stability needs at least two runs to compare")
    baseline = {a.repository: a.verdict for a in runs[0]}
    disagreements: list[str] = []
    for idx, run in enumerate(runs[1:], start=2):
        seen = {a.repository: a.verdict for a in run}
        if set(seen) != set(baseline):
            missing = sorted(set(baseline) ^ set(seen))
            disagreements.append(f"run {idx} coverage differs: {', '.join(missing)}")
        for repo in sorted(set(seen) & set(baseline)):
            if seen[repo] is not baseline[repo]:
                disagreements.append(
                    f"{repo}: run 1 said {baseline[repo].value}, run {idx} said {seen[repo].value}"
                )
    status = "HOLD" if disagreements else "OK"
    return StabilityReport(status=status, runs=len(runs), disagreements=tuple(disagreements))
