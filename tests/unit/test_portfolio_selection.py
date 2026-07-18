"""Portfolio Auditor M3 — strategic config, risk ranking, deep-scan selection.

RED-first. The operator supplies the strategic/marketable repository list
via configuration, never source code (PD-PA-02); an absent configuration
fails loudly (AC-PA-003). Risk ranking is a deterministic function of
broad-scan signals; selection is a deterministic function of (strategy,
ranking) with a traceable reason per selected repository. No verdict of
any kind appears in ranking or selection output.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pmpe.portfolio.selection import (
    RepoRisk,
    SelectionReport,
    load_strategy,
    rank_risks,
    select_for_deep_scan,
    strategy_schema_path,
)

from pmpe.domain.errors import ConfigError
from pmpe.portfolio.datasource import FixtureRepositorySource
from pmpe.portfolio.scanner import scan_portfolio

FIXTURES = (
    Path(__file__).resolve().parents[2]
    / "evals"
    / "fixtures"
    / "portfolio_auditor"
    / "demo-portfolio"
)
NOW = "2026-07-18T00:00:00+00:00"


def _scans():  # type: ignore[no-untyped-def]
    return scan_portfolio(FixtureRepositorySource(FIXTURES), "acme", now=NOW)


def _strategy_data() -> dict[str, object]:
    return json.loads((FIXTURES / "strategy.json").read_text())


def _write(tmp_path: Path, data: dict[str, object]) -> Path:
    p = tmp_path / "strategy.json"
    p.write_text(json.dumps(data))
    return p


class TestStrategyConfig:
    def test_demo_strategy_loads_and_validates(self) -> None:
        strategy = load_strategy(FIXTURES / "strategy.json")
        assert "acme/healthy-lib" in strategy.marketable_repositories
        assert "acme/internal-service" in strategy.strategic_repositories
        assert strategy.deep_scan_quota >= 1

    def test_absent_configuration_fails_loudly(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="strategy"):
            load_strategy(tmp_path / "missing.json")

    def test_schema_file_exists_and_rejects_missing_fields(self, tmp_path: Path) -> None:
        assert strategy_schema_path().is_file()
        data = _strategy_data()
        del data["deep_scan_quota"]
        with pytest.raises(ConfigError, match="deep_scan_quota"):
            load_strategy(_write(tmp_path, data))

    def test_nonpositive_quota_fails_closed(self, tmp_path: Path) -> None:
        data = _strategy_data()
        data["deep_scan_quota"] = 0
        with pytest.raises(ConfigError, match="deep_scan_quota"):
            load_strategy(_write(tmp_path, data))


class TestRiskRanking:
    def test_ranking_is_deterministic_and_complete(self) -> None:
        risks_a = rank_risks(_scans())
        risks_b = rank_risks(_scans())
        assert [r.to_dict() for r in risks_a] == [r.to_dict() for r in risks_b]
        assert {r.repository for r in risks_a} == {
            "acme/healthy-lib",
            "acme/slop-wrapper",
            "acme/stale-fork",
            "acme/internal-service",
        }

    def test_planted_secret_dominates_risk(self) -> None:
        risks = {r.repository: r for r in rank_risks(_scans())}
        assert risks["acme/slop-wrapper"].score > risks["acme/healthy-lib"].score
        assert risks["acme/internal-service"].score > risks["acme/healthy-lib"].score
        assert "secret_hits" in risks["acme/slop-wrapper"].factors

    def test_claim_to_evidence_gap_raises_risk(self) -> None:
        # slop-wrapper: heavy claims, no tests, no CI → the gap factor fires.
        risks = {r.repository: r for r in rank_risks(_scans())}
        assert "claim_to_evidence_gap" in risks["acme/slop-wrapper"].factors
        assert "claim_to_evidence_gap" not in risks["acme/healthy-lib"].factors

    def test_staleness_and_fork_are_factors(self) -> None:
        risks = {r.repository: r for r in rank_risks(_scans())}
        assert "stale" in risks["acme/stale-fork"].factors
        assert "fork" in risks["acme/stale-fork"].factors

    def test_healthy_repo_scores_lowest(self) -> None:
        ordered = rank_risks(_scans())
        assert ordered == sorted(ordered, key=lambda r: (-r.score, r.repository))
        assert ordered[-1].repository == "acme/healthy-lib"

    def test_risk_output_contains_no_verdict(self) -> None:
        blob = json.dumps([r.to_dict() for r in rank_risks(_scans())])
        for token in ("AI_SLOP", "NOT_AI_SLOP", "SHOWCASE", "REBUILD", "verdict"):
            assert token not in blob

    def test_risk_round_trips(self) -> None:
        r = rank_risks(_scans())[0]
        assert RepoRisk.from_dict(r.to_dict()) == r


class TestSelection:
    def test_strategic_and_marketable_always_selected(self) -> None:
        report = select_for_deep_scan(
            _scans(), load_strategy(FIXTURES / "strategy.json"), rank_risks(_scans())
        )
        selected = {s.repository for s in report.selected}
        assert "acme/healthy-lib" in selected  # marketable
        assert "acme/internal-service" in selected  # strategic

    def test_reasons_are_traceable(self) -> None:
        report = select_for_deep_scan(
            _scans(), load_strategy(FIXTURES / "strategy.json"), rank_risks(_scans())
        )
        for entry in report.selected:
            assert entry.reason, f"{entry.repository} selected without a reason"

    def test_quota_bounds_risk_based_selection(self, tmp_path: Path) -> None:
        data = _strategy_data()
        data["strategic_repositories"] = []
        data["marketable_repositories"] = []
        data["genai_authority_repositories"] = []
        data["deep_scan_quota"] = 1
        strategy = load_strategy(_write(tmp_path, data))
        report = select_for_deep_scan(_scans(), strategy, rank_risks(_scans()))
        assert len(report.selected) == 1
        # highest-risk repo wins the single slot
        assert report.selected[0].repository == rank_risks(_scans())[0].repository

    def test_strategic_selection_exceeds_quota_when_needed(self, tmp_path: Path) -> None:
        # Strategy lists always deep-scan even when the quota is tiny; the
        # quota bounds only the risk-based additions.
        data = _strategy_data()
        data["deep_scan_quota"] = 1
        strategy = load_strategy(_write(tmp_path, data))
        report = select_for_deep_scan(_scans(), strategy, rank_risks(_scans()))
        selected = {s.repository for s in report.selected}
        assert {"acme/healthy-lib", "acme/internal-service"} <= selected

    def test_unknown_strategy_repo_fails_loudly(self, tmp_path: Path) -> None:
        data = _strategy_data()
        strategic = data["strategic_repositories"]
        assert isinstance(strategic, list)
        strategic.append("acme/does-not-exist")
        strategy = load_strategy(_write(tmp_path, data))
        with pytest.raises(ConfigError, match="does-not-exist"):
            select_for_deep_scan(_scans(), strategy, rank_risks(_scans()))

    def test_selection_is_deterministic(self) -> None:
        strategy = load_strategy(FIXTURES / "strategy.json")
        a = select_for_deep_scan(_scans(), strategy, rank_risks(_scans()))
        b = select_for_deep_scan(_scans(), strategy, rank_risks(_scans()))
        assert json.dumps(a.to_dict()) == json.dumps(b.to_dict())

    def test_not_selected_repos_are_recorded(self) -> None:
        report = select_for_deep_scan(
            _scans(), load_strategy(FIXTURES / "strategy.json"), rank_risks(_scans())
        )
        assert isinstance(report, SelectionReport)
        all_repos = {s.repository for s in report.selected} | set(report.not_selected)
        assert all_repos == {r.repository for r in rank_risks(_scans())}
