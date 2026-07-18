"""Portfolio Auditor M4 — deep inspection (RED-first).

Deep inspection turns broad-scan signals plus repository snapshots into:
findings (all seven contract-required fields, schema-valid, redacted),
mechanically-honest business-claim grades, and 0-100 dimension scores.
Locked rules: unsupported claims never grade above NOT_PROVEN and the
mechanical grader can never emit PROVEN or CONTRADICTED (those demand
evidence kinds V1 mechanical inspection cannot observe — PD-PA-03,
absence != falsehood); a LIKELY grade needs the policy corroboration
floor of independent origins (AC-PA-004); a numeric dimension score never
buries a material high-confidence finding; inspection binds the snapshot
content digest and fails loudly if the source mutates mid-run.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pmpe.domain.errors import PmpeError
from pmpe.portfolio.datasource import FixtureRepositorySource
from pmpe.portfolio.inspection import (
    DeepInspection,
    inspect_repository,
    inspect_selected,
)
from pmpe.portfolio.models import BusinessAccuracyVerdict, Severity, must_surface
from pmpe.portfolio.policy import load_policy, validate_finding_dict
from pmpe.portfolio.scanner import scan_repository

FIXTURES = (
    Path(__file__).resolve().parents[2]
    / "evals"
    / "fixtures"
    / "portfolio_auditor"
    / "demo-portfolio"
)
NOW = "2026-07-18T00:00:00+00:00"


def _source() -> FixtureRepositorySource:
    return FixtureRepositorySource(FIXTURES)


def _inspect(name: str) -> DeepInspection:
    source = _source()
    scan = scan_repository(source, "acme", name, now=NOW)
    return inspect_repository(source, scan, policy=load_policy())


class TestFindings:
    def test_planted_secret_yields_blocking_schema_valid_finding(self) -> None:
        insp = _inspect("slop-wrapper")
        secret_findings = [
            f for f in insp.findings if f.dimension == "security_dependency_integrity"
        ]
        assert secret_findings, "planted secret must produce a finding"
        blocking = [f for f in secret_findings if f.severity is Severity.BLOCKING]
        assert blocking
        for f in insp.findings:
            assert validate_finding_dict(f.to_dict()) == [], f.finding_id

    def test_finding_output_never_contains_secret_values(self) -> None:
        for name in ("slop-wrapper", "internal-service"):
            blob = json.dumps(_inspect(name).to_dict())
            assert "EXAMPLE_placeholder" not in blob
            assert "FAKE_placeholder" not in blob

    def test_healthy_repo_has_no_blocking_findings(self) -> None:
        insp = _inspect("healthy-lib")
        assert [f for f in insp.findings if f.severity is Severity.BLOCKING] == []

    def test_claim_gap_produces_finding_with_evidence(self) -> None:
        insp = _inspect("slop-wrapper")
        gap = [f for f in insp.findings if f.dimension == "claim_to_evidence_integrity"]
        assert gap
        for f in gap:
            assert f.evidence and f.reasoning and f.remediation_recommendation


class TestClaimGrading:
    def test_unsupported_claims_never_grade_above_not_proven(self) -> None:
        insp = _inspect("slop-wrapper")
        assert insp.claim_grades, "planted claims must be graded"
        for grade in insp.claim_grades:
            assert grade.verdict in (
                BusinessAccuracyVerdict.NOT_PROVEN,
                BusinessAccuracyVerdict.INSUFFICIENT_EVIDENCE,
            ), f"{grade.claim.text!r} graded {grade.verdict}"

    def test_mechanical_grader_never_emits_proven_or_contradicted(self) -> None:
        for name in ("healthy-lib", "slop-wrapper", "stale-fork", "internal-service"):
            for grade in _inspect(name).claim_grades:
                assert grade.verdict is not BusinessAccuracyVerdict.PROVEN
                assert grade.verdict is not BusinessAccuracyVerdict.CONTRADICTED

    def test_supported_production_claim_grades_likely_with_corroboration(self) -> None:
        # healthy-lib has tests-in-CI, lockfile, docs; graft a production
        # claim onto its README via a wrapper source.
        source = _source()
        files = dict(source.files("acme", "healthy-lib"))
        files["README.md"] = files["README.md"] + "\nThis library is production-ready.\n"
        wrapped = _FilesOverrideSource(source, files)
        scan = scan_repository(wrapped, "acme", "healthy-lib", now=NOW)
        insp = inspect_repository(wrapped, scan, policy=load_policy())
        prod = [g for g in insp.claim_grades if g.claim.category == "production_readiness"]
        assert prod
        policy = load_policy()
        for g in prod:
            assert g.verdict is BusinessAccuracyVerdict.LIKELY
            origins = {e.origin for e in g.supporting_evidence}
            assert len(origins) >= policy.evidence.min_origins_normal

    def test_every_grade_carries_reasoning(self) -> None:
        for grade in _inspect("slop-wrapper").claim_grades:
            assert grade.reasoning


class TestDimensionScores:
    def test_scores_cover_all_dimensions_in_range(self) -> None:
        policy = load_policy()
        insp = _inspect("healthy-lib")
        assert set(insp.dimension_scores) == set(policy.assessment_dimensions)
        for value in insp.dimension_scores.values():
            assert 0 <= value <= 100

    def test_secrets_floor_the_security_score(self) -> None:
        assert (
            _inspect("slop-wrapper").dimension_scores["security_dependency_integrity"]
            < _inspect("healthy-lib").dimension_scores["security_dependency_integrity"]
        )

    def test_healthy_beats_slop_on_tests_dimension(self) -> None:
        assert (
            _inspect("healthy-lib").dimension_scores["tests_ci_evaluations"]
            > _inspect("slop-wrapper").dimension_scores["tests_ci_evaluations"]
        )

    def test_material_findings_are_surfaced_regardless_of_scores(self) -> None:
        policy = load_policy()
        insp = _inspect("slop-wrapper")
        expected = [
            f.finding_id
            for f in insp.findings
            if must_surface(f, high_confidence_floor=policy.scoring.high_confidence_floor)
        ]
        assert expected, "the planted secret finding must be material"
        assert insp.must_surface_finding_ids == tuple(expected)


class TestIntegrityAndDeterminism:
    def test_repeated_inspection_is_byte_identical(self) -> None:
        a = json.dumps(_inspect("slop-wrapper").to_dict())
        b = json.dumps(_inspect("slop-wrapper").to_dict())
        assert a == b

    def test_snapshot_digest_binds_content(self) -> None:
        insp = _inspect("healthy-lib")
        assert insp.snapshot_digest.startswith("sha256:")
        source = _source()
        files = dict(source.files("acme", "healthy-lib"))
        files["README.md"] = files["README.md"] + "\nchanged\n"
        wrapped = _FilesOverrideSource(source, files)
        scan = scan_repository(wrapped, "acme", "healthy-lib", now=NOW)
        changed = inspect_repository(wrapped, scan, policy=load_policy())
        assert changed.snapshot_digest != insp.snapshot_digest

    def test_mutating_source_fails_loudly(self) -> None:
        source = _MutatingSource(_source())
        scan = scan_repository(source, "acme", "healthy-lib", now=NOW)
        with pytest.raises(PmpeError, match="mutated"):
            inspect_repository(source, scan, policy=load_policy())

    def test_inspect_selected_covers_exactly_the_selection(self) -> None:
        source = _source()
        scans = [
            scan_repository(source, "acme", n, now=NOW) for n in ("healthy-lib", "slop-wrapper")
        ]
        results = inspect_selected(
            source, scans, ["acme/healthy-lib", "acme/slop-wrapper"], policy=load_policy()
        )
        assert [r.repository for r in results] == ["acme/healthy-lib", "acme/slop-wrapper"]

    def test_inspect_selected_unknown_repo_fails_loudly(self) -> None:
        source = _source()
        scans = [scan_repository(source, "acme", "healthy-lib", now=NOW)]
        with pytest.raises(PmpeError, match="phantom"):
            inspect_selected(source, scans, ["acme/phantom"], policy=load_policy())

    def test_inspection_round_trips(self) -> None:
        insp = _inspect("slop-wrapper")
        assert DeepInspection.from_dict(insp.to_dict()).to_dict() == insp.to_dict()


class _FilesOverrideSource:
    """Wraps the fixture source with replacement files for one repo."""

    def __init__(self, inner: FixtureRepositorySource, files: dict[str, str]) -> None:
        self._inner = inner
        self._files = files

    def discover(self, owner: str) -> list[str]:
        return self._inner.discover(owner)

    def metadata(self, owner: str, name: str) -> dict[str, object]:
        return self._inner.metadata(owner, name)

    def tree(self, owner: str, name: str) -> list[str]:
        return sorted(set(self._inner.tree(owner, name)) | set(self._files))

    def files(self, owner: str, name: str) -> dict[str, str]:
        return dict(self._files)


class _MutatingSource:
    """Hostile source whose file content changes between reads."""

    def __init__(self, inner: FixtureRepositorySource) -> None:
        self._inner = inner
        self._reads = 0

    def discover(self, owner: str) -> list[str]:
        return self._inner.discover(owner)

    def metadata(self, owner: str, name: str) -> dict[str, object]:
        return self._inner.metadata(owner, name)

    def tree(self, owner: str, name: str) -> list[str]:
        return self._inner.tree(owner, name)

    def files(self, owner: str, name: str) -> dict[str, str]:
        self._reads += 1
        files = dict(self._inner.files(owner, name))
        if self._reads > 1:
            files["README.md"] = files.get("README.md", "") + f"\ntamper {self._reads}\n"
        return files
