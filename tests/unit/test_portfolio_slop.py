"""Portfolio Auditor M5 — AI-slop classifier, counter-evidence review, stability.

RED-first. The classifier judges the repository artifact only (PD-PA-01)
from observable evidence-discipline signals. Locked gating: a hard verdict
(AI_SLOP or NOT_AI_SLOP) requires confidence >= the policy floor AND a
completed counter-evidence review; uncertainty defaults to
INSUFFICIENT_EVIDENCE; the six forbidden bases never appear among the
classifier's signals, and disclosed AI assistance is never penalized.
Stability: equivalent inputs (permuted snapshot orderings, repeated runs)
must produce byte-identical assessments; the stability checker reports
HOLD on any verdict flip. Also closes two M4 review notes: RepoScan now
carries the snapshot digest that inspect_repository verifies (TOCTOU), and
superlative claims join the unevaluable categories.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pmpe.portfolio.slop import (
    SlopAssessment,
    classify_slop,
    verify_stability,
)

from pmpe.domain.errors import PmpeError
from pmpe.portfolio.datasource import FixtureRepositorySource
from pmpe.portfolio.inspection import inspect_repository
from pmpe.portfolio.models import AISlopVerdict, BusinessAccuracyVerdict
from pmpe.portfolio.policy import load_policy
from pmpe.portfolio.scanner import scan_repository

FIXTURES = (
    Path(__file__).resolve().parents[2]
    / "evals"
    / "fixtures"
    / "portfolio_auditor"
    / "demo-portfolio"
)
NOW = "2026-07-18T00:00:00+00:00"

FORBIDDEN = {
    "writing_style",
    "disclosed_ai_assistance",
    "commit_volume",
    "repository_size",
    "generated_file_count",
    "lack_of_popularity",
}


def _source() -> FixtureRepositorySource:
    return FixtureRepositorySource(FIXTURES)


def _assess(name: str, source=None) -> SlopAssessment:  # type: ignore[no-untyped-def]
    src = source or _source()
    scan = scan_repository(src, "acme", name, now=NOW)
    inspection = inspect_repository(src, scan, policy=load_policy())
    return classify_slop(scan, inspection, policy=load_policy())


class TestPlantedVerdicts:
    def test_slop_wrapper_is_ai_slop_with_gated_confidence(self) -> None:
        a = _assess("slop-wrapper")
        assert a.verdict is AISlopVerdict.AI_SLOP
        assert a.confidence >= load_policy().slop.hard_verdict_min_confidence
        assert a.counter_evidence_reviewed is True

    def test_healthy_lib_is_not_ai_slop(self) -> None:
        a = _assess("healthy-lib")
        assert a.verdict is AISlopVerdict.NOT_AI_SLOP
        assert a.confidence >= load_policy().slop.hard_verdict_min_confidence
        assert a.counter_evidence_reviewed is True

    def test_stale_fork_is_honestly_uncertain(self) -> None:
        assert _assess("stale-fork").verdict is AISlopVerdict.INSUFFICIENT_EVIDENCE

    def test_internal_service_mixed_discipline_is_uncertain(self) -> None:
        # tests + CI (exculpatory) but committed secret + unpinned deps:
        # neither branch clears its floor — honest uncertainty.
        assert _assess("internal-service").verdict is AISlopVerdict.INSUFFICIENT_EVIDENCE


class TestCounterEvidenceReview:
    def test_review_always_runs_and_is_recorded(self) -> None:
        for name in ("healthy-lib", "slop-wrapper", "stale-fork", "internal-service"):
            a = _assess(name)
            assert a.counter_evidence_reviewed is True
            assert a.counter_evidence_searched, "the searched categories must be recorded"

    def test_slop_wrapper_counter_evidence_found_is_empty(self) -> None:
        assert _assess("slop-wrapper").counter_evidence_found == ()

    def test_healthy_lib_counter_evidence_lists_exculpatory_signals(self) -> None:
        a = _assess("healthy-lib")
        assert a.verdict is AISlopVerdict.NOT_AI_SLOP
        # for a NOT_AI_SLOP proposal the counter-evidence search looks for
        # slop-indicating signals; finding none is the recorded outcome
        assert a.counter_evidence_found == ()

    def test_every_assessment_carries_reasoning(self) -> None:
        for name in ("healthy-lib", "slop-wrapper", "stale-fork", "internal-service"):
            assert _assess(name).reasoning


class TestFairnessRules:
    def test_forbidden_bases_never_appear_as_signals(self) -> None:
        for name in ("healthy-lib", "slop-wrapper", "stale-fork", "internal-service"):
            a = _assess(name)
            assert not (set(a.signals) & FORBIDDEN)
            assert not (set(a.counter_evidence_found) & FORBIDDEN)

    def test_disclosed_ai_assistance_is_never_penalized(self) -> None:
        source = _source()
        files = dict(source.files("acme", "healthy-lib"))
        files["README.md"] = files["README.md"] + (
            "\n## Credits\nBuilt with Claude and GitHub Copilot assistance.\n"
        )
        wrapped = _FilesOverrideSource(source, files)
        a = _assess("healthy-lib", source=wrapped)
        assert a.verdict is AISlopVerdict.NOT_AI_SLOP
        assert not (set(a.signals) & FORBIDDEN)

    def test_verdict_is_about_the_artifact_only(self) -> None:
        d = _assess("slop-wrapper").to_dict()
        assert d["repository"] == "acme/slop-wrapper"
        assert "owner_identity" not in d and "author" not in d


class TestGatingIntegration:
    def test_low_confidence_never_yields_hard_verdict(self) -> None:
        # stale-fork and internal-service sit below both branch floors; the
        # gate guarantees no hard verdict escapes without the confidence floor.
        for name in ("stale-fork", "internal-service"):
            a = _assess(name)
            if a.verdict is not AISlopVerdict.INSUFFICIENT_EVIDENCE:
                assert a.confidence >= load_policy().slop.hard_verdict_min_confidence

    def test_assessment_round_trips(self) -> None:
        a = _assess("slop-wrapper")
        assert SlopAssessment.from_dict(a.to_dict()).to_dict() == a.to_dict()

    def test_no_secret_values_in_assessment(self) -> None:
        blob = json.dumps(_assess("slop-wrapper").to_dict())
        assert "EXAMPLE_placeholder" not in blob


class TestStability:
    def test_repeated_assessment_is_byte_identical(self) -> None:
        assert json.dumps(_assess("slop-wrapper").to_dict()) == json.dumps(
            _assess("slop-wrapper").to_dict()
        )

    def test_permuted_snapshot_order_gives_identical_assessment(self) -> None:
        source = _source()
        files = source.files("acme", "slop-wrapper")
        permuted = dict(reversed(list(files.items())))
        a = _assess("slop-wrapper")
        b = _assess("slop-wrapper", source=_FilesOverrideSource(source, permuted))
        assert json.dumps(a.to_dict()) == json.dumps(b.to_dict())

    def test_verify_stability_ok_on_agreeing_runs(self) -> None:
        run = [_assess("healthy-lib"), _assess("slop-wrapper")]
        report = verify_stability([run, run])
        assert report.status == "OK"
        assert report.disagreements == ()

    def test_verify_stability_holds_on_verdict_flip(self) -> None:
        a = _assess("slop-wrapper")
        flipped = SlopAssessment.from_dict(
            {**a.to_dict(), "verdict": AISlopVerdict.NOT_AI_SLOP.value}
        )
        report = verify_stability([[a], [flipped]])
        assert report.status == "HOLD"
        assert any("acme/slop-wrapper" in d for d in report.disagreements)

    def test_verify_stability_requires_at_least_two_runs(self) -> None:
        with pytest.raises(ValueError, match="two"):
            verify_stability([[_assess("healthy-lib")]])


class TestM4ReviewFollowUps:
    def test_repo_scan_carries_snapshot_digest(self) -> None:
        scan = scan_repository(_source(), "acme", "healthy-lib", now=NOW)
        assert scan.snapshot_digest.startswith("sha256:")

    def test_inspection_rejects_scan_from_different_snapshot(self) -> None:
        # The M4 reviewer's TOCTOU PoC: scan sees one snapshot, inspection
        # another. The digest carried on the scan must close the window.
        source = _source()
        scan = scan_repository(source, "acme", "healthy-lib", now=NOW)
        files = dict(source.files("acme", "healthy-lib"))
        files["README.md"] = files["README.md"] + "\nphase flip\n"
        flipped = _FilesOverrideSource(source, files)
        with pytest.raises(PmpeError, match="snapshot"):
            inspect_repository(flipped, scan, policy=load_policy())

    def test_superlative_claims_are_unevaluable(self) -> None:
        # Even a fully-supported repo cannot substantiate "state-of-the-art".
        source = _source()
        files = dict(source.files("acme", "healthy-lib"))
        files["README.md"] = files["README.md"] + "\nState-of-the-art parsing engine.\n"
        wrapped = _FilesOverrideSource(source, files)
        scan = scan_repository(wrapped, "acme", "healthy-lib", now=NOW)
        insp = inspect_repository(wrapped, scan, policy=load_policy())
        superlatives = [g for g in insp.claim_grades if g.claim.category == "superlative"]
        assert superlatives
        for g in superlatives:
            assert g.verdict is BusinessAccuracyVerdict.INSUFFICIENT_EVIDENCE


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
