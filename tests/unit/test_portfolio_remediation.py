"""Portfolio Auditor M7 — sandbox remediation PRs and the gated merge decision.

RED-first. Remediation PRs are generated ONLY for findings with an honest
mechanical fix (secret removal); patches never contain a secret value and
bind the inspected snapshot digest (PD-PA-05, gate bound_to_inspected_commit).
The merge decision is a pure function that fails closed: all nine policy
gates must be explicitly true, any forbidden action refuses, digest drift
refuses, and a non-sandbox target refuses ALWAYS — nothing real is ever
auto-merged (PD-08). Also closes three M6 review notes: policy threading in
render_dashboard, AI_SLOP-aware KEEP_AS_IS wording, and the SHOWCASE
exclusion pin for AI_SLOP assessments.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pmpe.domain.errors import PmpeError
from pmpe.portfolio.datasource import FixtureRepositorySource
from pmpe.portfolio.inspection import DeepInspection, inspect_repository
from pmpe.portfolio.models import AISlopVerdict, RecommendationVerdict
from pmpe.portfolio.policy import load_policy
from pmpe.portfolio.remediation import (
    MergeDecision,
    RemediationPR,
    SandboxRepo,
    apply_merge,
    decide_merge,
    generate_remediation_prs,
)
from pmpe.portfolio.reporting import recommend, render_dashboard
from pmpe.portfolio.scanner import scan_repository
from pmpe.portfolio.selection import load_strategy
from pmpe.portfolio.slop import SlopAssessment, classify_slop

FIXTURES = (
    Path(__file__).resolve().parents[2]
    / "evals"
    / "fixtures"
    / "portfolio_auditor"
    / "demo-portfolio"
)
NOW = "2026-07-18T00:00:00+00:00"

PLANTED_SECRETS = (
    "EXAMPLE_placeholder_secret_abcdef0123",
    "aws_secret_FAKE_placeholder_0000",
    "EXAMPLE_placeholder_billing_secret_0002",
)


def _pipeline(name: str):  # type: ignore[no-untyped-def]
    source = FixtureRepositorySource(FIXTURES)
    scan = scan_repository(source, "acme", name, now=NOW)
    inspection = inspect_repository(source, scan, policy=load_policy())
    return source, scan, inspection


def _sandbox(name: str) -> SandboxRepo:
    source, scan, inspection = _pipeline(name)
    return SandboxRepo(
        repository=f"acme/{name}",
        files=source.files("acme", name),
        snapshot_digest=inspection.snapshot_digest,
    )


def _all_gates_pass(pr: RemediationPR) -> dict[str, bool]:
    return dict.fromkeys(load_policy().remediation.auto_merge_required_gates, True)


class TestGeneration:
    def test_secret_findings_yield_remediation_prs(self) -> None:
        _, scan, inspection = _pipeline("slop-wrapper")
        prs = generate_remediation_prs(scan, inspection)
        assert prs, "the planted secret must yield a remediation PR"
        pr = prs[0]
        assert pr.repository == "acme/slop-wrapper"
        assert pr.finding_ids and all("-SEC-" in fid for fid in pr.finding_ids)
        assert pr.base_snapshot_digest == inspection.snapshot_digest
        assert pr.sandbox_only is True

    def test_patch_removes_secret_lines_without_carrying_values(self) -> None:
        _, scan, inspection = _pipeline("slop-wrapper")
        pr = generate_remediation_prs(scan, inspection)[0]
        blob = json.dumps(pr.to_dict())
        for secret in PLANTED_SECRETS:
            assert secret not in blob
        patched = pr.patch["config.js"]
        for secret in PLANTED_SECRETS:
            assert secret not in patched
        assert "credential removed" in patched.lower()

    def test_no_pr_for_findings_without_honest_mechanical_fix(self) -> None:
        # claim-gap and lockfile findings need human judgment; generating a
        # fake fix would itself be dishonest (forbidden: insufficient_evidence)
        _, scan, inspection = _pipeline("slop-wrapper")
        prs = generate_remediation_prs(scan, inspection)
        for pr in prs:
            assert all("-SEC-" in fid for fid in pr.finding_ids)

    def test_clean_repo_yields_no_prs(self) -> None:
        _, scan, inspection = _pipeline("healthy-lib")
        assert generate_remediation_prs(scan, inspection) == []

    def test_generation_is_deterministic(self) -> None:
        _, scan, inspection = _pipeline("internal-service")
        a = [p.to_dict() for p in generate_remediation_prs(scan, inspection)]
        b = [p.to_dict() for p in generate_remediation_prs(scan, inspection)]
        assert json.dumps(a) == json.dumps(b)

    def test_pr_round_trips(self) -> None:
        _, scan, inspection = _pipeline("internal-service")
        pr = generate_remediation_prs(scan, inspection)[0]
        assert RemediationPR.from_dict(pr.to_dict()).to_dict() == pr.to_dict()


class TestMergeDecision:
    def test_all_gates_true_in_sandbox_merges(self) -> None:
        _, scan, inspection = _pipeline("slop-wrapper")
        pr = generate_remediation_prs(scan, inspection)[0]
        decision = decide_merge(pr, gates=_all_gates_pass(pr), sandbox=_sandbox("slop-wrapper"))
        assert decision.decision == "MERGE"
        assert decision.failing_gates == ()

    def test_each_single_failing_gate_refuses_naming_it(self) -> None:
        _, scan, inspection = _pipeline("slop-wrapper")
        pr = generate_remediation_prs(scan, inspection)[0]
        for gate in load_policy().remediation.auto_merge_required_gates:
            gates = _all_gates_pass(pr)
            gates[gate] = False
            decision = decide_merge(pr, gates=gates, sandbox=_sandbox("slop-wrapper"))
            assert decision.decision == "REFUSE"
            assert gate in decision.failing_gates

    def test_missing_gate_key_fails_closed(self) -> None:
        _, scan, inspection = _pipeline("slop-wrapper")
        pr = generate_remediation_prs(scan, inspection)[0]
        gates = _all_gates_pass(pr)
        del gates["independent_review_approve"]
        decision = decide_merge(pr, gates=gates, sandbox=_sandbox("slop-wrapper"))
        assert decision.decision == "REFUSE"
        assert "independent_review_approve" in decision.failing_gates

    def test_any_forbidden_action_refuses(self) -> None:
        _, scan, inspection = _pipeline("slop-wrapper")
        pr = generate_remediation_prs(scan, inspection)[0]
        for action in load_policy().remediation.forbidden_auto_merge_actions:
            flagged = RemediationPR.from_dict({**pr.to_dict(), "flags": [action]})
            decision = decide_merge(
                flagged, gates=_all_gates_pass(pr), sandbox=_sandbox("slop-wrapper")
            )
            assert decision.decision == "REFUSE"
            assert action in decision.forbidden_hits

    def test_snapshot_drift_refuses(self) -> None:
        _, scan, inspection = _pipeline("slop-wrapper")
        pr = generate_remediation_prs(scan, inspection)[0]
        sandbox = _sandbox("slop-wrapper")
        drifted = SandboxRepo(
            repository=sandbox.repository,
            files={**sandbox.files, "new.txt": "drift"},
            snapshot_digest="sha256:" + "0" * 64,
        )
        decision = decide_merge(pr, gates=_all_gates_pass(pr), sandbox=drifted)
        assert decision.decision == "REFUSE"
        assert "bound_to_inspected_commit" in decision.failing_gates

    def test_non_sandbox_target_always_refuses(self) -> None:
        _, scan, inspection = _pipeline("slop-wrapper")
        pr = generate_remediation_prs(scan, inspection)[0]
        real = RemediationPR.from_dict({**pr.to_dict(), "sandbox_only": False})
        decision = decide_merge(real, gates=_all_gates_pass(pr), sandbox=_sandbox("slop-wrapper"))
        assert decision.decision == "REFUSE"
        assert any("sandbox" in r.lower() for r in (decision.reasoning,))

    def test_repository_mismatch_refuses(self) -> None:
        _, scan, inspection = _pipeline("slop-wrapper")
        pr = generate_remediation_prs(scan, inspection)[0]
        decision = decide_merge(pr, gates=_all_gates_pass(pr), sandbox=_sandbox("healthy-lib"))
        assert decision.decision == "REFUSE"

    def test_decision_round_trips(self) -> None:
        _, scan, inspection = _pipeline("slop-wrapper")
        pr = generate_remediation_prs(scan, inspection)[0]
        d = decide_merge(pr, gates=_all_gates_pass(pr), sandbox=_sandbox("slop-wrapper"))
        assert MergeDecision.from_dict(d.to_dict()).to_dict() == d.to_dict()


class TestApplyMerge:
    def test_apply_on_merge_returns_patched_files(self) -> None:
        _, scan, inspection = _pipeline("slop-wrapper")
        pr = generate_remediation_prs(scan, inspection)[0]
        sandbox = _sandbox("slop-wrapper")
        decision = decide_merge(pr, gates=_all_gates_pass(pr), sandbox=sandbox)
        patched = apply_merge(sandbox, pr, decision)
        for secret in PLANTED_SECRETS[:2]:
            assert secret not in json.dumps(patched)
        assert set(patched) == set(sandbox.files)

    def test_apply_on_refuse_raises(self) -> None:
        _, scan, inspection = _pipeline("slop-wrapper")
        pr = generate_remediation_prs(scan, inspection)[0]
        sandbox = _sandbox("slop-wrapper")
        gates = _all_gates_pass(pr)
        gates["substantive_ci_green"] = False
        decision = decide_merge(pr, gates=gates, sandbox=sandbox)
        with pytest.raises(PmpeError, match="REFUSE"):
            apply_merge(sandbox, pr, decision)


class TestM6ReviewFollowUps:
    def test_dashboard_accepts_policy_and_renders_its_digest(self) -> None:
        policy = load_policy()
        board = render_dashboard(
            [], backlog=[], run={"run_id": "x", "generated_at": NOW}, policy=policy
        )
        assert policy.digest in board

    def test_keep_as_is_wording_acknowledges_ai_slop(self) -> None:
        # A bare repo classifies AI_SLOP with zero findings; KEEP_AS_IS
        # reasoning must acknowledge the verdict, not say "fine as it is".
        source = FixtureRepositorySource(FIXTURES)
        scan = scan_repository(source, "acme", "stale-fork", now=NOW)
        scan_dict = scan.to_dict()
        scan_dict["freshness"]["is_fork"] = False
        scan_dict["freshness"]["days_since_pushed"] = 30
        from pmpe.portfolio.scanner import RepoScan

        bare_scan = RepoScan.from_dict(scan_dict)
        inspection = inspect_repository(source, scan, policy=load_policy())
        slop_assessment = SlopAssessment.from_dict(
            {
                **classify_slop(bare_scan, inspection, policy=load_policy()).to_dict(),
                "verdict": AISlopVerdict.AI_SLOP.value,
            }
        )
        verdict, reasoning = recommend(
            scan=bare_scan,
            inspection=inspection,
            assessment=slop_assessment,
            strategy=load_strategy(FIXTURES / "strategy.json"),
            policy=load_policy(),
        )
        if verdict is RecommendationVerdict.KEEP_AS_IS:
            assert "AI_SLOP" in reasoning
            assert "fine as it is" not in reasoning

    def test_showcase_is_never_returned_for_ai_slop_assessment(self) -> None:
        # Defense-in-depth pin: even a forged perfect inspection cannot make
        # an AI_SLOP-classified repo SHOWCASE.
        source, scan, inspection = _pipeline("healthy-lib")
        forged = DeepInspection.from_dict(inspection.to_dict())
        forged.dimension_scores = dict.fromkeys(forged.dimension_scores, 100)
        forged.findings = []
        forged.must_surface_finding_ids = ()
        assessment = SlopAssessment.from_dict(
            {
                **classify_slop(scan, inspection, policy=load_policy()).to_dict(),
                "verdict": AISlopVerdict.AI_SLOP.value,
            }
        )
        verdict, _ = recommend(
            scan=scan,
            inspection=forged,
            assessment=assessment,
            strategy=load_strategy(FIXTURES / "strategy.json"),
            policy=load_policy(),
        )
        assert verdict is not RecommendationVerdict.SHOWCASE
