"""Portfolio Auditor M1 — evidence model, verdict vocabulary, scoring guards.

RED-first contract for src/pmpe/portfolio/models.py. The vocabulary and the
guards here are locked product decisions carried over from the archived
prototype contract (PD-PA-01..07): findings need structured evidence plus a
confidence value, corroboration is keyed by evidence *origin*, hard AI-slop
verdicts are confidence- and counter-evidence-gated, and a numeric score never
overrides a material high-confidence finding.
"""

from __future__ import annotations

import pytest

from pmpe.portfolio.models import (
    AISlopVerdict,
    BusinessAccuracyVerdict,
    EvidenceRef,
    Finding,
    RecommendationVerdict,
    Severity,
    SlopPolicy,
    blocking_findings,
    clamp_confidence,
    distinct_origins,
    gate_slop_verdict,
    is_corroborated,
    must_surface,
    prioritization_score,
    severity_rank,
)


def _evidence(origin: str, ref: str = "README.md#L1") -> EvidenceRef:
    return EvidenceRef(
        evidence_id=f"EV-{origin}-{ref}",
        kind="repo_file_line",
        origin=origin,
        reference=ref,
        content_digest="sha256:" + "0" * 64,
    )


def _finding(
    severity: Severity = Severity.HIGH,
    confidence: int = 80,
    origins: tuple[str, ...] = ("source_code", "commit_history"),
) -> Finding:
    return Finding(
        finding_id="PA-F-001",
        repository="acme/healthy-lib",
        dimension="technical_health",
        summary="tests never run in CI",
        evidence=[_evidence(o) for o in origins],
        confidence=confidence,
        severity=severity,
        affected_capability="tests_ci_evaluations",
        reasoning="CI workflow exists but has no test step.",
        remediation_recommendation="Add a test job to the workflow.",
    )


_SLOP_POLICY = SlopPolicy(
    hard_verdict_min_confidence=70,
    require_counter_evidence_review=True,
    forbidden_sole_bases=(
        "writing_style",
        "disclosed_ai_assistance",
        "commit_volume",
        "repository_size",
        "generated_file_count",
        "lack_of_popularity",
    ),
)


class TestVocabulary:
    def test_recommendation_verdicts_are_the_five_locked_decisions(self) -> None:
        assert {v.value for v in RecommendationVerdict} == {
            "FIX",
            "SHOWCASE",
            "CONSOLIDATE",
            "REBUILD",
            "KEEP_AS_IS",
        }

    def test_slop_verdicts_are_three_and_never_personal(self) -> None:
        assert {v.value for v in AISlopVerdict} == {
            "AI_SLOP",
            "NOT_AI_SLOP",
            "INSUFFICIENT_EVIDENCE",
        }

    def test_business_accuracy_scale(self) -> None:
        assert {v.value for v in BusinessAccuracyVerdict} == {
            "PROVEN",
            "LIKELY",
            "NOT_PROVEN",
            "CONTRADICTED",
            "INSUFFICIENT_EVIDENCE",
        }

    def test_severity_rank_orders_blocking_most_severe(self) -> None:
        ordered = sorted(Severity, key=severity_rank)
        assert ordered[0] is Severity.BLOCKING
        assert ordered[-1] is Severity.INFO


class TestConfidenceAndFinding:
    def test_confidence_clamps_into_0_100(self) -> None:
        assert clamp_confidence(-5) == 0
        assert clamp_confidence(140) == 100
        assert clamp_confidence(70) == 70

    def test_finding_clamps_confidence_on_construction(self) -> None:
        assert _finding(confidence=250).confidence == 100

    def test_finding_requires_evidence(self) -> None:
        with pytest.raises(ValueError, match="evidence"):
            _finding(origins=())

    def test_finding_round_trips_through_dict(self) -> None:
        f = _finding()
        assert Finding.from_dict(f.to_dict()) == f

    def test_blocking_findings_filters_only_blocking(self) -> None:
        fs = [_finding(Severity.BLOCKING), _finding(Severity.HIGH), _finding(Severity.INFO)]
        assert [f.severity for f in blocking_findings(fs)] == [Severity.BLOCKING]


class TestCorroboration:
    def test_same_origin_evidence_counts_once(self) -> None:
        f = _finding(origins=("readme", "readme"))
        assert distinct_origins(f.evidence) == 1

    def test_normal_finding_needs_two_origins(self) -> None:
        assert is_corroborated(
            _finding(Severity.MEDIUM, origins=("readme", "source_code")),
            min_origins_normal=2,
            min_origins_high_impact=3,
        )
        assert not is_corroborated(
            _finding(Severity.MEDIUM, origins=("readme", "readme")),
            min_origins_normal=2,
            min_origins_high_impact=3,
        )

    def test_high_impact_finding_needs_three_origins(self) -> None:
        two = _finding(Severity.BLOCKING, origins=("readme", "source_code"))
        three = _finding(Severity.BLOCKING, origins=("readme", "source_code", "commit_history"))
        assert not is_corroborated(two, min_origins_normal=2, min_origins_high_impact=3)
        assert is_corroborated(three, min_origins_normal=2, min_origins_high_impact=3)


class TestScoringGuards:
    def test_prioritization_formula(self) -> None:
        score = prioritization_score(
            strategic_importance=2.0,
            severity_weight=3.0,
            authority_impact=2.0,
            confidence=80,
            remediation_effort=4.0,
        )
        assert score == pytest.approx((2.0 * 3.0 * 2.0 * 80) / 4.0)

    def test_prioritization_rejects_nonpositive_effort(self) -> None:
        with pytest.raises(ValueError, match="remediation_effort"):
            prioritization_score(
                strategic_importance=1.0,
                severity_weight=1.0,
                authority_impact=1.0,
                confidence=50,
                remediation_effort=0.0,
            )

    def test_material_high_confidence_finding_must_surface(self) -> None:
        assert must_surface(_finding(Severity.BLOCKING, confidence=85), high_confidence_floor=70)
        assert must_surface(_finding(Severity.HIGH, confidence=70), high_confidence_floor=70)

    def test_low_severity_or_low_confidence_does_not_force_surfacing(self) -> None:
        assert not must_surface(_finding(Severity.LOW, confidence=95), high_confidence_floor=70)
        assert not must_surface(_finding(Severity.HIGH, confidence=69), high_confidence_floor=70)


class TestSlopGate:
    def test_hard_verdict_below_confidence_floor_downgrades(self) -> None:
        for proposed in (AISlopVerdict.AI_SLOP, AISlopVerdict.NOT_AI_SLOP):
            assert (
                gate_slop_verdict(
                    proposed,
                    confidence=69,
                    counter_evidence_reviewed=True,
                    sole_basis=None,
                    policy=_SLOP_POLICY,
                )
                is AISlopVerdict.INSUFFICIENT_EVIDENCE
            )

    def test_hard_verdict_without_counter_evidence_review_downgrades(self) -> None:
        assert (
            gate_slop_verdict(
                AISlopVerdict.AI_SLOP,
                confidence=95,
                counter_evidence_reviewed=False,
                sole_basis=None,
                policy=_SLOP_POLICY,
            )
            is AISlopVerdict.INSUFFICIENT_EVIDENCE
        )

    def test_gated_hard_verdict_passes_when_fully_supported(self) -> None:
        assert (
            gate_slop_verdict(
                AISlopVerdict.AI_SLOP,
                confidence=70,
                counter_evidence_reviewed=True,
                sole_basis=None,
                policy=_SLOP_POLICY,
            )
            is AISlopVerdict.AI_SLOP
        )

    def test_forbidden_sole_basis_forces_insufficient_evidence(self) -> None:
        for basis in _SLOP_POLICY.forbidden_sole_bases:
            assert (
                gate_slop_verdict(
                    AISlopVerdict.AI_SLOP,
                    confidence=95,
                    counter_evidence_reviewed=True,
                    sole_basis=basis,
                    policy=_SLOP_POLICY,
                )
                is AISlopVerdict.INSUFFICIENT_EVIDENCE
            )

    def test_insufficient_evidence_passes_through_ungated(self) -> None:
        assert (
            gate_slop_verdict(
                AISlopVerdict.INSUFFICIENT_EVIDENCE,
                confidence=0,
                counter_evidence_reviewed=False,
                sole_basis=None,
                policy=_SLOP_POLICY,
            )
            is AISlopVerdict.INSUFFICIENT_EVIDENCE
        )
