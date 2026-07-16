"""PD-09: the deployment ladder — local/test automatic, staging gated on assurance,
production gated on a named approval bound to the candidate digest."""

from __future__ import annotations

from pathlib import Path

import pytest

from pmpe.deployment.policy import (
    DeploymentPolicy,
    ProductionApproval,
    load_production_approval,
    production_readiness,
    write_production_approval,
)
from pmpe.deployment.simulated import simulate_production_deploy

CAND = "sha256:cand-live"


@pytest.fixture()
def policy() -> DeploymentPolicy:
    return DeploymentPolicy()


def _approval(**overrides: object) -> ProductionApproval:
    fields: dict[str, object] = {
        "owner": "abhillash",
        "reason": "pilot cohort launch",
        "target": "production",
        "candidate_digest": CAND,
        "approved_at": "2026-07-16T10:00:00Z",
    }
    fields.update(overrides)
    return ProductionApproval(**fields)  # type: ignore[arg-type]


# --- the ladder -----------------------------------------------------------------------


def test_local_and_test_proceed_automatically_after_required_checks(
    policy: DeploymentPolicy,
) -> None:
    for env in ("local", "test"):
        decision = policy.authorize(env, required_checks_passed=True)
        assert decision.allowed, env


def test_local_blocks_when_required_checks_failed(policy: DeploymentPolicy) -> None:
    decision = policy.authorize("local", required_checks_passed=False)
    assert not decision.allowed


def test_staging_requires_all_assurance_gates(policy: DeploymentPolicy) -> None:
    blocked = policy.authorize("staging", required_checks_passed=True,
                               assurance_gates_passed=False)
    assert not blocked.allowed
    allowed = policy.authorize("staging", required_checks_passed=True,
                               assurance_gates_passed=True)
    assert allowed.allowed


def test_unknown_environment_is_rejected(policy: DeploymentPolicy) -> None:
    with pytest.raises(Exception, match="environment"):
        policy.authorize("prod-eu", required_checks_passed=True)


# --- production approval binding --------------------------------------------------------


def test_production_without_approval_blocks(policy: DeploymentPolicy) -> None:
    decision = policy.authorize(
        "production", required_checks_passed=True, assurance_gates_passed=True,
        candidate_digest=CAND, approval=None,
    )
    assert not decision.allowed
    assert any("approval" in r for r in decision.reasons)


def test_approval_for_an_older_candidate_blocks(policy: DeploymentPolicy) -> None:
    stale = _approval(candidate_digest="sha256:cand-OLD")
    decision = policy.authorize(
        "production", required_checks_passed=True, assurance_gates_passed=True,
        candidate_digest=CAND, approval=stale,
    )
    assert not decision.allowed
    assert any("digest" in r for r in decision.reasons)


def test_approval_must_name_owner_time_reason_and_target(policy: DeploymentPolicy) -> None:
    for broken in (
        _approval(owner=""),
        _approval(reason=""),
        _approval(approved_at=""),
        _approval(target="staging"),
    ):
        decision = policy.authorize(
            "production", required_checks_passed=True, assurance_gates_passed=True,
            candidate_digest=CAND, approval=broken,
        )
        assert not decision.allowed


def test_valid_approval_allows_the_execution_stage(policy: DeploymentPolicy) -> None:
    decision = policy.authorize(
        "production", required_checks_passed=True, assurance_gates_passed=True,
        candidate_digest=CAND, approval=_approval(),
    )
    assert decision.allowed


def test_approval_roundtrips_through_the_run_dir(tmp_path: Path) -> None:
    write_production_approval(tmp_path, _approval())
    loaded = load_production_approval(tmp_path)
    assert loaded is not None
    assert loaded.owner == "abhillash"
    assert loaded.candidate_digest == CAND
    assert load_production_approval(tmp_path / "empty") is None


# --- production readiness ---------------------------------------------------------------


def test_readiness_requires_rollback_health_and_journey(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    (workspace / "deploy").mkdir(parents=True)
    missing = production_readiness(workspace, health_verified=True, journey_verified=True)
    assert not missing.ready
    assert any("ROLLBACK" in item for item in missing.missing)

    (workspace / "deploy" / "ROLLBACK.md").write_text("# rollback\n")
    (workspace / "deploy" / "run.sh").write_text("#!/bin/sh\n")
    ready = production_readiness(workspace, health_verified=True, journey_verified=True)
    assert ready.ready

    unhealthy = production_readiness(workspace, health_verified=False, journey_verified=True)
    assert not unhealthy.ready


# --- simulated production execution (fixture mode) ---------------------------------------


def test_simulated_deploy_blocked_without_authorization(policy: DeploymentPolicy) -> None:
    decision = policy.authorize(
        "production", required_checks_passed=True, assurance_gates_passed=True,
        candidate_digest=CAND, approval=None,
    )
    outcome = simulate_production_deploy(decision, canary_healthy=True)
    assert not outcome.executed
    assert outcome.fixture_mode


def test_simulated_failed_canary_produces_rollback(policy: DeploymentPolicy) -> None:
    decision = policy.authorize(
        "production", required_checks_passed=True, assurance_gates_passed=True,
        candidate_digest=CAND, approval=_approval(),
    )
    outcome = simulate_production_deploy(decision, canary_healthy=False)
    assert outcome.executed
    assert outcome.rolled_back
    assert not outcome.ready


def test_simulated_success_is_ready_but_never_claims_a_real_deployment(
    policy: DeploymentPolicy,
) -> None:
    decision = policy.authorize(
        "production", required_checks_passed=True, assurance_gates_passed=True,
        candidate_digest=CAND, approval=_approval(),
    )
    outcome = simulate_production_deploy(decision, canary_healthy=True)
    assert outcome.executed and outcome.ready and not outcome.rolled_back
    assert outcome.fixture_mode
    assert "no real environment" in outcome.report_line.lower()
    assert "fixture" in outcome.report_line.lower()
