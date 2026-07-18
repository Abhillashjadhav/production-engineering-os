"""Portfolio Auditor M6 — recommendation, backlog, scorecards, dashboard.

RED-first. The recommendation ladder is deterministic and honors the
locked guard: a numeric score never overrides a material high-confidence
finding — a repository with one can never be SHOWCASE or KEEP_AS_IS.
Every backlog entry traces to a finding id (AC-PA-006), must-surface
findings are always in the backlog regardless of score, and all renderers
are pure functions of recorded evidence: byte-identical repeats, no wall
clock (run metadata is a parameter), no secret values, honest labeling of
repositories that received only a broad scan.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pmpe.portfolio.datasource import FixtureRepositorySource
from pmpe.portfolio.inspection import DeepInspection, inspect_repository
from pmpe.portfolio.models import RecommendationVerdict, Severity
from pmpe.portfolio.policy import load_policy
from pmpe.portfolio.reporting import (
    BacklogItem,
    RepoReport,
    build_backlog,
    build_repo_report,
    recommend,
    render_dashboard,
    render_scorecard,
)
from pmpe.portfolio.scanner import scan_repository
from pmpe.portfolio.selection import load_strategy
from pmpe.portfolio.slop import classify_slop

FIXTURES = (
    Path(__file__).resolve().parents[2]
    / "evals"
    / "fixtures"
    / "portfolio_auditor"
    / "demo-portfolio"
)
NOW = "2026-07-18T00:00:00+00:00"
RUN_META = {"run_id": "pa-demo-001", "generated_at": NOW}


def _report(name: str) -> RepoReport:
    source = FixtureRepositorySource(FIXTURES)
    scan = scan_repository(source, "acme", name, now=NOW)
    inspection = inspect_repository(source, scan, policy=load_policy())
    assessment = classify_slop(scan, inspection, policy=load_policy())
    return build_repo_report(
        scan=scan,
        inspection=inspection,
        assessment=assessment,
        strategy=load_strategy(FIXTURES / "strategy.json"),
        policy=load_policy(),
    )


def _all_reports() -> list[RepoReport]:
    return [_report(n) for n in ("healthy-lib", "internal-service", "slop-wrapper", "stale-fork")]


class TestRecommendationLadder:
    def test_slop_wrapper_is_rebuild(self) -> None:
        assert _report("slop-wrapper").recommendation is RecommendationVerdict.REBUILD

    def test_internal_service_is_fix(self) -> None:
        # material high-confidence secret finding forces at least FIX
        assert _report("internal-service").recommendation is RecommendationVerdict.FIX

    def test_healthy_lib_is_showcase(self) -> None:
        assert _report("healthy-lib").recommendation is RecommendationVerdict.SHOWCASE

    def test_stale_fork_is_consolidate(self) -> None:
        assert _report("stale-fork").recommendation is RecommendationVerdict.CONSOLIDATE

    def test_every_recommendation_carries_reasoning(self) -> None:
        for r in _all_reports():
            assert r.recommendation_reasoning

    def test_material_finding_never_showcase_or_keep(self) -> None:
        # The locked guard, probed directly: perfect scores plus one material
        # high-confidence finding must never yield SHOWCASE or KEEP_AS_IS.
        base = _report("internal-service")
        perfect = DeepInspection.from_dict(base.inspection.to_dict())
        perfect.dimension_scores = dict.fromkeys(perfect.dimension_scores, 100)
        verdict = recommend(
            scan=base.scan,
            inspection=perfect,
            assessment=base.assessment,
            strategy=load_strategy(FIXTURES / "strategy.json"),
            policy=load_policy(),
        )[0]
        assert verdict not in (
            RecommendationVerdict.SHOWCASE,
            RecommendationVerdict.KEEP_AS_IS,
        )

    def test_plain_repo_without_findings_is_keep_as_is(self) -> None:
        # stale-fork stripped of its fork flag becomes an ordinary quiet
        # repo: no material findings, not showcase-grade, nothing to fix.
        base = _report("stale-fork")
        scan_dict = base.scan.to_dict()
        scan_dict["freshness"]["is_fork"] = False
        scan_dict["freshness"]["days_since_pushed"] = 30
        from pmpe.portfolio.scanner import RepoScan

        verdict = recommend(
            scan=RepoScan.from_dict(scan_dict),
            inspection=base.inspection,
            assessment=base.assessment,
            strategy=load_strategy(FIXTURES / "strategy.json"),
            policy=load_policy(),
        )[0]
        assert verdict is RecommendationVerdict.KEEP_AS_IS


class TestBacklog:
    def test_every_entry_traces_to_a_finding(self) -> None:
        reports = _all_reports()
        backlog = build_backlog(reports, policy=load_policy())
        all_finding_ids = {f.finding_id for r in reports for f in r.inspection.findings}
        assert backlog, "planted findings must produce backlog entries"
        for item in backlog:
            assert item.finding_id in all_finding_ids
            assert item.repository and item.remediation and item.priority > 0

    def test_must_surface_findings_always_in_backlog(self) -> None:
        reports = _all_reports()
        backlog_ids = {b.finding_id for b in build_backlog(reports, policy=load_policy())}
        for r in reports:
            for fid in r.inspection.must_surface_finding_ids:
                assert fid in backlog_ids

    def test_backlog_sorted_by_priority_then_id(self) -> None:
        backlog = build_backlog(_all_reports(), policy=load_policy())
        keys = [(-b.priority, b.finding_id) for b in backlog]
        assert keys == sorted(keys)

    def test_blocking_secret_outranks_medium_dependency_hygiene(self) -> None:
        backlog = build_backlog(_all_reports(), policy=load_policy())
        by_id = {b.finding_id: b for b in backlog}
        sec = next(b for i, b in by_id.items() if "-SEC-" in i)
        dep = next((b for i, b in by_id.items() if "-DEP-" in i), None)
        if dep is not None:
            assert sec.priority > dep.priority

    def test_strategic_repo_findings_get_multiplier(self) -> None:
        # internal-service is strategic; its secret finding must outrank an
        # identical-severity finding on a non-strategic repo.
        backlog = build_backlog(_all_reports(), policy=load_policy())
        strategic_sec = next(
            b
            for b in backlog
            if b.repository == "acme/internal-service" and "-SEC-" in b.finding_id
        )
        plain_sec = next(
            b for b in backlog if b.repository == "acme/slop-wrapper" and "-SEC-" in b.finding_id
        )
        assert strategic_sec.priority > plain_sec.priority

    def test_backlog_round_trips(self) -> None:
        item = build_backlog(_all_reports(), policy=load_policy())[0]
        assert BacklogItem.from_dict(item.to_dict()) == item


class TestRenderers:
    def test_scorecard_contains_verdicts_scores_and_finding_ids(self) -> None:
        r = _report("slop-wrapper")
        card = render_scorecard(r, run=RUN_META)
        assert "acme/slop-wrapper" in card
        assert "AI_SLOP" in card and "REBUILD" in card
        for f in r.inspection.findings:
            assert f.finding_id in card
        assert r.inspection.snapshot_digest in card

    def test_scorecard_never_contains_secret_values(self) -> None:
        for name in ("slop-wrapper", "internal-service"):
            card = render_scorecard(_report(name), run=RUN_META)
            assert "EXAMPLE_placeholder" not in card
            assert "FAKE_placeholder" not in card

    def test_dashboard_covers_every_report_with_provenance(self) -> None:
        reports = _all_reports()
        board = render_dashboard(
            reports, backlog=build_backlog(reports, policy=load_policy()), run=RUN_META
        )
        for r in reports:
            assert r.repository in board
        assert RUN_META["run_id"] in board
        assert load_policy().digest in board

    def test_dashboard_is_byte_identical_across_runs(self) -> None:
        reports = _all_reports()
        backlog = build_backlog(reports, policy=load_policy())
        a = render_dashboard(reports, backlog=backlog, run=RUN_META)
        b = render_dashboard(_all_reports(), backlog=backlog, run=RUN_META)
        assert a == b

    def test_dashboard_run_metadata_is_injected_not_read(self) -> None:
        reports = _all_reports()
        backlog = build_backlog(reports, policy=load_policy())
        board = render_dashboard(
            reports, backlog=backlog, run={"run_id": "other", "generated_at": "2020-01-01"}
        )
        assert "other" in board and "2020-01-01" in board

    def test_report_round_trips(self) -> None:
        r = _report("healthy-lib")
        assert RepoReport.from_dict(r.to_dict()).to_dict() == r.to_dict()

    def test_reports_include_broad_scan_only_honesty(self) -> None:
        # A repo without inspection/assessment renders honestly as
        # broad-scan-only: no slop verdict, no recommendation invented.
        source = FixtureRepositorySource(FIXTURES)
        scan = scan_repository(source, "acme", "stale-fork", now=NOW)
        broad_only = RepoReport(
            repository="acme/stale-fork",
            scan=scan,
            inspection=None,
            assessment=None,
            recommendation=None,
            recommendation_reasoning="",
        )
        board = render_dashboard([broad_only], backlog=[], run=RUN_META)
        assert "broad scan only" in board.lower()
        with pytest.raises(ValueError, match="broad"):
            render_scorecard(broad_only, run=RUN_META)


class TestSeverityWeights:
    def test_severity_weight_order_matches_rank(self) -> None:
        from pmpe.portfolio.reporting import severity_weight

        weights = [severity_weight(s) for s in Severity]
        assert weights == sorted(weights, reverse=True)
        assert severity_weight(Severity.BLOCKING) > severity_weight(Severity.HIGH)
