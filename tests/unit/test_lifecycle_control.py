"""Issue #65: executable contract for the unified lifecycle control plane."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from pmpe.orchestration.lifecycle import (
    PHASE_ZERO_POLICY,
    Approval,
    AuthoritySnapshot,
    BudgetPolicy,
    BudgetUsage,
    FindingSignal,
    LifecycleControlPlane,
    LifecycleState,
    MutationAttempt,
    RolloutStatus,
    TransitionContext,
    TransitionDenied,
    WorkStatus,
    migrate_legacy_state,
)

from pmpe.policies.engine import PolicyEngine

SHA = "sha256:" + "a" * 64
OTHER_SHA = "sha256:" + "b" * 64


def authority(*, current: bool = True) -> AuthoritySnapshot:
    return AuthoritySnapshot(
        contract_version="contract-v1",
        publisher_version="publisher-v1",
        contract_active=current,
        publisher_active=current,
        observed_at="2026-08-02T00:00:00Z",
        digest=SHA,
    )


def budgets(**usage: int) -> tuple[BudgetPolicy, BudgetUsage]:
    policy = BudgetPolicy(
        version="budget-v1",
        limits={
            "tokens": 100,
            "credits": 10,
            "elapsed_seconds": 3600,
            "external_compute_seconds": 600,
            "spend_microunits": 1_000,
        },
        repair_attempts_per_finding=2,
        repair_attempts_per_stage=3,
        reserved_safety_units=10,
        approved_by="delivery-owner",
    )
    return policy, BudgetUsage(counters=usage)


def context(
    *,
    current_authority: bool = True,
    usage: BudgetUsage | None = None,
    rollout: RolloutStatus | None = None,
    work: WorkStatus | None = None,
    permission: str = "lifecycle.transition",
    evidence: dict[str, str] | None = None,
    approvals: tuple[Approval, ...] = (),
    finding: FindingSignal | None = None,
    mutation: MutationAttempt | None = None,
    resume_state: LifecycleState | None = None,
) -> TransitionContext:
    _, default_usage = budgets()
    return TransitionContext(
        actor="control-plane",
        permissions=frozenset({permission}),
        evidence=evidence or {"subject_digest": SHA, "evidence_bundle_digest": OTHER_SHA},
        authority=authority(current=current_authority),
        budget_usage=usage or default_usage,
        rollout=rollout or RolloutStatus(),
        work=work or WorkStatus(),
        approvals=approvals,
        finding=finding,
        mutation=mutation,
        resume_state=resume_state,
        observed_at="2026-08-02T00:01:00Z",
    )


def control_plane(
    tmp_path: Path,
    *,
    state: LifecycleState = LifecycleState.CONTRACT_RECEIVED,
) -> LifecycleControlPlane:
    policy, _ = budgets()
    return LifecycleControlPlane.create(
        tmp_path,
        run_id="run-65",
        subject_digest=SHA,
        initial_state=state,
        budget_policy=policy,
    )


def evidence_for(source: LifecycleState, target: LifecycleState, *, reason: str) -> dict[str, str]:
    rule = PHASE_ZERO_POLICY.rule(source, target, reason=reason)
    return {name: f"sha256:{name}" for name in rule.required_evidence}


def test_phase_zero_policy_is_versioned_digest_bound_and_complete() -> None:
    assert PHASE_ZERO_POLICY.version == "phase-zero-v1"
    assert PHASE_ZERO_POLICY.digest.startswith("sha256:")
    assert len(PHASE_ZERO_POLICY.digest) == 71
    assert {state.value for state in LifecycleState} == {
        "CONTRACT_RECEIVED",
        "CONTRACT_INVALID",
        "PRODUCT_INPUT_REQUIRED",
        "CONTRACT_APPROVED",
        "REPOSITORY_ANALYSED",
        "ARCHITECTURE_PROPOSED",
        "ARCHITECTURE_APPROVED",
        "TEST_PLAN_CREATED",
        "TEST_PLAN_VALIDATED",
        "IMPLEMENTATION_PLANNED",
        "DRAFT_PR_OPEN",
        "IMPLEMENTATION_IN_PROGRESS",
        "VERIFICATION_FAILED",
        "REPAIR_IN_PROGRESS",
        "REVIEW_REQUIRED",
        "REVIEW_FAILED",
        "PR_READY",
        "PR_MERGED",
        "STAGING_DEPLOYED",
        "STAGING_FAILED",
        "CANARY_DEPLOYED",
        "CANARY_FAILED",
        "PRODUCTION_APPROVAL_REQUIRED",
        "PRODUCTION_DEPLOYED",
        "LIVE_VERIFICATION_FAILED",
        "ROLLBACK_IN_PROGRESS",
        "ROLLED_BACK",
        "BLOCKED",
        "BUDGET_EXCEEDED",
        "COMPLETED",
    }
    for state in LifecycleState:
        assert PHASE_ZERO_POLICY.rules_from(state), f"{state.value} has no legal exit"


def test_transition_table_contains_key_forward_failure_and_recovery_edges() -> None:
    pairs = {(rule.source, rule.target) for rule in PHASE_ZERO_POLICY.rules}
    assert {
        (LifecycleState.CONTRACT_RECEIVED, LifecycleState.CONTRACT_APPROVED),
        (LifecycleState.IMPLEMENTATION_PLANNED, LifecycleState.DRAFT_PR_OPEN),
        (LifecycleState.PR_READY, LifecycleState.PR_MERGED),
        (LifecycleState.STAGING_DEPLOYED, LifecycleState.CANARY_DEPLOYED),
        (
            LifecycleState.PRODUCTION_APPROVAL_REQUIRED,
            LifecycleState.PRODUCTION_DEPLOYED,
        ),
        (LifecycleState.PRODUCTION_DEPLOYED, LifecycleState.COMPLETED),
        (LifecycleState.LIVE_VERIFICATION_FAILED, LifecycleState.ROLLBACK_IN_PROGRESS),
        (LifecycleState.ROLLBACK_IN_PROGRESS, LifecycleState.ROLLED_BACK),
        (LifecycleState.COMPLETED, LifecycleState.LIVE_VERIFICATION_FAILED),
        (LifecycleState.BLOCKED, LifecycleState.ROLLBACK_IN_PROGRESS),
        (LifecycleState.BLOCKED, LifecycleState.STAGING_FAILED),
        (LifecycleState.BUDGET_EXCEEDED, LifecycleState.BLOCKED),
    }.issubset(pairs)


def test_illegal_skip_and_missing_exact_evidence_fail_closed(tmp_path: Path) -> None:
    cp = control_plane(tmp_path)
    with pytest.raises(TransitionDenied, match="illegal transition"):
        cp.transition(LifecycleState.IMPLEMENTATION_IN_PROGRESS, context(), reason="begin_work")
    with pytest.raises(TransitionDenied, match="required evidence"):
        cp.transition(
            LifecycleState.CONTRACT_APPROVED,
            context(evidence={"subject_digest": SHA}),
            reason="contract_admitted",
        )
    assert cp.state is LifecycleState.CONTRACT_RECEIVED
    assert cp.events[-1].outcome == "DENIED"


def test_forward_work_revalidates_contract_and_publisher_authority(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.DRAFT_PR_OPEN)
    required = evidence_for(
        LifecycleState.DRAFT_PR_OPEN,
        LifecycleState.IMPLEMENTATION_IN_PROGRESS,
        reason="begin_work",
    )
    with pytest.raises(TransitionDenied, match="authority"):
        cp.transition(
            LifecycleState.IMPLEMENTATION_IN_PROGRESS,
            context(current_authority=False, evidence=required),
            reason="begin_work",
        )
    assert cp.state is LifecycleState.DRAFT_PR_OPEN


def test_observers_append_digest_bound_evidence_but_cannot_change_state(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.PR_READY)
    event = cp.record_observation(
        source="authorization-watchdog",
        subject_digest=SHA,
        payload_digest=OTHER_SHA,
        signature="sig:v1:watchdog",
        observed_at="2026-08-02T00:02:00Z",
    )
    assert event.kind == "OBSERVATION"
    assert cp.state is LifecycleState.PR_READY
    assert LifecycleControlPlane.load(tmp_path).state is LifecycleState.PR_READY


def test_every_budget_dimension_must_be_approved_and_within_limit(tmp_path: Path) -> None:
    policy, _ = budgets()
    with pytest.raises(ValueError, match="approved"):
        replace(policy, approved_by="")
    cp = control_plane(tmp_path, state=LifecycleState.DRAFT_PR_OPEN)
    required = evidence_for(
        LifecycleState.DRAFT_PR_OPEN,
        LifecycleState.IMPLEMENTATION_IN_PROGRESS,
        reason="begin_work",
    )
    _, exhausted = budgets(tokens=100)
    with pytest.raises(TransitionDenied, match="budget"):
        cp.transition(
            LifecycleState.IMPLEMENTATION_IN_PROGRESS,
            context(usage=exhausted, evidence=required),
            reason="begin_work",
        )


def test_budget_stop_requires_worker_quiescence_and_safe_disposition(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.IMPLEMENTATION_IN_PROGRESS)
    _, exhausted = budgets(tokens=101)
    required = evidence_for(
        LifecycleState.IMPLEMENTATION_IN_PROGRESS,
        LifecycleState.BUDGET_EXCEEDED,
        reason="delivery_budget_exhausted",
    )
    active = WorkStatus(worker_leases_active=1, partial_output_disposition="frozen")
    with pytest.raises(TransitionDenied, match="worker"):
        cp.transition(
            LifecycleState.BUDGET_EXCEEDED,
            context(usage=exhausted, work=active, evidence=required),
            reason="delivery_budget_exhausted",
        )
    stopped = WorkStatus(
        worker_leases_active=0,
        workers_stopped=True,
        partial_output_disposition="frozen-unverified-non-admissible",
    )
    event = cp.transition(
        LifecycleState.BUDGET_EXCEEDED,
        context(
            usage=exhausted,
            work=stopped,
            evidence=required,
            resume_state=LifecycleState.IMPLEMENTATION_IN_PROGRESS,
        ),
        reason="delivery_budget_exhausted",
    )
    assert event.resume_state is LifecycleState.IMPLEMENTATION_IN_PROGRESS


def test_reserved_safety_budget_cannot_authorize_forward_work(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.STAGING_DEPLOYED)
    _, exhausted = budgets(tokens=100)
    rollout = RolloutStatus(staging="ACTIVE")
    forward = evidence_for(
        LifecycleState.STAGING_DEPLOYED,
        LifecycleState.CANARY_DEPLOYED,
        reason="canary_admitted",
    )
    with pytest.raises(TransitionDenied, match="budget"):
        cp.transition(
            LifecycleState.CANARY_DEPLOYED,
            context(usage=exhausted, rollout=rollout, evidence=forward),
            reason="canary_admitted",
        )
    attempt = MutationAttempt(
        attempt_id="attempt-rollback-1",
        idempotency_key="rollback:run-65:1",
        subject_digest=SHA,
        action="rollback",
        step_plan_digest=OTHER_SHA,
        status="PLANNED",
    )
    safety = evidence_for(
        LifecycleState.STAGING_DEPLOYED,
        LifecycleState.ROLLBACK_IN_PROGRESS,
        reason="canary_mutation_indeterminate",
    )
    cp.transition(
        LifecycleState.ROLLBACK_IN_PROGRESS,
        context(usage=exhausted, rollout=rollout, evidence=safety, mutation=attempt),
        reason="canary_mutation_indeterminate",
    )


def test_repair_is_bounded_per_finding_and_stage(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.REVIEW_FAILED)
    required = evidence_for(
        LifecycleState.REVIEW_FAILED,
        LifecycleState.REPAIR_IN_PROGRESS,
        reason="accepted_finding",
    )
    finding = FindingSignal(
        finding_id="finding-1",
        source="codex",
        exact_subject_digest=SHA,
        severity="HIGH",
        credible=True,
        blocking=True,
        reviewer_eligible=False,
    )
    _, at_limit = budgets()
    at_limit = replace(
        at_limit,
        repair_attempts_by_finding={"finding-1": 2},
        repair_attempts_by_stage={LifecycleState.REVIEW_FAILED.value: 2},
    )
    with pytest.raises(TransitionDenied, match="repair attempt"):
        cp.transition(
            LifecycleState.REPAIR_IN_PROGRESS,
            context(usage=at_limit, evidence=required, finding=finding),
            reason="accepted_finding",
        )


def test_blocking_finding_is_independent_of_reviewer_approval_eligibility(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.PR_READY)
    required = evidence_for(
        LifecycleState.PR_READY,
        LifecycleState.REVIEW_FAILED,
        reason="blocking_finding",
    )
    signal = FindingSignal(
        finding_id="scanner-1",
        source="security-scanner",
        exact_subject_digest=SHA,
        severity="HIGH",
        credible=True,
        blocking=True,
        reviewer_eligible=False,
    )
    cp.transition(
        LifecycleState.REVIEW_FAILED,
        context(evidence=required, finding=signal),
        reason="blocking_finding",
    )
    assert cp.state is LifecycleState.REVIEW_FAILED
    assert not signal.reviewer_eligible


def test_pr_ready_requires_eligible_exact_subject_review(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.REVIEW_REQUIRED)
    required = evidence_for(
        LifecycleState.REVIEW_REQUIRED,
        LifecycleState.PR_READY,
        reason="formal_review_clear",
    )
    ineligible = Approval(
        approval_id="review-1",
        actor="scanner",
        subject_digest=SHA,
        kind="FORMAL_REVIEW",
        eligible=False,
        active=True,
    )
    with pytest.raises(TransitionDenied, match="eligible formal review"):
        cp.transition(
            LifecycleState.PR_READY,
            context(evidence=required, approvals=(ineligible,)),
            reason="formal_review_clear",
        )
    eligible = replace(ineligible, approval_id="review-2", actor="reviewer", eligible=True)
    cp.transition(
        LifecycleState.PR_READY,
        context(evidence=required, approvals=(eligible,)),
        reason="formal_review_clear",
    )


def test_external_mutation_requires_prejournaled_unique_attempt(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.PR_MERGED)
    required = evidence_for(
        LifecycleState.PR_MERGED,
        LifecycleState.STAGING_DEPLOYED,
        reason="staging_admitted",
    )
    with pytest.raises(TransitionDenied, match="mutation attempt"):
        cp.transition(
            LifecycleState.STAGING_DEPLOYED,
            context(evidence=required),
            reason="staging_admitted",
        )
    attempt = MutationAttempt(
        attempt_id="attempt-stage-1",
        idempotency_key="stage:run-65:1",
        subject_digest=SHA,
        action="deploy_staging",
        step_plan_digest=OTHER_SHA,
        status="PLANNED",
    )
    cp.transition(
        LifecycleState.STAGING_DEPLOYED,
        context(evidence=required, mutation=attempt),
        reason="staging_admitted",
    )
    with pytest.raises(TransitionDenied, match="idempotency key"):
        cp.record_mutation_result(
            replace(attempt, attempt_id="attempt-stage-2"),
            status="SUCCEEDED",
            result_digest=SHA,
        )


def test_missing_adapter_response_never_implies_success(tmp_path: Path) -> None:
    cp = control_plane(tmp_path)
    attempt = MutationAttempt(
        attempt_id="attempt-1",
        idempotency_key="cleanup:run-65:1",
        subject_digest=SHA,
        action="cleanup",
        step_plan_digest=OTHER_SHA,
        status="PLANNED",
    )
    result = cp.record_mutation_result(attempt, status="UNKNOWN", result_digest=None)
    assert result.status == "UNKNOWN"
    assert not result.successful


def test_active_exposure_cannot_stop_or_request_product_input_before_rollback(
    tmp_path: Path,
) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.CANARY_DEPLOYED)
    rollout = RolloutStatus(staging="ACTIVE", canary="ACTIVE")
    with pytest.raises(TransitionDenied, match="rollback"):
        cp.transition(
            LifecycleState.BLOCKED,
            context(rollout=rollout),
            reason="external_dependency",
        )
    with pytest.raises(TransitionDenied, match="rollback"):
        cp.transition(
            LifecycleState.PRODUCT_INPUT_REQUIRED,
            context(rollout=rollout),
            reason="authority_invalidated",
        )


def test_completed_requires_exact_release_live_rollback_and_observation_evidence(
    tmp_path: Path,
) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.PRODUCTION_DEPLOYED)
    required = evidence_for(
        LifecycleState.PRODUCTION_DEPLOYED,
        LifecycleState.COMPLETED,
        reason="observation_window_passed",
    )
    missing = dict(required)
    missing.pop("rollback_readiness_digest")
    with pytest.raises(TransitionDenied, match="required evidence"):
        cp.transition(
            LifecycleState.COMPLETED,
            context(evidence=missing),
            reason="observation_window_passed",
        )
    event = cp.transition(
        LifecycleState.COMPLETED,
        context(evidence=required),
        reason="observation_window_passed",
    )
    assert event.subject_digest == SHA
    assert cp.completion_claim_active


def test_completion_claim_is_revoked_append_only_on_admitted_invalidation(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.PRODUCTION_DEPLOYED)
    done = evidence_for(
        LifecycleState.PRODUCTION_DEPLOYED,
        LifecycleState.COMPLETED,
        reason="observation_window_passed",
    )
    cp.transition(
        LifecycleState.COMPLETED,
        context(evidence=done),
        reason="observation_window_passed",
    )
    before = len(cp.events)
    invalid = evidence_for(
        LifecycleState.COMPLETED,
        LifecycleState.LIVE_VERIFICATION_FAILED,
        reason="completion_evidence_invalidated",
    )
    cp.transition(
        LifecycleState.LIVE_VERIFICATION_FAILED,
        context(evidence=invalid),
        reason="completion_evidence_invalidated",
    )
    assert not cp.completion_claim_active
    assert len(cp.events) == before + 1
    assert any(event.kind == "COMPLETION_CLAIMED" for event in cp.events)
    assert cp.events[-1].kind == "COMPLETION_REVOKED"


@pytest.mark.parametrize(
    ("legacy", "expected"),
    [
        ({"version": 2, "stage": "assessment"}, LifecycleState.REPOSITORY_ANALYSED),
        ({"version": 2, "stage": "review"}, LifecycleState.REVIEW_REQUIRED),
        ({"version": 3, "stage": "draft_pr"}, LifecycleState.DRAFT_PR_OPEN),
        ({"version": 3, "stage": "deploy"}, LifecycleState.PR_MERGED),
    ],
)
def test_legacy_v2_and_fullstack_states_migrate_deterministically(
    legacy: dict[str, object], expected: LifecycleState
) -> None:
    migrated = migrate_legacy_state(legacy)
    assert migrated.state is expected
    assert migrated.source_version == legacy["version"]
    assert migrated.digest.startswith("sha256:")


def test_unknown_legacy_state_fails_closed() -> None:
    with pytest.raises(ValueError, match="unsupported legacy"):
        migrate_legacy_state({"version": 2, "stage": "surprise"})


def test_persistence_replay_detects_tampering(tmp_path: Path) -> None:
    cp = control_plane(tmp_path)
    required = evidence_for(
        LifecycleState.CONTRACT_RECEIVED,
        LifecycleState.CONTRACT_APPROVED,
        reason="contract_admitted",
    )
    cp.transition(
        LifecycleState.CONTRACT_APPROVED,
        context(evidence=required),
        reason="contract_admitted",
    )
    loaded = LifecycleControlPlane.load(tmp_path)
    assert loaded.state is LifecycleState.CONTRACT_APPROVED
    ledger = tmp_path / "lifecycle-events.jsonl"
    ledger.write_text(ledger.read_text().replace("CONTRACT_APPROVED", "COMPLETED", 1))
    with pytest.raises(ValueError, match="digest chain"):
        LifecycleControlPlane.load(tmp_path)


def test_unknown_policy_decisions_fail_closed() -> None:
    decision = PolicyEngine().classify("operation.never.registered")
    assert decision.level.value == "high"
    assert PolicyEngine().requires_approval(decision.level)
