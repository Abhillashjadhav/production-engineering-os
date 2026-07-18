"""Portfolio Auditor M2 — broad deterministic repository scanner (RED-first).

The scanner derives *mechanical, observable* signals from repository
snapshots: never model output, never the network, never a judgment. Planted
fixture expectations (demo portfolio): healthy-lib (well-kept Python lib),
slop-wrapper (claim-heavy JS with planted placeholder secrets, no tests/CI/
lockfile), stale-fork (old fork), internal-service (PRIVATE, planted
placeholder key, mixed pinning). Secret values must never appear anywhere in
scanner output — only rule/path/line with a redaction marker (PD-PA-06).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pmpe.portfolio.datasource import (
    FixtureRepositorySource,
    LiveAccessUnavailable,
    LiveRepositorySource,
)
from pmpe.portfolio.scanner import (
    RepoScan,
    detect_secrets,
    extract_mechanical_claims,
    scan_portfolio,
    scan_repository,
)

FIXTURES = (
    Path(__file__).resolve().parents[2]
    / "evals"
    / "fixtures"
    / "portfolio_auditor"
    / "demo-portfolio"
)
NOW = "2026-07-18T00:00:00+00:00"

PLANTED_SECRET_VALUES = (
    "EXAMPLE_placeholder_secret_abcdef0123",
    "aws_secret_FAKE_placeholder_0000",
    "EXAMPLE_placeholder_billing_secret_0002",
)


def _source() -> FixtureRepositorySource:
    return FixtureRepositorySource(FIXTURES)


def _scan(name: str) -> RepoScan:
    return scan_repository(_source(), "acme", name, now=NOW)


class TestDatasource:
    def test_discover_lists_all_repos(self) -> None:
        assert set(_source().discover("acme")) == {
            "healthy-lib",
            "slop-wrapper",
            "stale-fork",
            "internal-service",
        }

    def test_missing_repo_raises_loudly(self) -> None:
        with pytest.raises(LiveAccessUnavailable, match="no-such-repo"):
            _source().metadata("acme", "no-such-repo")

    def test_missing_fixture_root_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            FixtureRepositorySource(tmp_path / "absent")

    def test_live_source_raises_loudly_on_every_method(self) -> None:
        live = LiveRepositorySource()
        for call in (
            lambda: live.discover("acme"),
            lambda: live.metadata("acme", "x"),
            lambda: live.tree("acme", "x"),
            lambda: live.files("acme", "x"),
        ):
            with pytest.raises(LiveAccessUnavailable):
                call()


class TestPortfolioScan:
    def test_scan_portfolio_scans_every_repo_sorted(self) -> None:
        scans = scan_portfolio(_source(), "acme", now=NOW)
        assert [s.name for s in scans] == sorted(
            ["healthy-lib", "slop-wrapper", "stale-fork", "internal-service"]
        )

    def test_repeated_scans_are_byte_identical(self) -> None:
        one = json.dumps([s.to_dict() for s in scan_portfolio(_source(), "acme", now=NOW)])
        two = json.dumps([s.to_dict() for s in scan_portfolio(_source(), "acme", now=NOW)])
        assert one == two

    def test_scan_output_contains_no_verdict(self) -> None:
        # The broad scan records signals only — no premature AI-slop or
        # recommendation verdict may appear anywhere in its output.
        blob = json.dumps([s.to_dict() for s in scan_portfolio(_source(), "acme", now=NOW)])
        for token in ("AI_SLOP", "NOT_AI_SLOP", "SHOWCASE", "REBUILD", "verdict"):
            assert token not in blob

    def test_scan_records_provenance(self) -> None:
        s = _scan("healthy-lib")
        assert s.scanner_version
        assert s.to_dict()["scanner_version"] == s.scanner_version


class TestHealthyLib:
    def test_signals(self) -> None:
        s = _scan("healthy-lib")
        assert "Python" in s.languages
        assert "python" in s.stack
        assert s.docs.has_docs_dir and s.docs.has_contributing
        assert s.docs.license_name == "MIT"
        assert s.tests_ci.has_ci
        assert s.security.has_lockfile and "poetry.lock" in s.security.lockfile_kinds
        assert s.security.pinned_dependencies is True
        assert s.security.secret_hits == []
        assert s.readme.has_readme

    def test_round_trips(self) -> None:
        s = _scan("healthy-lib")
        assert RepoScan.from_dict(s.to_dict()) == s


class TestSlopWrapper:
    def test_secret_detection_fully_redacted(self) -> None:
        s = _scan("slop-wrapper")
        assert s.security.secret_hits, "planted placeholder secrets must be detected"
        assert {h.path for h in s.security.secret_hits} == {"config.js"}
        for h in s.security.secret_hits:
            assert h.rule and h.line > 0
        blob = json.dumps(s.to_dict())
        for value in PLANTED_SECRET_VALUES:
            assert value not in blob, "a secret value leaked into scanner output"

    def test_key_named_assignment_detected(self) -> None:
        s = _scan("slop-wrapper")
        assert any(h.rule == "key_named_assignment" for h in s.security.secret_hits)

    def test_mechanical_claims_extracted(self) -> None:
        s = _scan("slop-wrapper")
        categories = {c.category for c in s.mechanical_claims}
        assert {"production_readiness", "adoption", "superlative", "scale", "metric"} <= categories
        for c in s.mechanical_claims:
            assert c.location.startswith("README.md:")

    def test_risk_signals_without_any_judgment(self) -> None:
        s = _scan("slop-wrapper")
        assert not s.security.has_lockfile
        assert not s.tests_ci.has_tests
        assert not s.tests_ci.has_ci
        assert s.docs.license_name is None


class TestStaleForkAndPrivate:
    def test_stale_fork_flags(self) -> None:
        s = _scan("stale-fork")
        assert s.freshness.is_fork is True
        assert s.freshness.days_since_pushed is not None
        assert s.freshness.days_since_pushed > 500

    def test_private_visibility_recorded_and_secret_redacted(self) -> None:
        s = _scan("internal-service")
        assert s.visibility.value == "PRIVATE"
        assert any(h.path == "app/settings.py" for h in s.security.secret_hits)
        blob = json.dumps(s.to_dict())
        assert "EXAMPLE_placeholder_billing_secret_0002" not in blob

    def test_mixed_pinning_reports_not_pinned(self) -> None:
        # internal-service requirements.txt has requests>=2.31 among exact pins.
        s = _scan("internal-service")
        assert s.security.pinned_dependencies is False


class TestFreshnessClock:
    def test_now_none_gives_no_age(self) -> None:
        s = scan_repository(_source(), "acme", "healthy-lib", now=None)
        assert s.freshness.days_since_pushed is None

    def test_naive_now_degrades_gracefully(self) -> None:
        s = scan_repository(_source(), "acme", "healthy-lib", now="2026-07-18T00:00:00")
        assert s.freshness.days_since_pushed is None


class TestDetectionHelpers:
    def test_pinned_deps_not_fooled_by_x_named_packages(self) -> None:
        source = _source()
        files = {"requirements.txt": "lxml==4.9.3\nsphinx==7.0.0\nopenpyxl==3.1.2\n"}
        fake = _FakeSource(source, files)
        s = scan_repository(fake, "acme", "healthy-lib", now=NOW)
        assert s.security.pinned_dependencies is True

    def test_wildcard_version_is_not_pinned(self) -> None:
        source = _source()
        fake = _FakeSource(source, {"requirements.txt": "somepkg==4.x\n"})
        s = scan_repository(fake, "acme", "healthy-lib", now=NOW)
        assert s.security.pinned_dependencies is False

    def test_detect_secrets_covers_aws_and_stripe_rules(self) -> None:
        files = {
            "cfg.py": ("AWS_ID = 'AKIA" + "A" * 16 + "'\nstripe = 'sk_live_" + "a1" * 10 + "'\n")
        }
        rules = {h.rule for h in detect_secrets(files)}
        assert "aws_access_key_id" in rules
        assert "stripe_secret_key" in rules

    def test_install_commands_capture_python_m_pip(self) -> None:
        readme = "# X\n```bash\npython -m pip install x\nnpm install\n```\n"
        s = _FakeSource(_source(), {"README.md": readme})
        scan = scan_repository(s, "acme", "healthy-lib", now=NOW)
        assert any("python -m pip install x" in c for c in scan.packaging.install_commands)

    def test_claims_report_line_numbers(self) -> None:
        claims = extract_mechanical_claims("plain\n\nblazing fast engine\n")
        assert claims and claims[0].location == "README.md:3"


class _FakeSource:
    """Wraps the fixture source, overriding files() for helper-focused tests."""

    def __init__(self, inner: FixtureRepositorySource, files: dict[str, str]) -> None:
        self._inner = inner
        self._files = files

    def discover(self, owner: str) -> list[str]:
        return self._inner.discover(owner)

    def metadata(self, owner: str, name: str) -> dict[str, object]:
        return self._inner.metadata(owner, name)

    def tree(self, owner: str, name: str) -> list[str]:
        return sorted(self._files)

    def files(self, owner: str, name: str) -> dict[str, str]:
        return self._files
