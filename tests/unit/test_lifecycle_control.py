"""Issue #65: executable contract for the unified lifecycle control plane."""

from __future__ import annotations

import fcntl
import hashlib
import json
import multiprocessing
import os
import threading
import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import asdict, fields, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import pmpe.orchestration.lifecycle as lifecycle
from pmpe.orchestration.lifecycle import (
    PHASE_ZERO_POLICY,
    AdapterResultEvidence,
    Approval,
    AuthoritySnapshot,
    BudgetPolicy,
    BudgetUsage,
    EvidenceTrustPolicy,
    FindingSignal,
    LifecycleControlPlane,
    LifecycleState,
    MutationAttempt,
    MutationAuthorization,
    RolloutStatus,
    TransitionContext,
    TransitionDeniedError,
    WorkStatus,
    migrate_legacy_state,
    mutation_subject_digest,
)
from pmpe.policies.engine import PolicyEngine

SHA = "sha256:" + "a" * 64
OTHER_SHA = "sha256:" + "b" * 64
OWNER_CREDENTIAL_DIGEST = "sha256:" + "c" * 64
TRUST_POLICY = EvidenceTrustPolicy(
    adapter_authorities={"test-adapter": SHA},
    budget_owner_authorities={
        "delivery-owner": OWNER_CREDENTIAL_DIGEST,
        "owner-alice": OWNER_CREDENTIAL_DIGEST,
    },
    repository_observers={"repository-observer": OTHER_SHA},
    work_controllers={"work-controller": SHA},
    production_approvers={"release-owner": OWNER_CREDENTIAL_DIGEST},
    budget_meters={"budget-meter": SHA},
    formal_reviewers={"codex": SHA},
    native_merge_gates={"github-merge-queue": SHA},
    finding_sources={"finding-source": SHA},
    mutation_authorizers={"mutation-authorizer": SHA},
    live_observers={"live-observer": SHA},
    authority_observers={"authority-observer": SHA},
    integrity_monitors={"monitor-1": SHA},
)


def external_proof(identity: str, authority_digest: str, payload: object) -> str:
    return object_digest(
        {
            "test_trust_root": "not-persisted-with-the-lifecycle",
            "identity": identity,
            "authority_digest": authority_digest,
            "payload": payload,
        }
    )


def verify_external_proof(
    identity: str, authority_digest: str, payload: object, proof: str
) -> bool:
    return proof == external_proof(identity, authority_digest, payload)


def authority(
    *,
    current: bool = True,
    observed_at: str = "2026-08-02T00:01:00Z",
    valid_until: str = "2026-08-03T00:00:00Z",
) -> AuthoritySnapshot:
    payload = {
        "contract_version": "contract-v1",
        "publisher_version": "publisher-v1",
        "contract_active": current,
        "publisher_active": current,
        "observed_at": observed_at,
        "valid_until": valid_until,
    }
    return AuthoritySnapshot(
        contract_version="contract-v1",
        publisher_version="publisher-v1",
        contract_active=current,
        publisher_active=current,
        observed_at=observed_at,
        valid_until=valid_until,
        digest=object_digest(payload),
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
    actor: lifecycle.TransitionActor | None = None,
    evidence: dict[str, str] | None = None,
    approvals: tuple[Approval, ...] = (),
    finding: FindingSignal | None = None,
    mutation: MutationAttempt | None = None,
    budget_policy: BudgetPolicy | None = None,
) -> TransitionContext:
    default_policy, default_usage = budgets()
    effective_policy = budget_policy or default_policy
    authority_snapshot = authority(current=current_authority)
    effective_usage = usage or default_usage
    actor_claims = {
        "actor_id": "control-plane",
        "role": "lifecycle-controller",
        "authenticated": True,
        "capabilities": [permission],
        "subject_digest": SHA,
        "authority_digest": authority_snapshot.digest,
    }
    effective_evidence = dict(
        evidence or {"subject_digest": SHA, "evidence_bundle_digest": OTHER_SHA}
    )
    authority_payload = {
        "observer_id": "authority-observer",
        "authority_digest": SHA,
        "subject_digest": SHA,
        "contract_version": authority_snapshot.contract_version,
        "publisher_version": authority_snapshot.publisher_version,
        "contract_active": authority_snapshot.contract_active,
        "publisher_active": authority_snapshot.publisher_active,
        "authority_observed_at": authority_snapshot.observed_at,
        "valid_until": authority_snapshot.valid_until,
        "transition_observed_at": "2026-08-02T00:01:00Z",
        "authority_current_time": "2026-08-02T00:01:00Z",
    }
    effective_evidence.update(
        {
            "authority_observer_id": "authority-observer",
            "authority_observer_authority_digest": SHA,
            "authority_current_time": "2026-08-02T00:01:00Z",
            "authority_authentication_evidence_digest": external_proof(
                "authority-observer", SHA, authority_payload
            ),
        }
    )
    canary_window_payload = {
        "observer_id": "live-observer",
        "authority_digest": SHA,
        "subject_digest": SHA,
        "canary_id_digest": effective_evidence.get("canary_id_digest", OTHER_SHA),
        "canary_attempt_digest": effective_evidence.get("canary_attempt_digest", OTHER_SHA),
        "canary_status_digest": effective_evidence.get("canary_status_digest", OTHER_SHA),
        "slo_window_digest": effective_evidence.get("slo_window_digest", OTHER_SHA),
        "observed_at": "2026-08-02T00:01:00Z",
    }
    effective_evidence.update(
        {
            "canary_window_observer_id": "live-observer",
            "canary_window_observer_authority_digest": SHA,
            "canary_window_authentication_evidence_digest": external_proof(
                "live-observer", SHA, canary_window_payload
            ),
        }
    )
    meter_payload = {
        "meter_id": "budget-meter",
        "authority_digest": SHA,
        "subject_digest": SHA,
        "budget_policy_digest": object_digest(lifecycle._budget_policy_payload(effective_policy)),
        "budget_usage_digest": object_digest(lifecycle._budget_usage_payload(effective_usage)),
        "observed_at": "2026-08-02T00:01:00Z",
    }
    effective_evidence.update(
        {
            "budget_meter_id": "budget-meter",
            "budget_meter_authority_digest": SHA,
            "budget_usage_digest": meter_payload["budget_usage_digest"],
            "budget_meter_authentication_evidence_digest": external_proof(
                "budget-meter", SHA, meter_payload
            ),
        }
    )
    effective_rollout = rollout or RolloutStatus()
    rollback_payload = {
        "observer_id": "live-observer",
        "authority_digest": SHA,
        "subject_digest": SHA,
        "rollout_digest": object_digest(asdict(effective_rollout)),
        "rollback_exposure_digest": effective_evidence.get("rollback_exposure_digest", OTHER_SHA),
        "restoration_verification_digest": effective_evidence.get(
            "restoration_verification_digest", OTHER_SHA
        ),
        "observed_at": "2026-08-02T00:01:00Z",
    }
    effective_evidence["rollback_observation_authentication_evidence_digest"] = external_proof(
        "live-observer", SHA, rollback_payload
    )
    if finding is not None and (
        authority_digest := TRUST_POLICY.finding_sources.get(finding.source)
    ):
        effective_evidence.setdefault(
            "finding_authentication_evidence_digest",
            external_proof(
                finding.source,
                authority_digest,
                {
                    "finding": asdict(finding),
                    "subject_digest": SHA,
                    "observed_at": "2026-08-02T00:01:00Z",
                },
            ),
        )
    live_payload = {
        "observer_id": "live-observer",
        "authority_digest": SHA,
        "subject_digest": SHA,
        "release_sha": effective_evidence.get("release_sha", ""),
        "artifact_digest": effective_evidence.get("artifact_digest", ""),
        "configuration_digest": effective_evidence.get("configuration_digest", ""),
        "production_attempt_digest": effective_evidence.get("production_attempt_digest", ""),
        "production_result_digest": effective_evidence.get("production_result_digest", ""),
        "live_verification_digest": effective_evidence.get("live_verification_digest", OTHER_SHA),
        "rollback_readiness_digest": effective_evidence.get("rollback_readiness_digest", OTHER_SHA),
        "observation_window_digest": effective_evidence.get("observation_window_digest", OTHER_SHA),
        "observed_at": "2026-08-02T00:01:00Z",
    }
    effective_evidence.update(
        {
            "live_observer_id": "live-observer",
            "live_observer_authority_digest": SHA,
            "live_observation_authentication_evidence_digest": external_proof(
                "live-observer", SHA, live_payload
            ),
        }
    )
    inventories: dict[str, str] = {}
    inventory_observed = datetime.now(UTC).replace(microsecond=0)
    default_inventory_observed_at = inventory_observed.isoformat().replace("+00:00", "Z")
    default_inventory_expires_at = (
        (inventory_observed + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    )
    for source, authority_digest in TRUST_POLICY.finding_sources.items():
        inventory_digest = effective_evidence.setdefault(
            f"finding_inventory_{source}_digest", OTHER_SHA
        )
        inventory_observed_at = effective_evidence.setdefault(
            f"finding_inventory_{source}_observed_at", default_inventory_observed_at
        )
        inventory_expires_at = effective_evidence.setdefault(
            f"finding_inventory_{source}_expires_at", default_inventory_expires_at
        )
        inventories[source] = inventory_digest
        effective_evidence.setdefault(
            f"finding_inventory_{source}_authentication_evidence_digest",
            external_proof(
                source,
                authority_digest,
                {
                    "source_id": source,
                    "authority_digest": authority_digest,
                    "subject_digest": SHA,
                    "inventory_digest": inventory_digest,
                    "status": "NO_BLOCKING",
                    "observed_at": inventory_observed_at,
                    "expires_at": inventory_expires_at,
                },
            ),
        )
    effective_evidence.setdefault(
        "finding_source_set_digest", object_digest(dict(TRUST_POLICY.finding_sources))
    )
    effective_evidence.setdefault("finding_inventory_epochs_digest", object_digest(inventories))
    return TransitionContext(
        actor=actor
        or lifecycle.TransitionActor(
            actor_id=str(actor_claims["actor_id"]),
            role=str(actor_claims["role"]),
            authenticated=bool(actor_claims["authenticated"]),
            capabilities=frozenset({permission}),
            subject_digest=str(actor_claims["subject_digest"]),
            authority_digest=str(actor_claims["authority_digest"]),
            authentication_evidence_digest=external_proof(
                "control-plane", authority_snapshot.digest, actor_claims
            ),
        ),
        evidence=effective_evidence,
        authority=authority_snapshot,
        budget_usage=effective_usage,
        rollout=effective_rollout,
        work=work or WorkStatus(),
        approvals=approvals,
        finding=finding,
        mutation=mutation,
        observed_at="2026-08-02T00:01:00Z",
    )


def control_plane(
    tmp_path: Path,
    *,
    state: LifecycleState = LifecycleState.CONTRACT_RECEIVED,
    trust_policy: EvidenceTrustPolicy = TRUST_POLICY,
    lifecycle_policy: lifecycle.LifecyclePolicy = PHASE_ZERO_POLICY,
    bundle_verifier: lifecycle.BundleVerifier | None = None,
) -> LifecycleControlPlane:
    policy, _ = budgets()
    cp = LifecycleControlPlane.create(
        tmp_path,
        run_id="run-65",
        subject_digest=SHA,
        initial_state=LifecycleState.CONTRACT_RECEIVED,
        budget_policy=policy,
        lifecycle_policy=lifecycle_policy,
        trust_policy=trust_policy,
        evidence_verifier=verify_external_proof,
        bundle_verifier=bundle_verifier,
    )
    if state is not LifecycleState.CONTRACT_RECEIVED:
        cp._append(
            kind="MIGRATION_ADMITTED",
            outcome="APPLIED",
            source=LifecycleState.CONTRACT_RECEIVED,
            target=state,
            reason="test_fixture_migration",
            actor="test-fixture",
            evidence_refs={"subject_digest": SHA},
            observed_at="2026-08-02T00:01:00Z",
        )
        cp._state = state
    return cp


def test_no_blocker_inventory_requires_a_live_authenticated_freshness_window(
    tmp_path: Path,
) -> None:
    cp = control_plane(tmp_path)
    valid = context()
    assert cp._trusted_finding_inventory_valid(valid)

    source = "finding-source"
    authority_digest = TRUST_POLICY.finding_sources[source]
    stale_observed = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=10)
    stale_expires = stale_observed + timedelta(minutes=5)
    stale_evidence = dict(valid.evidence)
    stale_evidence[f"finding_inventory_{source}_observed_at"] = stale_observed.isoformat().replace(
        "+00:00", "Z"
    )
    stale_evidence[f"finding_inventory_{source}_expires_at"] = stale_expires.isoformat().replace(
        "+00:00", "Z"
    )
    payload = {
        "source_id": source,
        "authority_digest": authority_digest,
        "subject_digest": SHA,
        "inventory_digest": stale_evidence[f"finding_inventory_{source}_digest"],
        "status": "NO_BLOCKING",
        "observed_at": stale_evidence[f"finding_inventory_{source}_observed_at"],
        "expires_at": stale_evidence[f"finding_inventory_{source}_expires_at"],
    }
    stale_evidence[f"finding_inventory_{source}_authentication_evidence_digest"] = external_proof(
        source, authority_digest, payload
    )

    assert not cp._trusted_finding_inventory_valid(replace(valid, evidence=stale_evidence))


def test_no_blocker_inventory_rechecks_expiry_after_source_authentication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cp = control_plane(tmp_path)
    decision_time = datetime(2030, 1, 1, tzinfo=UTC)
    observed_at = (decision_time - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    expires = decision_time + timedelta(seconds=1)
    expires_at = expires.isoformat().replace("+00:00", "Z")
    valid = context(
        evidence={
            "finding_inventory_finding-source_observed_at": observed_at,
            "finding_inventory_finding-source_expires_at": expires_at,
        }
    )

    class DecisionClock:
        current = decision_time

        @classmethod
        def now(cls, timezone: object = None) -> datetime:
            del timezone
            return cls.current

        @staticmethod
        def fromisoformat(value: str) -> datetime:
            return datetime.fromisoformat(value)

    def expiring_verifier(
        identity: str,
        authority_digest: str,
        payload: object,
        proof: str,
    ) -> bool:
        authenticated = verify_external_proof(identity, authority_digest, payload, proof)
        DecisionClock.current = expires + timedelta(seconds=1)
        return authenticated

    cp._evidence_verifier = expiring_verifier
    monkeypatch.setattr(lifecycle, "datetime", DecisionClock)

    assert not cp._trusted_finding_inventory_valid(valid)


def mutation_authorization(
    cp: LifecycleControlPlane, attempt: MutationAttempt
) -> MutationAuthorization:
    observed = datetime.now(UTC).replace(microsecond=0)
    observed_at = observed.isoformat().replace("+00:00", "Z")
    expires_at = (observed + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    body = {
        "authorizer_id": "mutation-authorizer",
        "authority_digest": SHA,
        "subject_digest": SHA,
        "source_state": cp.state.value,
        "action": attempt.action,
        "attempt_id": attempt.attempt_id,
        "idempotency_key": attempt.idempotency_key,
        "step_plan_digest": attempt.step_plan_digest,
        "steps": list(attempt.steps),
        "observed_at": observed_at,
        "expires_at": expires_at,
    }
    return MutationAuthorization(
        authorizer_id="mutation-authorizer",
        authority_digest=SHA,
        subject_digest=SHA,
        source_state=cp.state,
        action=attempt.action,
        attempt_id=attempt.attempt_id,
        idempotency_key=attempt.idempotency_key,
        step_plan_digest=attempt.step_plan_digest,
        steps=attempt.steps,
        observed_at=observed_at,
        expires_at=expires_at,
        authentication_evidence_digest=external_proof("mutation-authorizer", SHA, body),
    )


def prejournal(
    cp: LifecycleControlPlane,
    attempt: MutationAttempt,
    *,
    evidence: Mapping[str, str] | None = None,
) -> MutationAttempt:
    return cp.prejournal_mutation(
        attempt,
        authorization=mutation_authorization(cp, attempt),
        evidence=evidence,
    )


def test_transition_actor_rejects_a_self_computed_credential(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.PR_MERGED)
    valid = context(
        evidence=evidence_for(
            LifecycleState.CONTRACT_RECEIVED,
            LifecycleState.CONTRACT_APPROVED,
            reason="contract_admitted",
        )
    )
    forged = replace(
        valid.actor,
        authentication_evidence_digest=lifecycle._actor_evidence_digest(valid.actor),
    )

    with pytest.raises(TransitionDeniedError, match="actor authority"):
        cp.transition(
            LifecycleState.CONTRACT_APPROVED,
            replace(valid, actor=forged),
            reason="contract_admitted",
        )


def test_forward_transition_rejects_self_computed_budget_telemetry(tmp_path: Path) -> None:
    cp = control_plane(tmp_path)
    valid = context(
        evidence=evidence_for(
            LifecycleState.CONTRACT_RECEIVED,
            LifecycleState.CONTRACT_APPROVED,
            reason="contract_admitted",
        )
    )
    forged_evidence = dict(valid.evidence)
    forged_evidence["budget_meter_authentication_evidence_digest"] = object_digest(
        {"usage": lifecycle._budget_usage_payload(valid.budget_usage)}
    )
    with pytest.raises(TransitionDeniedError, match="trusted complete budget telemetry"):
        cp.transition(
            LifecycleState.CONTRACT_APPROVED,
            replace(valid, evidence=forged_evidence),
            reason="contract_admitted",
        )


def test_transition_waits_for_the_retention_sweep_lock(tmp_path: Path) -> None:
    cp = control_plane(tmp_path)
    transition_context = context(
        evidence=evidence_for(
            LifecycleState.CONTRACT_RECEIVED,
            LifecycleState.CONTRACT_APPROVED,
            reason="contract_admitted",
        )
    )
    process_context = multiprocessing.get_context("fork")
    locked = process_context.Event()

    def hold_retention_lock() -> None:
        with cp.lock_path.open("a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            locked.set()
            time.sleep(0.2)

    holder = process_context.Process(target=hold_retention_lock)
    holder.start()
    assert locked.wait(timeout=1)
    started_at = time.monotonic()
    event = cp.transition(
        LifecycleState.CONTRACT_APPROVED,
        transition_context,
        reason="contract_admitted",
    )
    elapsed = time.monotonic() - started_at
    holder.join(timeout=1)

    assert holder.exitcode == 0
    assert elapsed >= 0.15
    assert event.target is LifecycleState.CONTRACT_APPROVED


def evidence_for(source: LifecycleState, target: LifecycleState, *, reason: str) -> dict[str, str]:
    rule = PHASE_ZERO_POLICY.rule(source, target, reason=reason)
    evidence = {
        name: (
            SHA
            if name == "subject_digest"
            else (
                "a" * 40
                if name.endswith("_sha")
                else "sha256:" + hashlib.sha256(name.encode()).hexdigest()
            )
        )
        for name in rule.required_evidence
    }
    if "finding_source_set_digest" in evidence:
        inventories = dict.fromkeys(TRUST_POLICY.finding_sources, OTHER_SHA)
        evidence.update(
            finding_source_set_digest=object_digest(dict(TRUST_POLICY.finding_sources)),
            finding_inventory_epochs_digest=object_digest(inventories),
        )
    return evidence


def rollback_plan(evidence: dict[str, str] | None = None) -> str:
    return mutation_subject_digest(
        "rollback",
        evidence
        or {
            name: SHA
            if name == "subject_digest"
            else "sha256:" + hashlib.sha256(name.encode()).hexdigest()
            for name in lifecycle._MUTATION_SUBJECT_FIELDS["rollback"]
        },
    )


def ready_attempt(evidence: dict[str, str]) -> MutationAttempt:
    return MutationAttempt(
        attempt_id="ready:run-65:1",
        idempotency_key="ready:run-65:1",
        subject_digest=SHA,
        action="mark_pr_ready",
        step_plan_digest=mutation_subject_digest("mark_pr_ready", evidence),
        status="PLANNED",
    )


def draft_revocation_attempt(evidence: dict[str, str]) -> MutationAttempt:
    return MutationAttempt(
        attempt_id="draft:run-65:revocation",
        idempotency_key="draft:run-65:revocation",
        subject_digest=SHA,
        action="convert_pr_to_draft",
        step_plan_digest=mutation_subject_digest("convert_pr_to_draft", evidence),
        status="PLANNED",
    )


def object_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def assert_live_utc(value: str) -> None:
    observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert abs(datetime.now(UTC) - observed) < timedelta(seconds=5)


def adapter_result_evidence(
    attempt: MutationAttempt,
    *,
    status: str,
    result_digest: str | None,
) -> AdapterResultEvidence:
    body = {
        "adapter_id": "test-adapter",
        "role": "mutation-adapter",
        "authenticated": True,
        "capabilities": ["lifecycle.mutation.result.record"],
        "subject_digest": attempt.subject_digest,
        "authority_digest": SHA,
        "attempt_id": attempt.attempt_id,
        "idempotency_key": attempt.idempotency_key,
        "action": attempt.action,
        "step_plan_digest": attempt.step_plan_digest,
        "status": status,
        "result_digest": result_digest,
    }
    return AdapterResultEvidence(
        adapter_id=str(body["adapter_id"]),
        role=str(body["role"]),
        authenticated=True,
        capabilities=frozenset({"lifecycle.mutation.result.record"}),
        subject_digest=attempt.subject_digest,
        authority_digest=SHA,
        attempt_id=attempt.attempt_id,
        idempotency_key=attempt.idempotency_key,
        action=attempt.action,
        step_plan_digest=attempt.step_plan_digest,
        status=status,
        result_digest=result_digest,
        authentication_evidence_digest=external_proof("test-adapter", SHA, body),
    )


def record_result(
    cp: LifecycleControlPlane,
    attempt: MutationAttempt,
    *,
    status: str,
    result_digest: str | None,
) -> lifecycle.MutationResult:
    return cp.record_mutation_result(
        attempt,
        status=status,
        result_digest=result_digest,
        adapter_evidence=adapter_result_evidence(
            attempt, status=status, result_digest=result_digest
        ),
    )


def bind_work_evidence(evidence: dict[str, str], work: WorkStatus) -> None:
    work_digest = object_digest(asdict(work))
    observed_at = "2026-08-02T00:01:00Z"
    lease_epoch = object_digest("lease-epoch-1")
    capability_epoch = object_digest("capability-epoch-1")
    quiescence = object_digest(
        {
            "controller_id": "work-controller",
            "authority_digest": SHA,
            "subject_digest": SHA,
            "work_digest": work_digest,
            "lease_epoch_digest": lease_epoch,
            "observed_at": observed_at,
            "status": "QUIESCED",
        }
    )
    revocation = object_digest(
        {
            "controller_id": "work-controller",
            "authority_digest": SHA,
            "subject_digest": SHA,
            "work_digest": work_digest,
            "capability_epoch_digest": capability_epoch,
            "observed_at": observed_at,
            "status": "REVOKED",
        }
    )
    evidence.update(
        {
            "work_disposition_digest": work_digest,
            "work_controller_id": "work-controller",
            "work_controller_authority_digest": SHA,
            "work_control_observed_at": observed_at,
            "work_lease_epoch_digest": lease_epoch,
            "mutation_capability_epoch_digest": capability_epoch,
            "worker_quiescence_digest": quiescence,
            "mutation_revocation_digest": revocation,
            "work_control_authentication_evidence_digest": external_proof(
                "work-controller",
                SHA,
                {
                    "controller_id": "work-controller",
                    "authority_digest": SHA,
                    "subject_digest": SHA,
                    "quiescence_digest": quiescence,
                    "revocation_digest": revocation,
                    "observed_at": observed_at,
                },
            ),
        }
    )


def bind_repository_observation(evidence: dict[str, str]) -> None:
    observed_at = "2026-08-02T00:01:00Z"
    review_inputs = {
        name: evidence[name]
        for name in (
            "reviewed_commit_sha",
            "prospective_tree_digest",
            "verification_bundle_digest",
            "review_digest",
        )
    }
    observation = object_digest(
        {
            "observer_id": "repository-observer",
            "authority_digest": OTHER_SHA,
            "subject_digest": SHA,
            "review_inputs": review_inputs,
            "observed_at": observed_at,
        }
    )
    evidence.update(
        {
            "repository_observer_id": "repository-observer",
            "repository_observer_authority_digest": OTHER_SHA,
            "repository_observed_at": observed_at,
            "repository_observation_digest": observation,
            "repository_observation_authentication_evidence_digest": external_proof(
                "repository-observer",
                OTHER_SHA,
                {
                    "observer_id": "repository-observer",
                    "authority_digest": OTHER_SHA,
                    "subject_digest": SHA,
                    "observation_digest": observation,
                    "observed_at": observed_at,
                },
            ),
        }
    )


def bind_resume_observation(
    evidence: dict[str, str], stopped: lifecycle.LifecycleEvent, target: LifecycleState
) -> None:
    """Bind ordinary resume evidence to the exact recorded stop."""
    observed_at = "2026-08-02T00:01:00Z"
    payload = {
        "observer_id": "repository-observer",
        "authority_digest": OTHER_SHA,
        "subject_digest": SHA,
        "stopped_event_digest": stopped.event_digest,
        "stopped_reason": stopped.reason,
        "resume_target": target.value,
        "incident_closure_digest": evidence["incident_closure_digest"],
        "restored_capability_digest": evidence["restored_capability_digest"],
        "unchanged_inputs_digest": evidence["unchanged_inputs_digest"],
        "observed_at": observed_at,
    }
    evidence.update(
        {
            "resume_observer_id": "repository-observer",
            "resume_observer_authority_digest": OTHER_SHA,
            "resume_authentication_evidence_digest": external_proof(
                "repository-observer", OTHER_SHA, payload
            ),
        }
    )


def record_integrated_merge(cp: LifecycleControlPlane, merge_result_digest: str) -> None:
    cp._append(
        kind="TRANSITION",
        outcome="APPLIED",
        source=cp.state,
        target=cp.state,
        reason="native_merge_linearized",
        actor="github-merge-queue",
        evidence_refs={"merge_result_digest": merge_result_digest},
        observed_at="2026-08-02T00:01:00Z",
    )


def record_active_canary_binding(
    cp: LifecycleControlPlane,
    *,
    attempt_digest: str = OTHER_SHA,
) -> dict[str, str]:
    evidence = {
        "subject_digest": SHA,
        "merge_commit_sha": "a" * 40,
        "merge_digest": object_digest("merge-fixture"),
        "artifact_digest": object_digest("artifact-fixture"),
        "configuration_digest": object_digest("configuration-fixture"),
        "migration_plan_digest": object_digest("migration-fixture"),
        "deployment_target_digest": object_digest("target-fixture"),
        "rollout_plan_digest": object_digest("rollout-fixture"),
        "staging_digest": object_digest("staging-fixture"),
        "canary_id_digest": object_digest("canary-run-65-fixture"),
        "canary_attempt_digest": attempt_digest,
    }
    evidence["canary_status_digest"] = object_digest(
        {
            "canary_id_digest": evidence["canary_id_digest"],
            "deployment_attempt_digest": attempt_digest,
            "deployment_result_digest": SHA,
            "subject_digest": SHA,
            "status": "ACTIVE",
        }
    )
    cp._append(
        kind="CANARY_BINDING_ADMITTED",
        outcome="RECORDED",
        source=cp.state,
        target=cp.state,
        reason="canary_admitted",
        actor="fixture",
        evidence_refs=evidence,
        observed_at="2026-08-02T00:01:00Z",
    )
    return evidence


def completion_evidence_with_review_binding(cp: LifecycleControlPlane) -> dict[str, str]:
    reviewed_commit = "a" * 40
    reviewed_candidate = object_digest({"tree": "reviewed-candidate"})
    review_evidence = object_digest({"bundle": "reviewed-evidence"})
    cp._append(
        kind="REVIEW_BINDING_ADMITTED",
        outcome="RECORDED",
        source=cp.state,
        target=cp.state,
        reason="formal_review_clear",
        actor="codex",
        evidence_refs={
            "subject_digest": SHA,
            "reviewed_commit_sha": reviewed_commit,
            "prospective_tree_digest": reviewed_candidate,
            "verification_bundle_digest": review_evidence,
            "review_digest": object_digest("codex-review-fixture"),
        },
        observed_at="2026-08-02T00:01:00Z",
    )
    evidence = evidence_for(
        LifecycleState.PRODUCTION_DEPLOYED,
        LifecycleState.COMPLETED,
        reason="observation_window_passed",
    )
    evidence.update(
        {
            "subject_digest": SHA,
            "release_sha": reviewed_commit,
            "reviewed_commit_sha": reviewed_commit,
            "reviewed_candidate_digest": reviewed_candidate,
            "review_evidence_digest": review_evidence,
            "evidence_bundle_digest": review_evidence,
            "finding_high_watermark_digest": object_digest("completion-findings"),
        }
    )
    return evidence


def test_phase_four_completion_accepts_a_distinct_completion_profile_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completion_bundle = object_digest("sealed-completion-profile")
    observed: list[tuple[str, dict[str, str]]] = []

    def verify_bundle(digest: str, bindings: Mapping[str, str]) -> bool:
        observed.append((digest, dict(bindings)))
        return digest == completion_bundle

    cp = control_plane(
        tmp_path,
        state=LifecycleState.PRODUCTION_DEPLOYED,
        lifecycle_policy=lifecycle.PHASE_FOUR_POLICY,
        bundle_verifier=verify_bundle,
    )
    evidence = completion_evidence_with_review_binding(cp)
    review_bundle = evidence["review_evidence_digest"]
    evidence["evidence_bundle_digest"] = completion_bundle
    sweeps: list[tuple[Path, Path | None]] = []

    def record_sweep(root: Path, *, exclude_run_dir: Path | None = None) -> None:
        sweeps.append((root, exclude_run_dir))

    monkeypatch.setattr(lifecycle, "purge_retained_runs", record_sweep)

    completed = cp.transition(
        LifecycleState.COMPLETED,
        context(evidence=evidence),
        reason="observation_window_passed",
    )

    assert completed.target is LifecycleState.COMPLETED
    assert completion_bundle != review_bundle
    assert sweeps == [(tmp_path.parent, tmp_path)]
    assert observed[0][0] == completion_bundle
    assert observed[0][1]["profile"] == "completion"
    assert_live_utc(observed[0][1]["as_of"])


def test_phase_four_readiness_holds_when_bundle_verifier_raises(tmp_path: Path) -> None:
    unavailable = False
    observed: list[tuple[str, dict[str, str]]] = []

    def unavailable_verifier(digest: str, bindings: Mapping[str, str]) -> bool:
        observed.append((digest, dict(bindings)))
        if unavailable:
            raise RuntimeError("immutable evidence store unavailable")
        return bool(
            digest and bindings.get("profile") == "candidate_review" and bindings.get("as_of")
        )

    cp = control_plane(
        tmp_path,
        state=LifecycleState.REVIEW_REQUIRED,
        lifecycle_policy=lifecycle.PHASE_FOUR_POLICY,
        bundle_verifier=unavailable_verifier,
    )
    rule = lifecycle.PHASE_FOUR_POLICY.rule(
        LifecycleState.REVIEW_REQUIRED,
        LifecycleState.PR_READY,
        reason="advisory_readiness_clear",
    )
    evidence = {
        name: (
            SHA
            if name == "subject_digest"
            else "a" * 40
            if name.endswith("_sha")
            else object_digest(name)
        )
        for name in rule.required_evidence
    }
    attempt = ready_attempt(evidence)
    prejournal(cp, attempt, evidence=evidence)
    assert_live_utc(observed[-1][1]["as_of"])
    record_result(cp, attempt, status="SUCCEEDED", result_digest=SHA)
    evidence.update(
        ready_attempt_digest=object_digest(asdict(attempt)),
        ready_result_digest=SHA,
    )

    unavailable = True
    with pytest.raises(TransitionDeniedError, match="sealed exact-candidate"):
        cp.transition(
            LifecycleState.PR_READY,
            context(evidence=evidence, mutation=attempt),
            reason="advisory_readiness_clear",
        )

    assert cp.state is LifecycleState.REVIEW_REQUIRED
    assert_live_utc(observed[-1][1]["as_of"])


def test_phase_four_completion_holds_when_bundle_verifier_raises(tmp_path: Path) -> None:
    observed: list[dict[str, str]] = []

    def unavailable_verifier(digest: str, bindings: Mapping[str, str]) -> bool:
        observed.append(dict(bindings))
        raise RuntimeError("immutable evidence store unavailable")

    cp = control_plane(
        tmp_path,
        state=LifecycleState.PRODUCTION_DEPLOYED,
        lifecycle_policy=lifecycle.PHASE_FOUR_POLICY,
        bundle_verifier=unavailable_verifier,
    )
    evidence = completion_evidence_with_review_binding(cp)

    with pytest.raises(TransitionDeniedError, match="valid sealed exact-subject"):
        cp.transition(
            LifecycleState.COMPLETED,
            context(evidence=evidence),
            reason="observation_window_passed",
        )

    assert cp.state is LifecycleState.PRODUCTION_DEPLOYED
    assert not cp.completion_claim_active
    assert observed[-1]["profile"] == "completion"
    assert_live_utc(observed[-1]["as_of"])


def test_phase_four_staging_requires_a_sealed_exact_merge_bundle(tmp_path: Path) -> None:
    staging_bundle = object_digest("sealed-staging-profile")
    observed: list[tuple[str, dict[str, str]]] = []

    def verify_bundle(digest: str, bindings: Mapping[str, str]) -> bool:
        observed.append((digest, dict(bindings)))
        return (
            digest == staging_bundle
            and bindings.get("profile") == "staging"
            and bool(bindings.get("as_of"))
            and bindings.get("observed_merge_sha") == "b" * 40
            and bindings.get("observed_merge_tree_digest") == object_digest("merged-tree")
        )

    cp = control_plane(
        tmp_path,
        state=LifecycleState.PR_MERGED,
        lifecycle_policy=lifecycle.PHASE_FOUR_POLICY,
        bundle_verifier=verify_bundle,
    )
    merge_result = object_digest("integrated-merge")
    cp._append(
        kind="TRANSITION",
        outcome="APPLIED",
        source=LifecycleState.PR_READY,
        target=LifecycleState.PR_MERGED,
        reason="native_merge_linearized",
        actor="github-merge-queue",
        evidence_refs={
            "merge_result_digest": merge_result,
            "merge_commit_sha": "b" * 40,
            "merge_tree_digest": object_digest("merged-tree"),
        },
        observed_at="2026-08-02T00:01:00Z",
    )
    evidence = evidence_for(
        LifecycleState.PR_MERGED,
        LifecycleState.STAGING_DEPLOYED,
        reason="staging_admitted",
    )
    evidence.update(
        subject_digest=SHA,
        evidence_bundle_digest=OTHER_SHA,
        merge_digest=merge_result,
    )
    alternate_bundle = dict(evidence)
    alternate_bundle["evidence_bundle_digest"] = staging_bundle
    assert mutation_subject_digest("deploy_staging", evidence) != mutation_subject_digest(
        "deploy_staging", alternate_bundle
    )

    with pytest.raises(TransitionDeniedError, match="staging EvidenceBundle"):
        cp.transition(
            LifecycleState.STAGING_DEPLOYED,
            context(evidence=evidence),
            reason="staging_admitted",
        )

    invalid_attempt = MutationAttempt(
        attempt_id="phase-four-staging-invalid",
        idempotency_key="stage:run-65:phase-four-invalid",
        subject_digest=SHA,
        action="deploy_staging",
        step_plan_digest=mutation_subject_digest("deploy_staging", evidence),
        status="PLANNED",
    )
    with pytest.raises(TransitionDeniedError, match="valid sealed exact-subject bundle"):
        prejournal(cp, invalid_attempt, evidence=evidence)

    evidence["evidence_bundle_digest"] = staging_bundle
    wrong_merge = dict(evidence)
    wrong_merge["merge_digest"] = object_digest("unrelated-merge")
    wrong_merge_attempt = MutationAttempt(
        attempt_id="phase-four-staging-wrong-merge",
        idempotency_key="stage:run-65:phase-four-wrong-merge",
        subject_digest=SHA,
        action="deploy_staging",
        step_plan_digest=mutation_subject_digest("deploy_staging", wrong_merge),
        status="PLANNED",
    )
    with pytest.raises(TransitionDeniedError, match="exact integrated merge"):
        prejournal(cp, wrong_merge_attempt, evidence=wrong_merge)

    attempt = MutationAttempt(
        attempt_id="phase-four-staging",
        idempotency_key="stage:run-65:phase-four",
        subject_digest=SHA,
        action="deploy_staging",
        step_plan_digest=mutation_subject_digest("deploy_staging", evidence),
        status="PLANNED",
    )
    prejournal(cp, attempt, evidence=evidence)
    record_result(cp, attempt, status="SUCCEEDED", result_digest=SHA)
    evidence["staging_attempt_digest"] = object_digest(asdict(attempt))
    evidence["staging_result_digest"] = SHA

    deployed = cp.transition(
        LifecycleState.STAGING_DEPLOYED,
        context(evidence=evidence, mutation=attempt),
        reason="staging_admitted",
    )

    assert deployed.target is LifecycleState.STAGING_DEPLOYED
    assert observed[-1][0] == staging_bundle
    assert_live_utc(observed[-1][1]["as_of"])
    assert_live_utc(observed[-2][1]["as_of"])


def test_completion_binds_release_to_persisted_merge_not_review_head(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.PRODUCTION_DEPLOYED)
    evidence = completion_evidence_with_review_binding(cp)
    deployed_sha = "b" * 40
    cp._append(
        kind="TRANSITION",
        outcome="APPLIED",
        source=LifecycleState.PR_READY,
        target=LifecycleState.PR_MERGED,
        reason="native_merge_linearized",
        actor="merge-queue",
        evidence_refs={"merge_commit_sha": deployed_sha},
        observed_at="2026-08-02T00:01:00Z",
    )
    evidence["release_sha"] = deployed_sha
    cp.transition(
        LifecycleState.COMPLETED,
        context(evidence=evidence),
        reason="observation_window_passed",
    )


def production_approval_for(evidence: dict[str, str]) -> Approval:
    approval = Approval(
        approval_id="production-approval-1",
        actor="release-owner",
        subject_digest=SHA,
        kind="PRODUCTION",
        eligible=True,
        active=True,
        reviewed_commit_sha=evidence["merge_commit_sha"],
        reviewed_candidate_digest=evidence["artifact_digest"],
        review_evidence_digest=lifecycle._production_approval_scope_digest(evidence),
    )
    return replace(
        approval,
        authentication_evidence_digest=external_proof(
            approval.actor,
            OWNER_CREDENTIAL_DIGEST,
            lifecycle._production_approval_payload(approval),
        ),
    )


def completion_invalidation_context(
    cp: LifecycleControlPlane,
    *,
    target: LifecycleState = LifecycleState.LIVE_VERIFICATION_FAILED,
    reason: str = "completion_evidence_invalidated",
) -> TransitionContext:
    base_actor = context().actor
    capabilities = frozenset({"lifecycle.transition", "lifecycle.completion.revoke"})
    actor_claims = {
        "actor_id": "monitor-1",
        "role": "lifecycle-monitor",
        "authenticated": True,
        "capabilities": sorted(capabilities),
        "subject_digest": SHA,
        "authority_digest": base_actor.authority_digest,
    }
    monitor = replace(
        base_actor,
        actor_id="monitor-1",
        role="lifecycle-monitor",
        capabilities=capabilities,
        authentication_evidence_digest=external_proof(
            "monitor-1", base_actor.authority_digest, actor_claims
        ),
    )
    completion_event = next(
        event for event in reversed(cp.events) if event.kind == "COMPLETION_CLAIMED"
    )
    evidence = evidence_for(LifecycleState.COMPLETED, target, reason=reason)
    identity_digest = object_digest(
        {
            "actor_id": monitor.actor_id,
            "role": monitor.role,
            "subject_digest": monitor.subject_digest,
        }
    )
    trigger_digest = evidence.get("incident_digest", evidence.get("safe_state_digest", ""))
    integrity_payload = {
        "monitor_id": monitor.actor_id,
        "authority_digest": SHA,
        "subject_digest": SHA,
        "actor_id": monitor.actor_id,
        "role": monitor.role,
        "trigger_digest": trigger_digest,
        "observed_at": "2026-08-02T00:01:00Z",
    }
    evidence.update(
        {
            "subject_digest": SHA,
            "completion_event_digest": completion_event.event_digest,
            "monitor_identity_digest": identity_digest,
            "monitor_authentication_evidence_digest": (monitor.authentication_evidence_digest),
            "integrity_monitor_id": monitor.actor_id,
            "integrity_monitor_authority_digest": SHA,
            "integrity_monitor_authentication_evidence_digest": external_proof(
                monitor.actor_id, SHA, integrity_payload
            ),
            "invalidation_digest": object_digest(
                {
                    "completion_event_digest": completion_event.event_digest,
                    "monitor_authentication_evidence_digest": (
                        monitor.authentication_evidence_digest
                    ),
                    "monitor_identity_digest": identity_digest,
                    "subject_digest": SHA,
                    "trigger_digest": trigger_digest,
                }
            ),
        }
    )
    return context(actor=monitor, evidence=evidence)


def extension_authorization(
    cp: LifecycleControlPlane,
    proposed: BudgetPolicy,
    *,
    amounts: dict[str, int],
    authority_snapshot: AuthoritySnapshot | None = None,
    admission_challenge: str | None = None,
) -> lifecycle.BudgetExtensionAuthorization:
    current_authority = authority_snapshot or authority(observed_at="2026-08-02T12:00:00Z")
    challenge = (
        admission_challenge
        or cp._budget_extension_challenge
        or cp.issue_budget_extension_challenge()
    )
    body = {
        "extension_id": f"extension:{proposed.version}",
        "owner_id": proposed.approved_by,
        "owner_role": "delivery-owner",
        "authenticated": True,
        "capabilities": ["lifecycle.budget.extend"],
        "run_id": cp.run_id,
        "subject_digest": cp.subject_digest,
        "authority_digest": current_authority.digest,
        "credential_digest": OWNER_CREDENTIAL_DIGEST,
        "prior_policy_digest": object_digest(lifecycle._budget_policy_payload(cp.budget_policy)),
        "proposed_policy_digest": object_digest(lifecycle._budget_policy_payload(proposed)),
        "amounts": amounts,
        "reason": "owner-approved bounded continuation",
        "valid_from": "2026-08-02T00:00:00Z",
        "valid_until": "2026-08-03T00:00:00Z",
        "authority_observer_id": "authority-observer",
        "authority_observer_authority_digest": SHA,
        "authority_current_time": current_authority.observed_at,
        "admission_challenge": challenge,
    }
    return lifecycle.BudgetExtensionAuthorization(
        extension_id=str(body["extension_id"]),
        owner_id=str(body["owner_id"]),
        owner_role=str(body["owner_role"]),
        authenticated=bool(body["authenticated"]),
        capabilities=frozenset({"lifecycle.budget.extend"}),
        run_id=str(body["run_id"]),
        subject_digest=str(body["subject_digest"]),
        authority_digest=str(body["authority_digest"]),
        credential_digest=str(body["credential_digest"]),
        prior_policy_digest=str(body["prior_policy_digest"]),
        proposed_policy_digest=str(body["proposed_policy_digest"]),
        amounts=amounts,
        reason=str(body["reason"]),
        valid_from=str(body["valid_from"]),
        valid_until=str(body["valid_until"]),
        authority_observer_id=str(body["authority_observer_id"]),
        authority_observer_authority_digest=str(body["authority_observer_authority_digest"]),
        authority_current_time=str(body["authority_current_time"]),
        admission_challenge=str(body["admission_challenge"]),
        authority_authentication_evidence_digest=external_proof(
            "authority-observer",
            SHA,
            {
                "observer_id": "authority-observer",
                "authority_digest": SHA,
                "subject_digest": SHA,
                "contract_version": current_authority.contract_version,
                "publisher_version": current_authority.publisher_version,
                "contract_active": current_authority.contract_active,
                "publisher_active": current_authority.publisher_active,
                "authority_observed_at": current_authority.observed_at,
                "valid_until": current_authority.valid_until,
                "authority_current_time": str(body["authority_current_time"]),
                "admission_challenge": str(body["admission_challenge"]),
            },
        ),
        evidence_digest=external_proof(str(body["owner_id"]), str(body["credential_digest"]), body),
    )


def test_phase_zero_policy_is_versioned_digest_bound_and_complete() -> None:
    assert PHASE_ZERO_POLICY.version == "phase-zero-v2"
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
    with pytest.raises(TransitionDeniedError, match="illegal transition"):
        cp.transition(LifecycleState.IMPLEMENTATION_IN_PROGRESS, context(), reason="begin_work")
    with pytest.raises(TransitionDeniedError, match="required evidence"):
        cp.transition(
            LifecycleState.CONTRACT_APPROVED,
            context(evidence={"subject_digest": SHA}),
            reason="contract_admitted",
        )
    assert cp.state is LifecycleState.CONTRACT_RECEIVED
    assert cp.events[-1].outcome == "DENIED"


def test_noncanonical_evidence_digest_fails_closed(tmp_path: Path) -> None:
    cp = control_plane(tmp_path)
    required = evidence_for(
        LifecycleState.CONTRACT_RECEIVED,
        LifecycleState.CONTRACT_APPROVED,
        reason="contract_admitted",
    )
    required["contract_digest"] = "looks-like-evidence-but-is-not-a-digest"
    with pytest.raises(TransitionDeniedError, match="canonical digest"):
        cp.transition(
            LifecycleState.CONTRACT_APPROVED,
            context(evidence=required),
            reason="contract_admitted",
        )


def test_draft_pr_side_effect_plan_has_one_enforced_order(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.IMPLEMENTATION_PLANNED)
    required = evidence_for(
        LifecycleState.IMPLEMENTATION_PLANNED,
        LifecycleState.DRAFT_PR_OPEN,
        reason="draft_pr_admitted",
    )
    out_of_order = MutationAttempt(
        attempt_id="draft-1",
        idempotency_key="draft:run-65:1",
        subject_digest=SHA,
        action="open_draft_pr",
        step_plan_digest=OTHER_SHA,
        status="PLANNED",
        steps=("branch", "issue", "red_commit", "draft_pr"),
    )
    with pytest.raises(TransitionDeniedError, match="issue, branch"):
        cp.transition(
            LifecycleState.DRAFT_PR_OPEN,
            context(evidence=required, mutation=out_of_order),
            reason="draft_pr_admitted",
        )


def test_forward_work_revalidates_contract_and_publisher_authority(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.DRAFT_PR_OPEN)
    required = evidence_for(
        LifecycleState.DRAFT_PR_OPEN,
        LifecycleState.IMPLEMENTATION_IN_PROGRESS,
        reason="begin_work",
    )
    with pytest.raises(TransitionDeniedError, match="authority"):
        cp.transition(
            LifecycleState.IMPLEMENTATION_IN_PROGRESS,
            context(current_authority=False, evidence=required),
            reason="begin_work",
        )
    assert cp.state is LifecycleState.DRAFT_PR_OPEN


def test_observers_append_digest_bound_evidence_but_cannot_change_state(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.PR_READY)
    event = cp.record_observation(
        source="live-observer",
        subject_digest=SHA,
        payload_digest=OTHER_SHA,
        signature=external_proof(
            "live-observer",
            SHA,
            {
                "source": "live-observer",
                "subject_digest": SHA,
                "payload_digest": OTHER_SHA,
                "observed_at": "2026-08-02T00:02:00Z",
            },
        ),
        observed_at="2026-08-02T00:02:00Z",
    )
    assert event.kind == "OBSERVATION"
    assert cp.state is LifecycleState.PR_READY
    assert LifecycleControlPlane.load(tmp_path).state is LifecycleState.PR_READY


def test_observation_rejects_an_untrusted_or_forged_live_source(tmp_path: Path) -> None:
    cp = control_plane(tmp_path)

    with pytest.raises(TransitionDeniedError, match="observation source is not authenticated"):
        cp.record_observation(
            source="live-observer",
            subject_digest=SHA,
            payload_digest=OTHER_SHA,
            signature=OTHER_SHA,
            observed_at="2026-08-02T00:02:00Z",
        )

    assert cp.events[-1].kind == "STATE_CREATED"


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
    with pytest.raises(TransitionDeniedError, match="budget"):
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
    with pytest.raises(TransitionDeniedError, match="worker"):
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
    bind_work_evidence(required, stopped)
    event = cp.transition(
        LifecycleState.BUDGET_EXCEEDED,
        context(
            usage=exhausted,
            work=stopped,
            evidence=required,
        ),
        reason="delivery_budget_exhausted",
    )
    assert event.resume_state is LifecycleState.IMPLEMENTATION_IN_PROGRESS


def test_reserved_safety_budget_cannot_authorize_forward_work(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.STAGING_DEPLOYED)
    _, exhausted = budgets(tokens=100)
    rollout = RolloutStatus(staging="ACTIVE", canary="UNKNOWN")
    forward = evidence_for(
        LifecycleState.STAGING_DEPLOYED,
        LifecycleState.CANARY_DEPLOYED,
        reason="canary_admitted",
    )
    with pytest.raises(TransitionDeniedError, match="budget"):
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
        step_plan_digest=rollback_plan(),
        status="PLANNED",
    )
    safety = evidence_for(
        LifecycleState.STAGING_DEPLOYED,
        LifecycleState.ROLLBACK_IN_PROGRESS,
        reason="canary_mutation_indeterminate",
    )
    safety["rollback_attempt_digest"] = object_digest(asdict(attempt))
    prejournal(cp, attempt)
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
        source="finding-source",
        exact_subject_digest=SHA,
        severity="HIGH",
        credible=True,
        blocking=True,
        reviewer_eligible=False,
        category="ENGINEERING",
        disposition="ACCEPTED_FOR_REPAIR",
        affected_scope_digest=OTHER_SHA,
    )
    required["finding_digest"] = object_digest(asdict(finding))
    _, at_limit = budgets()
    at_limit = replace(
        at_limit,
        repair_attempts_by_finding={"finding-1": 2},
        repair_attempts_by_stage={LifecycleState.REVIEW_FAILED.value: 2},
    )
    with pytest.raises(TransitionDeniedError, match="repair attempt"):
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
        source="finding-source",
        exact_subject_digest=SHA,
        severity="HIGH",
        credible=True,
        blocking=True,
        reviewer_eligible=False,
        category="ENGINEERING",
        disposition="ACCEPTED",
        affected_scope_digest=OTHER_SHA,
    )
    required["finding_digest"] = object_digest(asdict(signal))
    required["ready_revocation_observation_digest"] = OTHER_SHA
    revocation = draft_revocation_attempt(required)
    prejournal(cp, revocation)
    record_result(cp, revocation, status="SUCCEEDED", result_digest=SHA)
    required.update(
        ready_revocation_attempt_digest=object_digest(asdict(revocation)),
        ready_revocation_result_digest=SHA,
    )
    cp.transition(
        LifecycleState.REVIEW_FAILED,
        context(evidence=required, finding=signal, mutation=revocation),
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
        reviewed_commit_sha=required["reviewed_commit_sha"],
        reviewed_candidate_digest=required["prospective_tree_digest"],
        review_evidence_digest=required["verification_bundle_digest"],
    )
    required["review_digest"] = object_digest(asdict(ineligible))
    with pytest.raises(TransitionDeniedError, match="eligible formal review"):
        cp.transition(
            LifecycleState.PR_READY,
            context(evidence=required, approvals=(ineligible,)),
            reason="formal_review_clear",
        )
    unsigned = replace(ineligible, approval_id="review-2", actor="codex", eligible=True)
    eligible = replace(
        unsigned,
        authentication_evidence_digest=external_proof(
            "codex", SHA, lifecycle._production_approval_payload(unsigned)
        ),
    )
    required["review_digest"] = object_digest(asdict(eligible))
    ready = ready_attempt(required)
    prejournal(cp, ready)
    record_result(cp, ready, status="SUCCEEDED", result_digest=SHA)
    required.update(
        ready_attempt_digest=object_digest(asdict(ready)),
        ready_result_digest=SHA,
        ready_observation_digest=OTHER_SHA,
    )
    cp.transition(
        LifecycleState.PR_READY,
        context(evidence=required, approvals=(eligible,), mutation=ready),
        reason="formal_review_clear",
    )


def test_formal_review_rejects_self_computed_reviewer_credential(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.REVIEW_REQUIRED)
    required = evidence_for(
        LifecycleState.REVIEW_REQUIRED,
        LifecycleState.PR_READY,
        reason="formal_review_clear",
    )
    forged = Approval(
        approval_id="forged-review",
        actor="codex",
        subject_digest=SHA,
        kind="FORMAL_REVIEW",
        eligible=True,
        active=True,
        reviewed_commit_sha=required["reviewed_commit_sha"],
        reviewed_candidate_digest=required["prospective_tree_digest"],
        review_evidence_digest=required["verification_bundle_digest"],
        authentication_evidence_digest=object_digest({"self": "asserted"}),
    )
    required["review_digest"] = object_digest(asdict(forged))
    with pytest.raises(TransitionDeniedError, match="eligible formal review"):
        cp.transition(
            LifecycleState.PR_READY,
            context(evidence=required, approvals=(forged,)),
            reason="formal_review_clear",
        )


def test_finding_rejection_requires_authenticated_owner_disposition(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.REVIEW_FAILED)
    required = evidence_for(
        LifecycleState.REVIEW_FAILED,
        LifecycleState.REVIEW_REQUIRED,
        reason="finding_rejected_with_evidence",
    )
    required.update(
        finding_disposition_source_id="finding-source",
        finding_disposition_authority_digest=SHA,
        finding_disposition_authentication_evidence_digest=OTHER_SHA,
    )

    with pytest.raises(TransitionDeniedError, match="finding disposition"):
        cp.transition(
            LifecycleState.REVIEW_REQUIRED,
            context(evidence=required),
            reason="finding_rejected_with_evidence",
        )


def test_external_mutation_requires_prejournaled_unique_attempt(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.PR_MERGED)
    required = evidence_for(
        LifecycleState.PR_MERGED,
        LifecycleState.STAGING_DEPLOYED,
        reason="staging_admitted",
    )
    record_integrated_merge(cp, required["merge_digest"])
    with pytest.raises(TransitionDeniedError, match="mutation attempt"):
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
        step_plan_digest=mutation_subject_digest("deploy_staging", required),
        status="PLANNED",
    )
    prejournal(cp, attempt)
    with pytest.raises(TransitionDeniedError, match="successful exact-attempt"):
        cp.transition(
            LifecycleState.STAGING_DEPLOYED,
            context(evidence=required, mutation=attempt),
            reason="staging_admitted",
        )
    record_result(cp, attempt, status="SUCCEEDED", result_digest=SHA)
    required["staging_result_digest"] = SHA
    required["staging_attempt_digest"] = object_digest(asdict(attempt))
    cp.transition(
        LifecycleState.STAGING_DEPLOYED,
        context(evidence=required, mutation=attempt),
        reason="staging_admitted",
    )
    with pytest.raises(TransitionDeniedError, match="idempotency key"):
        record_result(
            cp,
            replace(attempt, attempt_id="attempt-stage-2"),
            status="SUCCEEDED",
            result_digest=SHA,
        )


def test_staging_requires_an_authenticated_inventory_from_every_configured_source(
    tmp_path: Path,
) -> None:
    trust_policy = replace(
        TRUST_POLICY,
        finding_sources={"finding-source": SHA, "secondary-scanner": OTHER_SHA},
    )
    policy, _ = budgets()
    cp = LifecycleControlPlane.create(
        tmp_path,
        run_id="two-source-promotion",
        subject_digest=SHA,
        initial_state=LifecycleState.CONTRACT_RECEIVED,
        budget_policy=policy,
        lifecycle_policy=PHASE_ZERO_POLICY,
        trust_policy=trust_policy,
        evidence_verifier=verify_external_proof,
    )
    cp._append(
        kind="MIGRATION_ADMITTED",
        outcome="APPLIED",
        source=LifecycleState.CONTRACT_RECEIVED,
        target=LifecycleState.PR_MERGED,
        reason="test_fixture_migration",
        actor="test-fixture",
        evidence_refs={"subject_digest": SHA},
        observed_at="2026-08-02T00:01:00Z",
    )
    cp._state = LifecycleState.PR_MERGED
    required = evidence_for(
        LifecycleState.PR_MERGED,
        LifecycleState.STAGING_DEPLOYED,
        reason="staging_admitted",
    )
    required.update(
        finding_source_set_digest=object_digest(dict(trust_policy.finding_sources)),
        finding_inventory_epochs_digest=object_digest({"finding-source": OTHER_SHA}),
    )

    with pytest.raises(TransitionDeniedError, match="current trusted finding inventory"):
        cp.transition(
            LifecycleState.STAGING_DEPLOYED,
            context(evidence=required),
            reason="staging_admitted",
        )


def test_staging_fails_closed_when_no_finding_source_is_configured(tmp_path: Path) -> None:
    cp = control_plane(
        tmp_path,
        state=LifecycleState.PR_MERGED,
        trust_policy=replace(TRUST_POLICY, finding_sources={}),
    )
    required = evidence_for(
        LifecycleState.PR_MERGED,
        LifecycleState.STAGING_DEPLOYED,
        reason="staging_admitted",
    )
    required.update(
        finding_source_set_digest=object_digest({}),
        finding_inventory_epochs_digest=object_digest({}),
    )

    with pytest.raises(TransitionDeniedError, match="current trusted finding inventory"):
        cp.transition(
            LifecycleState.STAGING_DEPLOYED,
            context(evidence=required),
            reason="staging_admitted",
        )


def test_staging_mutation_subject_binds_complete_promotion_fence() -> None:
    baseline = dict.fromkeys(lifecycle._MUTATION_SUBJECT_FIELDS["deploy_staging"], SHA)
    for field in (
        "configuration_digest",
        "deployment_target_digest",
        "staging_authorization_digest",
        "finding_source_set_digest",
        "finding_inventory_epochs_digest",
        "authority_fence_digest",
    ):
        changed = dict(baseline)
        changed[field] = OTHER_SHA
        assert mutation_subject_digest("deploy_staging", baseline) != mutation_subject_digest(
            "deploy_staging", changed
        )


def test_rollback_mutation_subject_binds_failed_and_restoration_targets() -> None:
    baseline = dict.fromkeys(lifecycle._MUTATION_SUBJECT_FIELDS["rollback"], SHA)
    for field in (
        "failed_deployment_digest",
        "restoration_target_digest",
        "migration_plan_digest",
    ):
        changed = dict(baseline)
        changed[field] = OTHER_SHA
        assert mutation_subject_digest("rollback", baseline) != mutation_subject_digest(
            "rollback", changed
        )


def test_production_admission_requires_live_exact_subject_approval(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.PRODUCTION_APPROVAL_REQUIRED)
    required = evidence_for(
        LifecycleState.PRODUCTION_APPROVAL_REQUIRED,
        LifecycleState.PRODUCTION_DEPLOYED,
        reason="production_admitted",
    )
    required["production_result_digest"] = SHA
    required.update(record_active_canary_binding(cp))
    approval = production_approval_for(required)
    required["production_approval_digest"] = object_digest(asdict(approval))
    attempt = MutationAttempt(
        attempt_id="attempt-production-approval",
        idempotency_key="production:run-65:approval",
        subject_digest=SHA,
        action="deploy_production",
        step_plan_digest=mutation_subject_digest("deploy_production", required),
        status="PLANNED",
    )
    prejournal(cp, attempt)
    record_result(cp, attempt, status="SUCCEEDED", result_digest=SHA)
    required["production_attempt_digest"] = object_digest(asdict(attempt))

    with pytest.raises(TransitionDeniedError, match="production approval"):
        cp.transition(
            LifecycleState.PRODUCTION_DEPLOYED,
            context(
                evidence=required,
                mutation=attempt,
                rollout=RolloutStatus(canary="ACTIVE"),
            ),
            reason="production_admitted",
        )

    forged = replace(
        approval,
        authentication_evidence_digest=object_digest(
            lifecycle._production_approval_payload(approval)
        ),
    )
    required["production_approval_digest"] = object_digest(asdict(forged))
    with pytest.raises(TransitionDeniedError, match="production approval"):
        cp.transition(
            LifecycleState.PRODUCTION_DEPLOYED,
            context(
                evidence=required,
                mutation=attempt,
                approvals=(forged,),
                rollout=RolloutStatus(canary="ACTIVE"),
            ),
            reason="production_admitted",
        )

    required["production_approval_digest"] = object_digest(asdict(approval))

    cp.transition(
        LifecycleState.PRODUCTION_DEPLOYED,
        context(
            evidence=required,
            mutation=attempt,
            approvals=(approval,),
            rollout=RolloutStatus(canary="ACTIVE"),
        ),
        reason="production_admitted",
    )


def test_denial_synchronizes_monotonic_budget_state_before_retry(tmp_path: Path) -> None:
    cp = control_plane(tmp_path)
    observed_usage = BudgetUsage(counters={"tokens": 5})
    with pytest.raises(TransitionDeniedError, match="illegal transition"):
        cp.transition(
            LifecycleState.IMPLEMENTATION_IN_PROGRESS,
            context(usage=observed_usage),
            reason="begin_work",
        )
    assert cp.budget_usage.counters["tokens"] == 5

    cp.transition(
        LifecycleState.CONTRACT_APPROVED,
        context(
            usage=observed_usage,
            evidence=evidence_for(
                LifecycleState.CONTRACT_RECEIVED,
                LifecycleState.CONTRACT_APPROVED,
                reason="contract_admitted",
            ),
        ),
        reason="contract_admitted",
    )
    assert LifecycleControlPlane.load(tmp_path).budget_usage.counters["tokens"] == 5


def test_forward_transition_rejects_reused_authority_observation(tmp_path: Path) -> None:
    cp = control_plane(tmp_path)
    stale = replace(authority(), observed_at="2026-08-01T00:00:00Z")
    stale_context = replace(
        context(
            evidence=evidence_for(
                LifecycleState.CONTRACT_RECEIVED,
                LifecycleState.CONTRACT_APPROVED,
                reason="contract_admitted",
            )
        ),
        authority=stale,
    )
    with pytest.raises(TransitionDeniedError, match="authority"):
        cp.transition(
            LifecycleState.CONTRACT_APPROVED,
            stale_context,
            reason="contract_admitted",
        )


def test_forward_transition_requires_independent_authority_attestation(tmp_path: Path) -> None:
    cp = control_plane(tmp_path)
    required = evidence_for(
        LifecycleState.CONTRACT_RECEIVED,
        LifecycleState.CONTRACT_APPROVED,
        reason="contract_admitted",
    )
    forged = context(evidence=required)
    forged_evidence = dict(forged.evidence)
    forged_evidence["authority_authentication_evidence_digest"] = OTHER_SHA

    with pytest.raises(TransitionDeniedError, match="contract or publisher authority"):
        cp.transition(
            LifecycleState.CONTRACT_APPROVED,
            replace(forged, evidence=forged_evidence),
            reason="contract_admitted",
        )


def test_forward_transition_rejects_authority_time_before_the_sealed_ledger_clock(
    tmp_path: Path,
) -> None:
    cp = control_plane(tmp_path)
    cp._append(
        kind="TRANSITION",
        outcome="APPLIED",
        source=LifecycleState.CONTRACT_RECEIVED,
        target=LifecycleState.CONTRACT_RECEIVED,
        reason="trusted_clock_fixture",
        actor="authority-observer",
        evidence_refs={"subject_digest": SHA},
        observed_at="2026-08-02T01:00:00Z",
    )
    required = evidence_for(
        LifecycleState.CONTRACT_RECEIVED,
        LifecycleState.CONTRACT_APPROVED,
        reason="contract_admitted",
    )

    with pytest.raises(TransitionDeniedError, match="contract or publisher authority"):
        cp.transition(
            LifecycleState.CONTRACT_APPROVED,
            context(evidence=required),
            reason="contract_admitted",
        )


def test_mutation_admission_binds_evidence_to_persisted_result(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.PR_MERGED)
    required = evidence_for(
        LifecycleState.PR_MERGED,
        LifecycleState.STAGING_DEPLOYED,
        reason="staging_admitted",
    )
    record_integrated_merge(cp, required["merge_digest"])
    attempt = MutationAttempt(
        attempt_id="attempt-stage-result-binding",
        idempotency_key="stage:run-65:result-binding",
        subject_digest=SHA,
        action="deploy_staging",
        step_plan_digest=mutation_subject_digest("deploy_staging", required),
        status="PLANNED",
    )
    prejournal(cp, attempt)
    record_result(cp, attempt, status="SUCCEEDED", result_digest=SHA)
    required["staging_result_digest"] = OTHER_SHA
    with pytest.raises(TransitionDeniedError, match="persisted mutation result"):
        cp.transition(
            LifecycleState.STAGING_DEPLOYED,
            context(evidence=required, mutation=attempt),
            reason="staging_admitted",
        )

    required["staging_result_digest"] = SHA
    required["staging_attempt_digest"] = object_digest(asdict(attempt))
    cp.transition(
        LifecycleState.STAGING_DEPLOYED,
        context(evidence=required, mutation=attempt),
        reason="staging_admitted",
    )


def test_missing_adapter_response_never_implies_success(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.STAGING_DEPLOYED)
    attempt = MutationAttempt(
        attempt_id="attempt-1",
        idempotency_key="cleanup:run-65:1",
        subject_digest=SHA,
        action="rollback",
        step_plan_digest=OTHER_SHA,
        status="PLANNED",
    )
    prejournal(cp, attempt)
    result = record_result(cp, attempt, status="UNKNOWN", result_digest=None)
    assert result.status == "UNKNOWN"
    assert not result.successful


def test_active_exposure_cannot_stop_or_request_product_input_before_rollback(
    tmp_path: Path,
) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.CANARY_DEPLOYED)
    rollout = RolloutStatus(staging="ACTIVE", canary="ACTIVE")
    with pytest.raises(TransitionDeniedError, match="rollback"):
        cp.transition(
            LifecycleState.BLOCKED,
            context(rollout=rollout),
            reason="external_dependency",
        )
    with pytest.raises(TransitionDeniedError, match="rollback"):
        cp.transition(
            LifecycleState.PRODUCT_INPUT_REQUIRED,
            context(rollout=rollout),
            reason="authority_invalidated",
        )


def test_completed_requires_exact_release_live_rollback_and_observation_evidence(
    tmp_path: Path,
) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.PRODUCTION_DEPLOYED)
    required = completion_evidence_with_review_binding(cp)
    missing = dict(required)
    missing.pop("rollback_readiness_digest")
    with pytest.raises(TransitionDeniedError, match="required evidence"):
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


def test_phase_four_completion_rechecks_current_authenticated_blocking_findings(
    tmp_path: Path,
) -> None:
    def verify_completion_bundle(digest: str, bindings: Mapping[str, str]) -> bool:
        return bool(digest and all(bindings.values()))

    cp = control_plane(
        tmp_path,
        state=LifecycleState.PRODUCTION_DEPLOYED,
        lifecycle_policy=lifecycle.PHASE_FOUR_POLICY,
        bundle_verifier=verify_completion_bundle,
    )
    required = completion_evidence_with_review_binding(cp)
    required["finding_high_watermark_digest"] = object_digest("completion-findings")
    finding = FindingSignal(
        finding_id="late-production-blocker",
        source="finding-source",
        exact_subject_digest=SHA,
        severity="HIGH",
        credible=True,
        blocking=True,
        reviewer_eligible=False,
        category="ENGINEERING",
        disposition="OPEN",
        affected_scope_digest=OTHER_SHA,
    )

    with pytest.raises(TransitionDeniedError, match="pending blocking finding"):
        cp.transition(
            LifecycleState.COMPLETED,
            context(evidence=required, finding=finding),
            reason="observation_window_passed",
        )

    assert cp.state is LifecycleState.PRODUCTION_DEPLOYED
    assert not cp.completion_claim_active


def test_completion_rejects_live_attestation_replayed_for_a_different_release(
    tmp_path: Path,
) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.PRODUCTION_DEPLOYED)
    required = completion_evidence_with_review_binding(cp)
    signed = context(evidence=required)
    replayed = dict(signed.evidence)
    replayed["release_sha"] = "b" * 40

    with pytest.raises(TransitionDeniedError, match="trusted live observation"):
        cp.transition(
            LifecycleState.COMPLETED,
            replace(signed, evidence=replayed),
            reason="observation_window_passed",
        )


def test_completion_claim_is_revoked_append_only_on_admitted_invalidation(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.PRODUCTION_DEPLOYED)
    done = completion_evidence_with_review_binding(cp)
    cp.transition(
        LifecycleState.COMPLETED,
        context(evidence=done),
        reason="observation_window_passed",
    )
    before = len(cp.events)
    cp.transition(
        LifecycleState.LIVE_VERIFICATION_FAILED,
        completion_invalidation_context(cp),
        reason="completion_evidence_invalidated",
    )
    assert not cp.completion_claim_active
    assert len(cp.events) == before + 1
    assert any(event.kind == "COMPLETION_CLAIMED" for event in cp.events)
    assert cp.events[-1].kind == "COMPLETION_REVOKED"


def test_completion_revocation_remains_available_when_delivery_authority_is_revoked(
    tmp_path: Path,
) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.PRODUCTION_DEPLOYED)
    cp.transition(
        LifecycleState.COMPLETED,
        context(evidence=completion_evidence_with_review_binding(cp)),
        reason="observation_window_passed",
    )
    revoked = authority(current=False)
    invalidation = completion_invalidation_context(cp)
    actor = invalidation.actor
    actor_claims = {
        "actor_id": actor.actor_id,
        "role": actor.role,
        "authenticated": actor.authenticated,
        "capabilities": sorted(actor.capabilities),
        "subject_digest": actor.subject_digest,
        "authority_digest": revoked.digest,
    }
    monitor = replace(
        actor,
        authority_digest=revoked.digest,
        authentication_evidence_digest=external_proof("monitor-1", revoked.digest, actor_claims),
    )
    evidence = dict(invalidation.evidence)
    evidence["monitor_authentication_evidence_digest"] = monitor.authentication_evidence_digest
    evidence["invalidation_digest"] = object_digest(
        {
            "completion_event_digest": evidence["completion_event_digest"],
            "monitor_authentication_evidence_digest": monitor.authentication_evidence_digest,
            "monitor_identity_digest": evidence["monitor_identity_digest"],
            "subject_digest": SHA,
            "trigger_digest": evidence["incident_digest"],
        }
    )

    cp.transition(
        LifecycleState.LIVE_VERIFICATION_FAILED,
        replace(invalidation, actor=monitor, authority=revoked, evidence=evidence),
        reason="completion_evidence_invalidated",
    )
    assert not cp.completion_claim_active


def test_completion_revocation_rejects_a_forged_integrity_monitor_attestation(
    tmp_path: Path,
) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.PRODUCTION_DEPLOYED)
    cp.transition(
        LifecycleState.COMPLETED,
        context(evidence=completion_evidence_with_review_binding(cp)),
        reason="observation_window_passed",
    )
    invalidation = completion_invalidation_context(cp)
    forged = dict(invalidation.evidence)
    forged["integrity_monitor_authentication_evidence_digest"] = OTHER_SHA

    with pytest.raises(TransitionDeniedError, match="completion revocation"):
        cp.transition(
            LifecycleState.LIVE_VERIFICATION_FAILED,
            replace(invalidation, evidence=forged),
            reason="completion_evidence_invalidated",
        )


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


def test_legacy_migration_is_readable_but_stops_for_phase_zero_readmission(
    tmp_path: Path,
) -> None:
    policy, _ = budgets()
    migration = migrate_legacy_state({"version": 2, "stage": "deploy"})

    cp = LifecycleControlPlane.admit_legacy_migration(
        tmp_path,
        run_id="legacy-run-65",
        subject_digest=SHA,
        budget_policy=policy,
        migration=migration,
        trust_policy=TRUST_POLICY,
        evidence_verifier=verify_external_proof,
    )

    assert cp.state is LifecycleState.PRODUCT_INPUT_REQUIRED
    admitted = cp.events[-1]
    assert admitted.kind == "MIGRATION_ADMITTED"
    assert admitted.evidence_refs["legacy_migration_digest"] == migration.digest
    assert LifecycleControlPlane.load(tmp_path, evidence_verifier=verify_external_proof).state is (
        LifecycleState.PRODUCT_INPUT_REQUIRED
    )


def test_replay_rejects_mutation_result_when_prejournal_is_missing(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.PR_MERGED)
    attempt = MutationAttempt(
        attempt_id="missing-journal-attempt",
        idempotency_key="stage:run-65:missing-journal",
        subject_digest=SHA,
        action="deploy_staging",
        step_plan_digest=mutation_subject_digest(
            "deploy_staging",
            evidence_for(
                LifecycleState.PR_MERGED,
                LifecycleState.STAGING_DEPLOYED,
                reason="staging_admitted",
            ),
        ),
        status="PLANNED",
    )
    prejournal(cp, attempt)
    record_result(cp, attempt, status="SUCCEEDED", result_digest=SHA)
    cp.mutation_path.unlink()

    with pytest.raises(ValueError, match="mutation result adapter evidence is invalid"):
        LifecycleControlPlane.load(tmp_path, evidence_verifier=verify_external_proof)


def test_legacy_migration_rejects_a_different_existing_admission(tmp_path: Path) -> None:
    policy, _ = budgets()
    admitted = migrate_legacy_state({"version": 2, "stage": "deploy"})
    different = migrate_legacy_state({"version": 2, "stage": "review"})
    LifecycleControlPlane.admit_legacy_migration(
        tmp_path,
        run_id="legacy-run-65",
        subject_digest=SHA,
        budget_policy=policy,
        migration=admitted,
        trust_policy=TRUST_POLICY,
        evidence_verifier=verify_external_proof,
    )

    with pytest.raises(ValueError, match="different migration admission"):
        LifecycleControlPlane.admit_legacy_migration(
            tmp_path,
            run_id="legacy-run-65",
            subject_digest=SHA,
            budget_policy=policy,
            migration=different,
            trust_policy=TRUST_POLICY,
            evidence_verifier=verify_external_proof,
        )


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
    loaded = LifecycleControlPlane.load(tmp_path, evidence_verifier=verify_external_proof)
    assert loaded.state is LifecycleState.CONTRACT_APPROVED
    ledger = tmp_path / "lifecycle-events.jsonl"
    ledger.write_text(ledger.read_text().replace("CONTRACT_APPROVED", "COMPLETED", 1))
    with pytest.raises(ValueError, match="digest chain"):
        LifecycleControlPlane.load(tmp_path)


def test_budget_resume_uses_only_the_recorded_safe_state(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.IMPLEMENTATION_IN_PROGRESS)
    _, exhausted = budgets(tokens=101)
    required = evidence_for(
        LifecycleState.IMPLEMENTATION_IN_PROGRESS,
        LifecycleState.BUDGET_EXCEEDED,
        reason="delivery_budget_exhausted",
    )
    stopped = WorkStatus(
        workers_stopped=True,
        partial_output_disposition="frozen-unverified-non-admissible",
    )
    bind_work_evidence(required, stopped)
    cp.transition(
        LifecycleState.BUDGET_EXCEEDED,
        context(
            usage=exhausted,
            work=stopped,
            evidence=required,
        ),
        reason="delivery_budget_exhausted",
    )
    policy, _ = budgets()
    extended = replace(policy, version="budget-v2", limits={**policy.limits, "tokens": 200})
    cp.admit_budget_policy(
        extended,
        authorization=extension_authorization(cp, extended, amounts={"tokens": 100}),
        authority=authority(observed_at="2026-08-02T12:00:00Z"),
        observed_at="2026-08-02T12:00:00Z",
    )
    resume_evidence = {
        "subject_digest": SHA,
        "incident_closure_digest": SHA,
        "restored_capability_digest": OTHER_SHA,
        "unchanged_inputs_digest": SHA,
    }
    stopped_event = next(
        event
        for event in reversed(cp.events)
        if event.target is LifecycleState.BUDGET_EXCEEDED and event.resume_state is not None
    )
    bind_resume_observation(
        resume_evidence, stopped_event, LifecycleState.IMPLEMENTATION_IN_PROGRESS
    )
    cp.resume(
        context(
            usage=BudgetUsage(counters={"tokens": 101}),
            budget_policy=cp.budget_policy,
            evidence=resume_evidence,
        )
    )
    assert cp.state is LifecycleState.IMPLEMENTATION_IN_PROGRESS


def test_mutation_idempotency_binding_survives_replay(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.STAGING_DEPLOYED)
    attempt = MutationAttempt(
        attempt_id="attempt-1",
        idempotency_key="cleanup:run-65:1",
        subject_digest=SHA,
        action="rollback",
        step_plan_digest=OTHER_SHA,
        status="PLANNED",
    )
    prejournal(cp, attempt)
    record_result(cp, attempt, status="UNKNOWN", result_digest=None)
    loaded = LifecycleControlPlane.load(tmp_path, evidence_verifier=verify_external_proof)
    with pytest.raises(TransitionDeniedError, match="idempotency key"):
        record_result(
            loaded,
            replace(attempt, attempt_id="attempt-2"),
            status="SUCCEEDED",
            result_digest=SHA,
        )


def test_concurrent_append_rejects_stale_writer_without_corrupting_chain(tmp_path: Path) -> None:
    first = control_plane(tmp_path)
    stale = LifecycleControlPlane.load(tmp_path, evidence_verifier=verify_external_proof)
    first.record_observation(
        source="live-observer",
        subject_digest=SHA,
        payload_digest=OTHER_SHA,
        signature=external_proof(
            "live-observer",
            SHA,
            {
                "source": "live-observer",
                "subject_digest": SHA,
                "payload_digest": OTHER_SHA,
                "observed_at": "2026-08-02T00:03:00Z",
            },
        ),
        observed_at="2026-08-02T00:03:00Z",
    )
    with pytest.raises(TransitionDeniedError, match="compare-and-swap"):
        stale.record_observation(
            source="live-observer",
            subject_digest=SHA,
            payload_digest=OTHER_SHA,
            signature=external_proof(
                "live-observer",
                SHA,
                {
                    "source": "live-observer",
                    "subject_digest": SHA,
                    "payload_digest": OTHER_SHA,
                    "observed_at": "2026-08-02T00:03:01Z",
                },
            ),
            observed_at="2026-08-02T00:03:01Z",
        )
    loaded = LifecycleControlPlane.load(tmp_path)
    assert [event.reason for event in loaded.events] == ["create", "live-observer"]


def test_budget_stop_derives_the_interrupted_safe_gate(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.IMPLEMENTATION_IN_PROGRESS)
    _, exhausted = budgets(tokens=100)
    required = evidence_for(
        LifecycleState.IMPLEMENTATION_IN_PROGRESS,
        LifecycleState.BUDGET_EXCEEDED,
        reason="delivery_budget_exhausted",
    )
    stopped = WorkStatus(
        workers_stopped=True,
        partial_output_disposition="frozen-unverified-non-admissible",
    )
    bind_work_evidence(required, stopped)
    event = cp.transition(
        LifecycleState.BUDGET_EXCEEDED,
        context(usage=exhausted, work=stopped, evidence=required),
        reason="delivery_budget_exhausted",
    )
    assert event.resume_state is LifecycleState.IMPLEMENTATION_IN_PROGRESS


def test_budget_and_repair_usage_are_monotonic_and_replayed(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.VERIFICATION_FAILED)
    finding = FindingSignal(
        finding_id="finding-monotonic",
        source="finding-source",
        exact_subject_digest=SHA,
        severity="HIGH",
        credible=True,
        blocking=True,
        reviewer_eligible=True,
        category="ENGINEERING",
        disposition="ACCEPTED_FOR_REPAIR",
        affected_scope_digest=OTHER_SHA,
    )
    required = evidence_for(
        LifecycleState.VERIFICATION_FAILED,
        LifecycleState.REPAIR_IN_PROGRESS,
        reason="accepted_finding",
    )
    required["finding_digest"] = object_digest(asdict(finding))
    cp.transition(
        LifecycleState.REPAIR_IN_PROGRESS,
        context(
            usage=BudgetUsage(counters={"tokens": 10}),
            evidence=required,
            finding=finding,
        ),
        reason="accepted_finding",
    )
    assert cp.budget_usage.repair_attempts_by_finding["finding-monotonic"] == 1
    loaded = LifecycleControlPlane.load(tmp_path, evidence_verifier=verify_external_proof)
    assert loaded.budget_usage.counters["tokens"] == 10
    assert loaded.budget_usage.repair_attempts_by_finding["finding-monotonic"] == 1
    next_required = evidence_for(
        LifecycleState.REPAIR_IN_PROGRESS,
        LifecycleState.VERIFICATION_FAILED,
        reason="repair_candidate_ready",
    )
    with pytest.raises(TransitionDeniedError, match="budget usage cannot decrease"):
        loaded.transition(
            LifecycleState.VERIFICATION_FAILED,
            context(evidence=next_required),
            reason="repair_candidate_ready",
        )


def test_same_attempt_id_cannot_rebind_a_complete_mutation_plan(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.PR_MERGED)
    attempt = MutationAttempt(
        attempt_id="attempt-complete-plan",
        idempotency_key="deploy:run-65:1",
        subject_digest=SHA,
        action="deploy_staging",
        step_plan_digest=OTHER_SHA,
        status="PLANNED",
        steps=("create", "wait", "observe"),
    )
    prejournal(cp, attempt)
    record_result(cp, attempt, status="UNKNOWN", result_digest=None)
    altered = replace(
        attempt,
        action="deploy_production",
        step_plan_digest=SHA,
        steps=("promote",),
    )
    with pytest.raises(TransitionDeniedError, match="complete mutation plan"):
        record_result(cp, altered, status="UNKNOWN", result_digest=None)


def test_mutation_admission_requires_persisted_success_after_replay(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.PR_MERGED)
    required = evidence_for(
        LifecycleState.PR_MERGED,
        LifecycleState.STAGING_DEPLOYED,
        reason="staging_admitted",
    )
    record_integrated_merge(cp, required["merge_digest"])
    attempt = MutationAttempt(
        attempt_id="attempt-stage-replay",
        idempotency_key="stage:run-65:replay",
        subject_digest=SHA,
        action="deploy_staging",
        step_plan_digest=mutation_subject_digest("deploy_staging", required),
        status="PLANNED",
    )
    prejournal(cp, attempt)
    record_result(cp, attempt, status="SUCCEEDED", result_digest=SHA)
    loaded = LifecycleControlPlane.load(tmp_path, evidence_verifier=verify_external_proof)
    required["staging_result_digest"] = SHA
    required["staging_attempt_digest"] = object_digest(asdict(attempt))
    loaded.transition(
        LifecycleState.STAGING_DEPLOYED,
        context(evidence=required, mutation=attempt),
        reason="staging_admitted",
    )
    assert loaded.state is LifecycleState.STAGING_DEPLOYED


def test_safety_resume_is_bound_to_original_blocked_attempt(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.ROLLBACK_IN_PROGRESS)
    attempt = MutationAttempt(
        attempt_id="rollback-original",
        idempotency_key="rollback:run-65:original",
        subject_digest=SHA,
        action="rollback",
        step_plan_digest=rollback_plan(),
        status="PLANNED",
    )
    blocked_evidence = evidence_for(
        LifecycleState.ROLLBACK_IN_PROGRESS,
        LifecycleState.BLOCKED,
        reason="rollback_indeterminate",
    )
    blocked_evidence["original_attempt_digest"] = object_digest(asdict(attempt))
    prejournal(cp, attempt)
    cp.transition(
        LifecycleState.BLOCKED,
        context(
            evidence=blocked_evidence,
            mutation=attempt,
        ),
        reason="rollback_indeterminate",
    )
    resume_evidence = evidence_for(
        LifecycleState.BLOCKED,
        LifecycleState.ROLLBACK_IN_PROGRESS,
        reason="resume_safety_rollback",
    )
    resume_evidence["original_attempt_digest"] = object_digest(asdict(attempt))
    impostor = replace(attempt, attempt_id="rollback-impostor")
    with pytest.raises(TransitionDeniedError, match="original blocked action"):
        cp.transition(
            LifecycleState.ROLLBACK_IN_PROGRESS,
            context(
                evidence=resume_evidence,
                mutation=impostor,
            ),
            reason="resume_safety_rollback",
        )
    cp.transition(
        LifecycleState.ROLLBACK_IN_PROGRESS,
        context(
            evidence=resume_evidence,
            mutation=attempt,
        ),
        reason="resume_safety_rollback",
    )
    assert cp.budget_usage.safety_units_used == 0


def test_blocked_direct_readmission_fails_closed_until_safe_recovery(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.BLOCKED)
    evidence = evidence_for(
        LifecycleState.BLOCKED,
        LifecycleState.REPOSITORY_ANALYSED,
        reason="repository_readmitted",
    )
    with pytest.raises(TransitionDeniedError, match="safe-stop|resources|quiescence"):
        cp.transition(
            LifecycleState.REPOSITORY_ANALYSED,
            context(
                evidence=evidence,
                rollout=RolloutStatus(canary="UNKNOWN"),
                work=WorkStatus(
                    workers_stopped=False,
                    mutation_capability_active=True,
                ),
            ),
            reason="repository_readmitted",
        )


def test_indeterminate_rollback_retains_truthful_unresolved_exposure(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.ROLLBACK_IN_PROGRESS)
    attempt = MutationAttempt(
        attempt_id="rollback-unresolved-exposure",
        idempotency_key="rollback:run-65:unresolved-exposure",
        subject_digest=SHA,
        action="rollback",
        step_plan_digest=rollback_plan(),
        status="PLANNED",
    )
    prejournal(cp, attempt)
    required = evidence_for(
        LifecycleState.ROLLBACK_IN_PROGRESS,
        LifecycleState.BLOCKED,
        reason="rollback_indeterminate",
    )
    required["original_attempt_digest"] = object_digest(asdict(attempt))

    event = cp.transition(
        LifecycleState.BLOCKED,
        context(
            evidence=required,
            mutation=attempt,
            rollout=RolloutStatus(
                staging="ACTIVE",
                canary="UNKNOWN",
                changed_production="UNKNOWN",
            ),
        ),
        reason="rollback_indeterminate",
    )
    assert event.target is LifecycleState.BLOCKED
    assert event.resume_state is LifecycleState.ROLLBACK_IN_PROGRESS


def test_safety_mutations_are_explicitly_prejournaled_before_adapter_execution(
    tmp_path: Path,
) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.LIVE_VERIFICATION_FAILED)
    attempt = MutationAttempt(
        attempt_id="rollback-prejournal",
        idempotency_key="rollback:run-65:prejournal",
        subject_digest=SHA,
        action="rollback",
        step_plan_digest=rollback_plan(),
        status="PLANNED",
    )
    start_evidence = evidence_for(
        LifecycleState.LIVE_VERIFICATION_FAILED,
        LifecycleState.ROLLBACK_IN_PROGRESS,
        reason="rollback_started",
    )
    start_evidence["rollback_attempt_digest"] = object_digest(asdict(attempt))

    with pytest.raises(TransitionDeniedError, match="durably pre-journaled"):
        cp.transition(
            LifecycleState.ROLLBACK_IN_PROGRESS,
            context(evidence=start_evidence, mutation=attempt),
            reason="rollback_started",
        )
    with pytest.raises(TransitionDeniedError, match="durably pre-journaled"):
        record_result(cp, attempt, status="SUCCEEDED", result_digest=SHA)

    prejournal(cp, attempt)
    persisted = cp.mutation_path.read_text()
    assert attempt.attempt_id in persisted
    assert "record_digest" in persisted

    cp.transition(
        LifecycleState.ROLLBACK_IN_PROGRESS,
        context(evidence=start_evidence, mutation=attempt),
        reason="rollback_started",
    )
    record_result(cp, attempt, status="UNKNOWN", result_digest=None)
    verified_evidence = evidence_for(
        LifecycleState.ROLLBACK_IN_PROGRESS,
        LifecycleState.ROLLED_BACK,
        reason="rollback_verified",
    )
    with pytest.raises(TransitionDeniedError, match="successful exact-attempt"):
        cp.transition(
            LifecycleState.ROLLED_BACK,
            context(
                evidence=verified_evidence,
                mutation=attempt,
                usage=cp.budget_usage,
            ),
            reason="rollback_verified",
        )


def test_resume_target_is_control_plane_derived_not_caller_selected(tmp_path: Path) -> None:
    assert "resume_state" not in {field.name for field in fields(TransitionContext)}

    cp = control_plane(tmp_path, state=LifecycleState.IMPLEMENTATION_IN_PROGRESS)
    policy, _ = budgets()
    exhausted = BudgetUsage(counters={"tokens": policy.limits["tokens"]})
    stop_evidence = evidence_for(
        LifecycleState.IMPLEMENTATION_IN_PROGRESS,
        LifecycleState.BUDGET_EXCEEDED,
        reason="delivery_budget_exhausted",
    )
    stopped_work = WorkStatus(
        workers_stopped=True,
        partial_output_disposition="frozen-unverified-non-admissible",
    )
    bind_work_evidence(stop_evidence, stopped_work)
    event = cp.transition(
        LifecycleState.BUDGET_EXCEEDED,
        context(
            usage=exhausted,
            evidence=stop_evidence,
            work=stopped_work,
        ),
        reason="delivery_budget_exhausted",
    )
    assert event.resume_state is LifecycleState.IMPLEMENTATION_IN_PROGRESS


def test_every_transition_requires_authenticated_exact_subject_actor_authority(
    tmp_path: Path,
) -> None:
    required = evidence_for(
        LifecycleState.CONTRACT_RECEIVED,
        LifecycleState.CONTRACT_APPROVED,
        reason="contract_admitted",
    )
    valid = context(evidence=required)
    assert isinstance(valid.actor, lifecycle.TransitionActor)

    invalid_actors = (
        replace(valid.actor, actor_id=""),
        replace(valid.actor, role=""),
        replace(valid.actor, authenticated=False),
        replace(valid.actor, subject_digest=OTHER_SHA),
        replace(valid.actor, capabilities=frozenset()),
        replace(valid.actor, authority_digest=OTHER_SHA),
    )
    for index, actor in enumerate(invalid_actors):
        cp = control_plane(tmp_path / str(index))
        with pytest.raises(TransitionDeniedError, match="actor authority"):
            cp.transition(
                LifecycleState.CONTRACT_APPROVED,
                replace(valid, actor=actor),
                reason="contract_admitted",
            )
        assert cp.state is LifecycleState.CONTRACT_RECEIVED


def test_reserved_safety_budget_is_control_plane_bounded_and_not_caller_capacity(
    tmp_path: Path,
) -> None:
    cp = control_plane(tmp_path / "ordinary", state=LifecycleState.CONTRACT_RECEIVED)
    required = evidence_for(
        LifecycleState.CONTRACT_RECEIVED,
        LifecycleState.CONTRACT_APPROVED,
        reason="contract_admitted",
    )
    with pytest.raises(TransitionDeniedError, match="reserved safety usage"):
        cp.transition(
            LifecycleState.CONTRACT_APPROVED,
            context(evidence=required, usage=BudgetUsage(safety_units_used=1)),
            reason="contract_admitted",
        )

    policy, _ = budgets()
    blocked = control_plane(tmp_path / "resume", state=LifecycleState.LIVE_VERIFICATION_FAILED)
    blocked._budget_policy = replace(policy, reserved_safety_units=1)
    attempt = MutationAttempt(
        attempt_id="rollback-safety-cap",
        idempotency_key="rollback:run-65:safety-cap",
        subject_digest=SHA,
        action="rollback",
        step_plan_digest=rollback_plan(),
        status="PLANNED",
    )
    start_evidence = evidence_for(
        LifecycleState.LIVE_VERIFICATION_FAILED,
        LifecycleState.ROLLBACK_IN_PROGRESS,
        reason="rollback_started",
    )
    start_evidence["rollback_attempt_digest"] = object_digest(asdict(attempt))
    prejournal(blocked, attempt)
    blocked.transition(
        LifecycleState.ROLLBACK_IN_PROGRESS,
        context(evidence=start_evidence, mutation=attempt),
        reason="rollback_started",
    )
    assert blocked.budget_usage.safety_units_used == 1
    blocked_evidence = evidence_for(
        LifecycleState.ROLLBACK_IN_PROGRESS,
        LifecycleState.BLOCKED,
        reason="rollback_indeterminate",
    )
    blocked_evidence["original_attempt_digest"] = object_digest(asdict(attempt))
    blocked.transition(
        LifecycleState.BLOCKED,
        context(
            evidence=blocked_evidence,
            mutation=attempt,
            usage=blocked.budget_usage,
        ),
        reason="rollback_indeterminate",
    )
    resume_evidence = evidence_for(
        LifecycleState.BLOCKED,
        LifecycleState.ROLLBACK_IN_PROGRESS,
        reason="resume_safety_rollback",
    )
    resume_evidence["original_attempt_digest"] = object_digest(asdict(attempt))
    blocked.transition(
        LifecycleState.ROLLBACK_IN_PROGRESS,
        context(
            evidence=resume_evidence,
            mutation=attempt,
            usage=blocked.budget_usage,
        ),
        reason="resume_safety_rollback",
    )
    assert blocked.budget_usage.safety_units_used == 1
    blocked.transition(
        LifecycleState.BLOCKED,
        context(
            evidence=blocked_evidence,
            mutation=attempt,
            usage=blocked.budget_usage,
        ),
        reason="rollback_indeterminate",
    )
    resumed = blocked.transition(
        LifecycleState.ROLLBACK_IN_PROGRESS,
        context(
            evidence=resume_evidence,
            mutation=attempt,
            usage=blocked.budget_usage,
        ),
        reason="resume_safety_rollback",
    )
    assert resumed.target is LifecycleState.ROLLBACK_IN_PROGRESS
    assert blocked.budget_usage.safety_units_used == 1


def test_live_gate_failure_requires_authenticated_exact_deployment_attestation(
    tmp_path: Path,
) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.PRODUCTION_DEPLOYED)
    deployed = {
        "subject_digest": SHA,
        "release_sha": "a" * 40,
        "artifact_digest": object_digest("production-artifact"),
        "configuration_digest": object_digest("production-config"),
        "production_attempt_digest": object_digest("production-attempt"),
        "production_result_digest": object_digest("production-result"),
    }
    cp._append(
        kind="PRODUCTION_BINDING_ADMITTED",
        outcome="APPLIED",
        source=LifecycleState.PRODUCTION_APPROVAL_REQUIRED,
        target=LifecycleState.PRODUCTION_DEPLOYED,
        reason="production_admitted",
        actor="fixture",
        evidence_refs=deployed,
        observed_at="2026-08-02T00:01:00Z",
    )
    failure = evidence_for(
        LifecycleState.PRODUCTION_DEPLOYED,
        LifecycleState.LIVE_VERIFICATION_FAILED,
        reason="live_gate_failed",
    )
    failure.update(deployed)
    failure.update(
        live_failure_digest=object_digest("slo-breach"),
        telemetry_digest=object_digest("trusted-live-telemetry"),
    )

    with pytest.raises(TransitionDeniedError, match="trusted live failure"):
        cp.transition(
            LifecycleState.LIVE_VERIFICATION_FAILED,
            context(evidence=failure),
            reason="live_gate_failed",
        )

    payload = {
        "observer_id": "live-observer",
        "authority_digest": SHA,
        "subject_digest": SHA,
        "release_sha": failure["release_sha"],
        "artifact_digest": failure["artifact_digest"],
        "configuration_digest": failure["configuration_digest"],
        "production_attempt_digest": failure["production_attempt_digest"],
        "production_result_digest": failure["production_result_digest"],
        "live_failure_digest": failure["live_failure_digest"],
        "telemetry_digest": failure["telemetry_digest"],
        "observed_at": "2026-08-02T00:01:00Z",
    }
    failure.update(
        live_failure_observer_id="live-observer",
        live_failure_observer_authority_digest=SHA,
        live_failure_authentication_evidence_digest=external_proof("live-observer", SHA, payload),
    )
    event = cp.transition(
        LifecycleState.LIVE_VERIFICATION_FAILED,
        context(evidence=failure),
        reason="live_gate_failed",
    )
    assert event.target is LifecycleState.LIVE_VERIFICATION_FAILED


def test_canary_failure_with_mutation_or_indeterminate_exposure_enters_rollback(
    tmp_path: Path,
) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.CANARY_DEPLOYED)
    required = evidence_for(
        LifecycleState.CANARY_DEPLOYED,
        LifecycleState.ROLLBACK_IN_PROGRESS,
        reason="canary_failed",
    )
    required.update(record_active_canary_binding(cp))
    rollback = MutationAttempt(
        attempt_id="rollback-canary-failure",
        idempotency_key="rollback:run-65:canary-failure",
        subject_digest=SHA,
        action="rollback",
        step_plan_digest=rollback_plan(required),
        status="PLANNED",
    )
    prejournal(cp, rollback)
    required["rollback_attempt_digest"] = object_digest(asdict(rollback))
    event = cp.transition(
        LifecycleState.ROLLBACK_IN_PROGRESS,
        context(
            evidence=required,
            mutation=rollback,
            rollout=RolloutStatus(staging="ACTIVE", canary="UNKNOWN"),
        ),
        reason="canary_failed",
    )
    assert event.target is LifecycleState.ROLLBACK_IN_PROGRESS


def test_canary_breach_is_recorded_before_a_rollback_attempt(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.CANARY_DEPLOYED)
    required = evidence_for(
        LifecycleState.CANARY_DEPLOYED,
        LifecycleState.CANARY_FAILED,
        reason="canary_breach_recorded",
    )
    required.update(record_active_canary_binding(cp))
    required["canary_failure_digest"] = object_digest("canary-slo-breach")

    with pytest.raises(TransitionDeniedError, match="trusted exact-canary breach"):
        cp.transition(
            LifecycleState.CANARY_FAILED,
            context(
                evidence=required,
                rollout=RolloutStatus(staging="ACTIVE", canary="ACTIVE"),
            ),
            reason="canary_breach_recorded",
        )
    required.update(
        canary_breach_observer_id="live-observer",
        canary_breach_observer_authority_digest=SHA,
    )
    required["canary_breach_authentication_evidence_digest"] = external_proof(
        "live-observer",
        SHA,
        {
            "observer_id": "live-observer",
            "authority_digest": SHA,
            "subject_digest": SHA,
            "canary_id_digest": required["canary_id_digest"],
            "canary_attempt_digest": required["canary_attempt_digest"],
            "canary_status_digest": required["canary_status_digest"],
            "canary_failure_digest": required["canary_failure_digest"],
            "observed_at": "2026-08-02T00:01:00Z",
        },
    )
    event = cp.transition(
        LifecycleState.CANARY_FAILED,
        context(evidence=required, rollout=RolloutStatus(staging="ACTIVE", canary="ACTIVE")),
        reason="canary_breach_recorded",
    )

    assert event.target is LifecycleState.CANARY_FAILED
    assert cp.state is LifecycleState.CANARY_FAILED
    assert "rollback_attempt_digest" not in event.evidence_refs


def test_approval_window_canary_breach_is_recorded_before_rollback(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.PRODUCTION_APPROVAL_REQUIRED)
    required = evidence_for(
        LifecycleState.PRODUCTION_APPROVAL_REQUIRED,
        LifecycleState.CANARY_FAILED,
        reason="canary_breach_recorded",
    )
    required.update(record_active_canary_binding(cp))
    required["canary_failure_digest"] = object_digest("approval-window-slo-breach")
    required.update(
        canary_breach_observer_id="live-observer",
        canary_breach_observer_authority_digest=SHA,
    )
    required["canary_breach_authentication_evidence_digest"] = external_proof(
        "live-observer",
        SHA,
        {
            "observer_id": "live-observer",
            "authority_digest": SHA,
            "subject_digest": SHA,
            "canary_id_digest": required["canary_id_digest"],
            "canary_attempt_digest": required["canary_attempt_digest"],
            "canary_status_digest": required["canary_status_digest"],
            "canary_failure_digest": required["canary_failure_digest"],
            "observed_at": "2026-08-02T00:01:00Z",
        },
    )
    assert (
        cp.transition(
            LifecycleState.CANARY_FAILED,
            context(evidence=required, rollout=RolloutStatus(staging="ACTIVE", canary="ACTIVE")),
            reason="canary_breach_recorded",
        ).target
        is LifecycleState.CANARY_FAILED
    )


def test_blocking_finding_requires_external_source_authentication(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.PR_READY)
    required = evidence_for(
        LifecycleState.PR_READY,
        LifecycleState.REVIEW_FAILED,
        reason="blocking_finding",
    )
    finding = FindingSignal(
        finding_id="unauthenticated-scanner-1",
        source="finding-source",
        exact_subject_digest=SHA,
        severity="HIGH",
        credible=True,
        blocking=True,
        reviewer_eligible=False,
        category="ENGINEERING",
        disposition="ACCEPTED",
        affected_scope_digest=OTHER_SHA,
    )
    required["finding_digest"] = object_digest(asdict(finding))
    required["finding_authentication_evidence_digest"] = OTHER_SHA

    with pytest.raises(TransitionDeniedError, match="finding source is not authenticated"):
        cp.transition(
            LifecycleState.REVIEW_FAILED,
            context(evidence=required, finding=finding),
            reason="blocking_finding",
        )

    assert cp.state is LifecycleState.PR_READY


def test_canary_state_cannot_claim_zero_exposure_without_evidence(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.CANARY_DEPLOYED)
    required = evidence_for(
        LifecycleState.CANARY_DEPLOYED,
        LifecycleState.PRODUCTION_APPROVAL_REQUIRED,
        reason="canary_window_passed",
    )
    with pytest.raises(TransitionDeniedError, match="canary exposure"):
        cp.transition(
            LifecycleState.PRODUCTION_APPROVAL_REQUIRED,
            context(evidence=required, rollout=RolloutStatus()),
            reason="canary_window_passed",
        )


def test_budget_extensions_require_named_authenticated_exact_subject_authority(
    tmp_path: Path,
) -> None:
    cp = control_plane(tmp_path)
    extended = replace(
        cp.budget_policy,
        version="budget-v2",
        limits={**cp.budget_policy.limits, "tokens": 125},
        approved_by="owner-alice",
    )
    with pytest.raises(TransitionDeniedError, match="authenticated budget owner"):
        cp.admit_budget_policy(extended)

    authorization = extension_authorization(cp, extended, amounts={"tokens": 25})
    with pytest.raises(TransitionDeniedError, match="run or subject"):
        cp.admit_budget_policy(
            extended,
            authorization=replace(authorization, subject_digest=OTHER_SHA),
            authority=authority(observed_at="2026-08-02T12:00:00Z"),
            observed_at="2026-08-02T12:00:00Z",
        )
    with pytest.raises(TransitionDeniedError, match="amount"):
        cp.admit_budget_policy(
            extended,
            authorization=extension_authorization(cp, extended, amounts={"tokens": 26}),
            authority=authority(observed_at="2026-08-02T12:00:00Z"),
            observed_at="2026-08-02T12:00:00Z",
        )
    with pytest.raises(TransitionDeniedError, match="reason"):
        cp.admit_budget_policy(
            extended,
            authorization=replace(authorization, reason=""),
            authority=authority(observed_at="2026-08-02T12:00:00Z"),
            observed_at="2026-08-02T12:00:00Z",
        )
    with pytest.raises(TransitionDeniedError, match="authority|validity"):
        cp.admit_budget_policy(
            extended,
            authorization=authorization,
            authority=authority(
                observed_at="2026-08-04T12:00:00Z",
                valid_until="2026-08-05T00:00:00Z",
            ),
            observed_at="2026-08-04T12:00:00Z",
        )
    forged_credential = replace(authorization, credential_digest=OTHER_SHA)
    forged_credential = replace(
        forged_credential,
        evidence_digest=external_proof(
            forged_credential.owner_id,
            forged_credential.credential_digest,
            lifecycle._budget_extension_authorization_payload(forged_credential),
        ),
    )
    with pytest.raises(TransitionDeniedError, match="trusted budget-owner"):
        cp.admit_budget_policy(
            extended,
            authorization=forged_credential,
            authority=authority(observed_at="2026-08-02T12:00:00Z"),
            observed_at="2026-08-02T12:00:00Z",
        )
    cp.admit_budget_policy(
        extended,
        authorization=authorization,
        authority=authority(observed_at="2026-08-02T12:00:00Z"),
        observed_at="2026-08-02T12:00:00Z",
    )
    assert cp.budget_policy == extended
    assert cp.events[-1].kind == "BUDGET_POLICY_ADMITTED"
    assert cp.events[-1].actor == "owner-alice"
    loaded = LifecycleControlPlane.load(tmp_path)
    assert loaded.budget_policy == extended
    assert loaded.events[-1].kind == "BUDGET_POLICY_ADMITTED"
    assert (
        loaded.events[-1].evidence_refs["authorization_evidence_digest"]
        == authorization.evidence_digest
    )


def test_budget_owner_trust_root_accepts_a_fresh_current_authority_snapshot(
    tmp_path: Path,
) -> None:
    cp = control_plane(tmp_path)
    extended = replace(
        cp.budget_policy,
        version="budget-v2-refreshed-authority",
        limits={**cp.budget_policy.limits, "tokens": 125},
        approved_by="owner-alice",
    )
    refreshed = authority(
        observed_at="2026-08-02T13:00:00Z",
        valid_until="2026-08-03T00:00:00Z",
    )

    cp.admit_budget_policy(
        extended,
        authorization=extension_authorization(
            cp,
            extended,
            amounts={"tokens": 25},
            authority_snapshot=refreshed,
        ),
        authority=refreshed,
        observed_at="2026-08-02T13:00:00Z",
    )

    assert cp.budget_policy == extended


def test_budget_extension_ignores_untrusted_denied_event_time_but_requires_fresh_challenge(
    tmp_path: Path,
) -> None:
    cp = control_plane(tmp_path)
    extended = replace(
        cp.budget_policy,
        version="budget-v2-fresh-challenge",
        limits={**cp.budget_policy.limits, "tokens": 125},
        approved_by="owner-alice",
    )
    with pytest.raises(TransitionDeniedError):
        cp.transition(
            LifecycleState.CONTRACT_INVALID,
            replace(context(), observed_at="2099-01-01T00:00:00Z"),
            reason="contract_invalid",
        )

    authorization = extension_authorization(
        cp,
        extended,
        amounts={"tokens": 25},
        admission_challenge=cp.issue_budget_extension_challenge(),
    )
    cp.admit_budget_policy(
        extended,
        authorization=authorization,
        authority=authority(observed_at="2026-08-02T12:00:00Z"),
        observed_at="2026-08-02T12:00:00Z",
    )

    assert cp.budget_policy == extended


def test_budget_extension_rejects_a_superseded_admission_challenge(tmp_path: Path) -> None:
    cp = control_plane(tmp_path)
    extended = replace(
        cp.budget_policy,
        version="budget-v2-stale-challenge",
        limits={**cp.budget_policy.limits, "tokens": 125},
        approved_by="owner-alice",
    )
    authorization = extension_authorization(
        cp,
        extended,
        amounts={"tokens": 25},
        admission_challenge=cp.issue_budget_extension_challenge(),
    )
    cp.issue_budget_extension_challenge()

    with pytest.raises(TransitionDeniedError, match="fresh admission challenge"):
        cp.admit_budget_policy(
            extended,
            authorization=authorization,
            authority=authority(observed_at="2026-08-02T12:00:00Z"),
            observed_at="2026-08-02T12:00:00Z",
        )


def test_budget_extension_rejects_an_expired_admission_challenge(tmp_path: Path) -> None:
    cp = control_plane(tmp_path)
    extended = replace(
        cp.budget_policy,
        version="budget-v2-expired-challenge",
        limits={**cp.budget_policy.limits, "tokens": 125},
        approved_by="owner-alice",
    )
    challenge = cp.issue_budget_extension_challenge()
    cp._budget_extension_challenge_deadline = time.monotonic() - 1.0
    authorization = extension_authorization(
        cp, extended, amounts={"tokens": 25}, admission_challenge=challenge
    )

    with pytest.raises(TransitionDeniedError, match="fresh admission challenge"):
        cp.admit_budget_policy(
            extended,
            authorization=authorization,
            authority=authority(observed_at="2026-08-02T12:00:00Z"),
            observed_at="2026-08-02T12:00:00Z",
        )


def test_policy_snapshot_rejects_mutation_subject_schema_drift() -> None:
    snapshot = lifecycle._policy_payload(PHASE_ZERO_POLICY)
    mutated = next(
        rule for rule in snapshot["rules"] if rule["mutation_action"] == "deploy_staging"
    )
    mutated["mutation_subject_fields"] = ["subject_digest"]

    with pytest.raises(ValueError, match="lifecycle policy snapshot is invalid"):
        lifecycle._policy_from_payload(snapshot)


def test_phase_zero_v1_snapshot_loads_with_its_versioned_mutation_schemas() -> None:
    snapshot = lifecycle._policy_payload(PHASE_ZERO_POLICY)
    snapshot["version"] = "phase-zero-v1"
    for rule in snapshot["rules"]:
        rule.pop("mutation_subject_fields")

    assert lifecycle._policy_from_payload(snapshot).version == "phase-zero-v1"
    assert lifecycle._policy_from_payload(snapshot).mutation_subject_fields["deploy_staging"] == (
        "subject_digest",
        "merge_digest",
        "artifact_digest",
    )


def test_phase_zero_v1_replay_allowlists_all_released_digests_and_shared_variants() -> None:
    snapshot = lifecycle._policy_payload(PHASE_ZERO_POLICY)
    snapshot["version"] = "phase-zero-v1"
    for rule in snapshot["rules"]:
        rule.pop("mutation_subject_fields")

    assert len(lifecycle._PHASE_ZERO_V1_RELEASED_POLICY_DIGESTS) == 17
    for digest in lifecycle._PHASE_ZERO_V1_RELEASED_POLICY_DIGESTS:
        assert (
            lifecycle._policy_from_payload(snapshot, policy_digest=digest).version
            == "phase-zero-v1"
        )
    variants = lifecycle._PHASE_ZERO_V1_MUTATION_SCHEMA_VARIANTS["open_draft_pr"]
    assert (
        "subject_digest",
        "governance_attempt_digest",
        "issue_digest",
        "branch_digest",
        "red_commit_digest",
        "draft_pr_digest",
    ) in variants
    assert (
        "subject_digest",
        "issue_digest",
        "branch_digest",
        "red_commit_digest",
        "draft_pr_digest",
    ) in variants


def test_phase_zero_v1_schemas_do_not_inherit_active_schema_edits() -> None:
    historical_open = lifecycle._PHASE_ZERO_V1_B9_MUTATION_SUBJECT_FIELDS["open_draft_pr"]
    historical_cleanup = lifecycle._PHASE_ZERO_V1_B9_MUTATION_SUBJECT_FIELDS["cleanup_staging"]
    active_open = lifecycle._MUTATION_SUBJECT_FIELDS["open_draft_pr"]
    active_cleanup = lifecycle._MUTATION_SUBJECT_FIELDS["cleanup_staging"]
    try:
        lifecycle._MUTATION_SUBJECT_FIELDS["open_draft_pr"] = (
            *active_open,
            "future_active_field",
        )
        lifecycle._MUTATION_SUBJECT_FIELDS["cleanup_staging"] = (
            *active_cleanup,
            "future_active_field",
        )

        assert (
            lifecycle._PHASE_ZERO_V1_B9_MUTATION_SUBJECT_FIELDS["open_draft_pr"] == historical_open
        )
        assert (
            lifecycle._PHASE_ZERO_V1_B9_MUTATION_SUBJECT_FIELDS["cleanup_staging"]
            == historical_cleanup
        )
    finally:
        lifecycle._MUTATION_SUBJECT_FIELDS["open_draft_pr"] = active_open
        lifecycle._MUTATION_SUBJECT_FIELDS["cleanup_staging"] = active_cleanup


def test_ambiguous_v1_policy_can_replay_but_not_release_a_new_mutation(
    tmp_path: Path,
) -> None:
    snapshot = lifecycle._policy_payload(PHASE_ZERO_POLICY)
    snapshot["version"] = "phase-zero-v1"
    for rule in snapshot["rules"]:
        rule.pop("mutation_subject_fields")
    historical_policy = lifecycle._policy_from_payload(
        snapshot,
        policy_digest=lifecycle._V1_B9_POLICY_DIGEST,
    )
    cp = control_plane(tmp_path, state=LifecycleState.PRODUCTION_APPROVAL_REQUIRED)
    cp._policy = historical_policy
    attempt = MutationAttempt(
        attempt_id="historical-production-attempt",
        idempotency_key="production:run-65:historical",
        subject_digest=SHA,
        action="deploy_production",
        step_plan_digest=OTHER_SHA,
        status="PLANNED",
    )

    with pytest.raises(TransitionDeniedError, match="unavailable or ambiguous"):
        prejournal(cp, attempt)

    cp._register_mutation(attempt)
    assert prejournal(cp, attempt) == attempt


def test_v1_policy_without_an_exact_schema_cannot_release_a_new_mutation(
    tmp_path: Path,
) -> None:
    snapshot = lifecycle._policy_payload(PHASE_ZERO_POLICY)
    snapshot["version"] = "phase-zero-v1"
    for rule in snapshot["rules"]:
        rule.pop("mutation_subject_fields")
    unmapped_digest = next(
        digest
        for digest in lifecycle._PHASE_ZERO_V1_RELEASED_POLICY_DIGESTS
        if digest not in lifecycle._PHASE_ZERO_V1_SCHEMA_BY_POLICY_DIGEST
    )
    historical_policy = lifecycle._policy_from_payload(
        snapshot,
        policy_digest=unmapped_digest,
    )
    assert not historical_policy.mutation_subject_field_variants
    cp = control_plane(tmp_path, state=LifecycleState.PRODUCTION_APPROVAL_REQUIRED)
    cp._policy = historical_policy
    attempt = MutationAttempt(
        attempt_id="unmapped-production-attempt",
        idempotency_key="production:run-65:unmapped",
        subject_digest=SHA,
        action="deploy_production",
        step_plan_digest=OTHER_SHA,
        status="PLANNED",
    )

    with pytest.raises(TransitionDeniedError, match="unavailable or ambiguous"):
        prejournal(cp, attempt)


def test_post_merge_blocking_finding_enters_safe_blocked_state(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.PR_MERGED)
    finding = FindingSignal(
        finding_id="post-merge-1",
        source="finding-source",
        exact_subject_digest=SHA,
        severity="HIGH",
        credible=True,
        blocking=True,
        reviewer_eligible=True,
        category="ENGINEERING",
        disposition="ACCEPTED_FOR_REPAIR",
        affected_scope_digest=OTHER_SHA,
    )
    evidence = {
        "subject_digest": SHA,
        "finding_digest": object_digest(asdict(finding)),
        "zero_resource_digest": SHA,
    }
    bind_work_evidence(evidence, WorkStatus())

    event = cp.transition(
        LifecycleState.BLOCKED,
        context(evidence=evidence, finding=finding),
        reason="post_merge_blocking_finding",
    )
    assert event.evidence_refs["subject_digest"] == SHA
    assert event.evidence_refs["finding_digest"] == object_digest(asdict(finding))
    assert event.resume_state is LifecycleState.REPOSITORY_ANALYSED

    resume_evidence = {
        "subject_digest": SHA,
        "incident_closure_digest": SHA,
        "restored_capability_digest": OTHER_SHA,
        "unchanged_inputs_digest": SHA,
        "finding_digest": evidence["finding_digest"],
        "finding_disposition_digest": OTHER_SHA,
        "remediation_issue_digest": SHA,
        "repository_snapshot_digest": OTHER_SHA,
    }
    resume_evidence["finding_disposition_authentication_evidence_digest"] = external_proof(
        "finding-source",
        SHA,
        {
            "source_id": "finding-source",
            "authority_digest": SHA,
            "subject_digest": SHA,
            "finding_digest": resume_evidence["finding_digest"],
            "finding_disposition_digest": OTHER_SHA,
            "remediation_issue_digest": SHA,
            "repository_snapshot_digest": OTHER_SHA,
            "observed_at": "2026-08-02T00:01:00Z",
        },
    )
    resumed = cp.resume(context(evidence=resume_evidence))
    assert resumed.target is LifecycleState.REPOSITORY_ANALYSED


def test_staging_rejects_a_pending_post_merge_blocker(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.PR_MERGED)
    finding = FindingSignal(
        finding_id="post-merge-2",
        source="finding-source",
        exact_subject_digest=SHA,
        severity="HIGH",
        credible=True,
        blocking=True,
        reviewer_eligible=True,
        category="ENGINEERING",
        disposition="ACCEPTED_FOR_REPAIR",
        affected_scope_digest=OTHER_SHA,
    )
    attempt = MutationAttempt(
        attempt_id="staging-pending-finding",
        idempotency_key="staging:run-65:pending-finding",
        subject_digest=SHA,
        action="deploy_staging",
        step_plan_digest=OTHER_SHA,
        status="PLANNED",
    )
    prejournal(cp, attempt)
    evidence = evidence_for(
        LifecycleState.PR_MERGED,
        LifecycleState.STAGING_DEPLOYED,
        reason="staging_admitted",
    )
    evidence["staging_result_digest"] = SHA
    with pytest.raises(TransitionDeniedError, match="blocking finding"):
        cp.transition(
            LifecycleState.STAGING_DEPLOYED,
            context(evidence=evidence, finding=finding, mutation=attempt),
            reason="staging_admitted",
        )


def test_required_subject_evidence_rejects_cross_run_substitution(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.REPOSITORY_ANALYSED)
    evidence = evidence_for(
        LifecycleState.REPOSITORY_ANALYSED,
        LifecycleState.ARCHITECTURE_PROPOSED,
        reason="architecture_compiled",
    )
    evidence["subject_digest"] = OTHER_SHA
    with pytest.raises(TransitionDeniedError, match="subject evidence"):
        cp.transition(
            LifecycleState.ARCHITECTURE_PROPOSED,
            context(evidence=evidence),
            reason="architecture_compiled",
        )


@pytest.mark.parametrize(
    "finding",
    [
        FindingSignal("", "codex", SHA, "HIGH", True, True, True),
        FindingSignal("finding-source", "", SHA, "HIGH", True, True, True),
        FindingSignal("finding-credible", "codex", SHA, "HIGH", False, True, True),
        FindingSignal("finding-blocking", "codex", SHA, "HIGH", True, False, True),
        FindingSignal("finding-product", "product-decision", SHA, "HIGH", True, True, True),
    ],
    ids=("empty-id", "empty-source", "not-credible", "not-blocking", "product-decision"),
)
def test_repair_rejects_unaccepted_or_incomplete_findings_without_consuming_budget(
    tmp_path: Path, finding: FindingSignal
) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.REVIEW_FAILED)
    required = evidence_for(
        LifecycleState.REVIEW_FAILED,
        LifecycleState.REPAIR_IN_PROGRESS,
        reason="accepted_finding",
    )
    before = cp.budget_usage
    with pytest.raises(TransitionDeniedError, match="accepted engineering finding"):
        cp.transition(
            LifecycleState.REPAIR_IN_PROGRESS,
            context(evidence=required, finding=finding),
            reason="accepted_finding",
        )
    assert cp.state is LifecycleState.REVIEW_FAILED
    assert cp.budget_usage == before


def test_safe_stop_requires_worker_quiescence_and_revoked_mutation_capability(
    tmp_path: Path,
) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.VERIFICATION_FAILED)
    required = evidence_for(
        LifecycleState.VERIFICATION_FAILED,
        LifecycleState.BLOCKED,
        reason="verification_infrastructure_missing",
    )
    required.update(
        worker_quiescence_digest=object_digest(asdict(WorkStatus())),
        mutation_revocation_digest=OTHER_SHA,
    )
    with pytest.raises(TransitionDeniedError, match="workers must be quiescent"):
        cp.transition(
            LifecycleState.BLOCKED,
            context(
                evidence=required,
                work=WorkStatus(worker_leases_active=1, workers_stopped=False),
            ),
            reason="verification_infrastructure_missing",
        )

    assert "mutation_capability_active" in {field.name for field in fields(WorkStatus)}
    with pytest.raises(TransitionDeniedError, match="mutation capability"):
        cp.transition(
            LifecycleState.BLOCKED,
            context(
                evidence=required,
                work=WorkStatus(mutation_capability_active=True),
            ),
            reason="verification_infrastructure_missing",
        )


def test_safe_stop_requires_digest_bound_quiescence_evidence(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.VERIFICATION_FAILED)
    required = evidence_for(
        LifecycleState.VERIFICATION_FAILED,
        LifecycleState.BLOCKED,
        reason="verification_infrastructure_missing",
    )
    with pytest.raises(TransitionDeniedError, match="quiescence evidence"):
        cp.transition(
            LifecycleState.BLOCKED,
            context(evidence=required),
            reason="verification_infrastructure_missing",
        )


def test_budget_policy_admission_replays_after_post_append_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cp = control_plane(tmp_path)
    extended = replace(
        cp.budget_policy,
        version="budget-v2",
        limits={**cp.budget_policy.limits, "tokens": 125},
        approved_by="owner-alice",
    )
    authorization = extension_authorization(cp, extended, amounts={"tokens": 25})
    original_append = cp._append

    def crash_after_admission(**kwargs: object) -> object:
        event = original_append(**kwargs)  # type: ignore[arg-type]
        if kwargs.get("kind") == "BUDGET_POLICY_ADMITTED":
            raise RuntimeError("simulated crash after fsynced admission")
        return event

    monkeypatch.setattr(cp, "_append", crash_after_admission)
    with pytest.raises(RuntimeError, match="simulated crash"):
        cp.admit_budget_policy(
            extended,
            authorization=authorization,
            authority=authority(observed_at="2026-08-02T12:00:00Z"),
            observed_at="2026-08-02T12:00:00Z",
        )

    loaded = LifecycleControlPlane.load(tmp_path)
    assert loaded.budget_policy == extended
    assert loaded.events[-1].evidence_refs["budget_policy_digest"] == object_digest(
        lifecycle._budget_policy_payload(extended)
    )


def test_concurrent_budget_extensions_cannot_overwrite_the_admitted_policy(
    tmp_path: Path,
) -> None:
    first = control_plane(tmp_path)
    stale = LifecycleControlPlane.load(tmp_path, evidence_verifier=verify_external_proof)
    extended = replace(
        first.budget_policy,
        version="budget-v2",
        limits={**first.budget_policy.limits, "tokens": 125},
        approved_by="owner-alice",
    )
    first.admit_budget_policy(
        extended,
        authorization=extension_authorization(first, extended, amounts={"tokens": 25}),
        authority=authority(observed_at="2026-08-02T12:00:00Z"),
        observed_at="2026-08-02T12:00:00Z",
    )
    with pytest.raises(TransitionDeniedError, match="compare-and-swap"):
        stale.admit_budget_policy(
            extended,
            authorization=extension_authorization(stale, extended, amounts={"tokens": 25}),
            authority=authority(observed_at="2026-08-02T12:00:00Z"),
            observed_at="2026-08-02T12:00:00Z",
        )
    assert LifecycleControlPlane.load(tmp_path).budget_policy == extended


def test_ordinary_safe_stop_resumes_only_through_its_admitted_safe_gate(
    tmp_path: Path,
) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.VERIFICATION_FAILED)
    stop_evidence = evidence_for(
        LifecycleState.VERIFICATION_FAILED,
        LifecycleState.BLOCKED,
        reason="verification_infrastructure_missing",
    )
    bind_work_evidence(stop_evidence, WorkStatus())
    stopped = cp.transition(
        LifecycleState.BLOCKED,
        context(evidence=stop_evidence),
        reason="verification_infrastructure_missing",
    )
    assert stopped.resume_state is LifecycleState.VERIFICATION_FAILED
    PHASE_ZERO_POLICY.rule(
        LifecycleState.BLOCKED,
        LifecycleState.VERIFICATION_FAILED,
        reason="recorded_safe_resume",
    )

    resume_evidence = {
        "subject_digest": SHA,
        "incident_closure_digest": SHA,
        "restored_capability_digest": OTHER_SHA,
        "unchanged_inputs_digest": SHA,
    }
    bind_resume_observation(resume_evidence, stopped, LifecycleState.VERIFICATION_FAILED)
    resumed = cp.resume(context(evidence=resume_evidence))
    assert resumed.source is LifecycleState.BLOCKED
    assert resumed.target is LifecycleState.VERIFICATION_FAILED
    assert cp.state is LifecycleState.VERIFICATION_FAILED


def test_recorded_safe_resume_cannot_bypass_resume_admission(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.BLOCKED)
    with pytest.raises(TransitionDeniedError, match="require resume"):
        cp.transition(
            LifecycleState.PRODUCTION_DEPLOYED,
            context(evidence={"subject_digest": SHA}),
            reason="recorded_safe_resume",
        )


def test_unknown_policy_decisions_fail_closed() -> None:
    decision = PolicyEngine().classify("operation.never.registered")
    assert decision.level.value == "high"
    assert PolicyEngine().requires_approval(decision.level)


def test_same_instance_serializes_competing_transitions_before_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cp = control_plane(tmp_path)
    barrier = threading.Barrier(2)
    original_rule = PHASE_ZERO_POLICY.rule

    def synchronized_rule(
        source: LifecycleState, target: LifecycleState, *, reason: str
    ) -> lifecycle.TransitionRule:
        if source is LifecycleState.CONTRACT_RECEIVED:
            with suppress(threading.BrokenBarrierError):
                barrier.wait(timeout=0.5)
        return original_rule(source, target, reason=reason)

    monkeypatch.setattr(PHASE_ZERO_POLICY, "rule", synchronized_rule)
    transitions = (
        (
            LifecycleState.CONTRACT_INVALID,
            "contract_rejected",
            evidence_for(
                LifecycleState.CONTRACT_RECEIVED,
                LifecycleState.CONTRACT_INVALID,
                reason="contract_rejected",
            ),
        ),
        (
            LifecycleState.CONTRACT_APPROVED,
            "contract_admitted",
            evidence_for(
                LifecycleState.CONTRACT_RECEIVED,
                LifecycleState.CONTRACT_APPROVED,
                reason="contract_admitted",
            ),
        ),
    )

    def apply(item: tuple[LifecycleState, str, dict[str, str]]) -> str:
        target, reason, evidence = item
        try:
            cp.transition(target, context(evidence=evidence), reason=reason)
        except TransitionDeniedError:
            return "denied"
        return "applied"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(apply, transitions))

    assert sorted(outcomes) == ["applied", "denied"]
    loaded = LifecycleControlPlane.load(tmp_path)
    applied = [event for event in loaded.events if event.outcome == "APPLIED"]
    assert len(applied) == 2  # STATE_CREATED plus exactly one competing transition.
    assert applied[-1].source is LifecycleState.CONTRACT_RECEIVED


def test_rollback_completion_requires_exact_attempt_bound_zero_exposure(
    tmp_path: Path,
) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.ROLLBACK_IN_PROGRESS)
    attempt = MutationAttempt(
        attempt_id="rollback-exposure-1",
        idempotency_key="rollback:run-65:exposure-1",
        subject_digest=SHA,
        action="rollback",
        step_plan_digest=rollback_plan(),
        status="PLANNED",
    )
    prejournal(cp, attempt)
    record_result(cp, attempt, status="SUCCEEDED", result_digest=SHA)
    required = evidence_for(
        LifecycleState.ROLLBACK_IN_PROGRESS,
        LifecycleState.ROLLED_BACK,
        reason="rollback_verified",
    )
    required.update(
        {
            "subject_digest": SHA,
            "rollback_attempt_digest": object_digest(asdict(attempt)),
            "rollback_result_digest": SHA,
            "rollback_exposure_digest": object_digest(
                {
                    "subject_digest": SHA,
                    "rollback_attempt_digest": object_digest(asdict(attempt)),
                    "rollback_result_digest": SHA,
                    "canary": "ACTIVE",
                    "changed_production": "UNKNOWN",
                }
            ),
        }
    )

    with pytest.raises(TransitionDeniedError, match="unresolved exposure"):
        cp.transition(
            LifecycleState.ROLLED_BACK,
            context(
                evidence=required,
                mutation=attempt,
                rollout=RolloutStatus(
                    staging="REMOVED",
                    canary="ACTIVE",
                    changed_production="UNKNOWN",
                ),
            ),
            reason="rollback_verified",
        )
    required["rollback_exposure_digest"] = object_digest(
        {
            "subject_digest": SHA,
            "rollback_attempt_digest": object_digest(asdict(attempt)),
            "rollback_result_digest": SHA,
            "canary": "REMOVED",
            "changed_production": "REMOVED",
        }
    )
    admitted = cp.transition(
        LifecycleState.ROLLED_BACK,
        context(
            evidence=required,
            mutation=attempt,
            rollout=RolloutStatus(
                staging="REMOVED",
                canary="REMOVED",
                changed_production="REMOVED",
            ),
            usage=cp.budget_usage,
        ),
        reason="rollback_verified",
    )
    assert admitted.target is LifecycleState.ROLLED_BACK


def test_canary_progression_rejects_foreign_or_stale_active_canary_proof(
    tmp_path: Path,
) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.STAGING_DEPLOYED)
    admitted = evidence_for(
        LifecycleState.STAGING_DEPLOYED,
        LifecycleState.CANARY_DEPLOYED,
        reason="canary_admitted",
    )
    admitted.update(
        {
            "subject_digest": SHA,
            "canary_id_digest": object_digest("canary-run-65-1"),
        }
    )
    attempt = MutationAttempt(
        attempt_id="canary-deploy-1",
        idempotency_key="canary:run-65:deploy-1",
        subject_digest=SHA,
        action="deploy_canary",
        step_plan_digest=mutation_subject_digest("deploy_canary", admitted),
        status="PLANNED",
    )
    prejournal(cp, attempt)
    record_result(cp, attempt, status="SUCCEEDED", result_digest=SHA)
    admitted.update(
        {
            "canary_attempt_digest": object_digest(asdict(attempt)),
            "canary_result_digest": SHA,
            "canary_status_digest": object_digest(
                {
                    "canary_id_digest": object_digest("canary-run-65-1"),
                    "deployment_attempt_digest": object_digest(asdict(attempt)),
                    "deployment_result_digest": SHA,
                    "subject_digest": SHA,
                    "status": "ACTIVE",
                }
            ),
        }
    )
    cp.transition(
        LifecycleState.CANARY_DEPLOYED,
        context(
            evidence=admitted,
            mutation=attempt,
            rollout=RolloutStatus(staging="ACTIVE", canary="ACTIVE"),
        ),
        reason="canary_admitted",
    )
    promotion = evidence_for(
        LifecycleState.CANARY_DEPLOYED,
        LifecycleState.PRODUCTION_APPROVAL_REQUIRED,
        reason="canary_window_passed",
    )
    promotion.update(
        {
            "subject_digest": SHA,
            "canary_id_digest": object_digest("foreign-canary"),
            "canary_attempt_digest": object_digest(asdict(attempt)),
            "canary_status_digest": admitted["canary_status_digest"],
        }
    )

    with pytest.raises(TransitionDeniedError, match="canary"):
        cp.transition(
            LifecycleState.PRODUCTION_APPROVAL_REQUIRED,
            context(
                evidence=promotion,
                rollout=RolloutStatus(staging="ACTIVE", canary="ACTIVE"),
            ),
            reason="canary_window_passed",
        )

    promotion.update(
        {
            "canary_id_digest": admitted["canary_id_digest"],
            "canary_status_digest": admitted["canary_status_digest"],
        }
    )
    with pytest.raises(TransitionDeniedError, match="canary"):
        cp.transition(
            LifecycleState.PRODUCTION_APPROVAL_REQUIRED,
            context(
                evidence=promotion,
                rollout=RolloutStatus(staging="ACTIVE", canary="REMOVED"),
            ),
            reason="canary_window_passed",
        )

    assert LifecycleControlPlane.load(tmp_path).state is LifecycleState.CANARY_DEPLOYED


def test_completion_rejects_review_binding_from_a_different_frozen_candidate(
    tmp_path: Path,
) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.PRODUCTION_DEPLOYED)
    reviewed_commit = "a" * 40
    reviewed_candidate = object_digest({"tree": "reviewed-candidate"})
    review_evidence = object_digest({"bundle": "reviewed-evidence"})
    approval = Approval(
        approval_id="codex-review-1",
        actor="codex",
        subject_digest=SHA,
        kind="FORMAL_REVIEW",
        eligible=True,
        active=True,
        reviewed_commit_sha=reviewed_commit,
        reviewed_candidate_digest=reviewed_candidate,
        review_evidence_digest=review_evidence,
    )
    cp._append(
        kind="REVIEW_BINDING_ADMITTED",
        outcome="RECORDED",
        source=LifecycleState.PRODUCTION_DEPLOYED,
        target=LifecycleState.PRODUCTION_DEPLOYED,
        reason="formal_review_clear",
        actor=approval.actor,
        evidence_refs={
            "subject_digest": SHA,
            "reviewed_commit_sha": reviewed_commit,
            "prospective_tree_digest": reviewed_candidate,
            "verification_bundle_digest": review_evidence,
            "review_digest": object_digest(asdict(approval)),
        },
        observed_at="2026-08-02T00:01:00Z",
    )
    completion = evidence_for(
        LifecycleState.PRODUCTION_DEPLOYED,
        LifecycleState.COMPLETED,
        reason="observation_window_passed",
    )
    completion.update(
        {
            "subject_digest": SHA,
            "release_sha": reviewed_commit,
            "reviewed_commit_sha": reviewed_commit,
            "reviewed_candidate_digest": OTHER_SHA,
            "review_evidence_digest": review_evidence,
            "evidence_bundle_digest": review_evidence,
        }
    )

    with pytest.raises(TransitionDeniedError, match="reviewed candidate"):
        cp.transition(
            LifecycleState.COMPLETED,
            context(evidence=completion),
            reason="observation_window_passed",
        )
    assert not cp.completion_claim_active


def test_quarantine_disposition_failure_enters_bound_security_block(
    tmp_path: Path,
) -> None:
    cp = control_plane(tmp_path)
    stopped_work = WorkStatus(
        worker_leases_active=0,
        workers_stopped=True,
        mutation_capability_active=False,
        partial_output_disposition="quarantined-unresolved",
    )
    affected_artifact = object_digest({"artifact": "untrusted-contract"})
    blocked_evidence = {
        "subject_digest": SHA,
        "intake_receipt_digest": object_digest("receipt"),
        "affected_artifact_digest": affected_artifact,
        "quarantine_disposition_status": "UNKNOWN",
        "quarantine_disposition_digest": object_digest(
            {
                "affected_artifact_digest": affected_artifact,
                "subject_digest": SHA,
                "status": "UNKNOWN",
            }
        ),
        "exposure_digest": object_digest(
            {
                "affected_artifact_digest": affected_artifact,
                "subject_digest": SHA,
                "rollout": asdict(RolloutStatus(changed_production="UNKNOWN")),
            }
        ),
        "incident_digest": object_digest("incident-1"),
        "worker_quiescence_digest": object_digest(asdict(stopped_work)),
        "mutation_revocation_digest": object_digest("revoked"),
        "retry_gate_digest": object_digest(
            {
                "affected_artifact_digest": affected_artifact,
                "gate": "AUTHORITATIVE_DISPOSITION_REQUIRED",
                "subject_digest": SHA,
            }
        ),
    }
    with pytest.raises(TransitionDeniedError, match="trusted|quiescence|revocation"):
        cp.transition(
            LifecycleState.BLOCKED,
            context(
                evidence=blocked_evidence,
                work=stopped_work,
                rollout=RolloutStatus(changed_production="UNKNOWN"),
            ),
            reason="quarantine_disposition_indeterminate",
        )
    bind_work_evidence(blocked_evidence, stopped_work)
    blocked = cp.transition(
        LifecycleState.BLOCKED,
        context(
            evidence=blocked_evidence,
            work=stopped_work,
            rollout=RolloutStatus(changed_production="UNKNOWN"),
        ),
        reason="quarantine_disposition_indeterminate",
    )
    assert blocked.resume_state is LifecycleState.CONTRACT_RECEIVED
    assert blocked.evidence_refs["affected_artifact_digest"] == affected_artifact
    resume_evidence = {
        "subject_digest": SHA,
        "incident_closure_digest": object_digest("incident-closed"),
        "restored_capability_digest": object_digest("intake-only"),
        "unchanged_inputs_digest": object_digest("same-artifact"),
    }
    with pytest.raises(TransitionDeniedError, match="quarantine disposition"):
        cp.resume(context(evidence=resume_evidence, work=stopped_work))
    base_actor = context().actor
    disposition_capabilities = frozenset(
        {"lifecycle.transition", "lifecycle.quarantine.disposition"}
    )
    disposition_authority = external_proof(
        base_actor.actor_id,
        base_actor.authority_digest,
        {
            "actor_id": base_actor.actor_id,
            "role": base_actor.role,
            "authenticated": base_actor.authenticated,
            "capabilities": sorted(disposition_capabilities),
            "subject_digest": base_actor.subject_digest,
            "authority_digest": base_actor.authority_digest,
        },
    )
    disposition_actor = replace(
        base_actor,
        capabilities=disposition_capabilities,
        authentication_evidence_digest=disposition_authority,
    )
    resume_evidence.update(
        {
            "affected_artifact_digest": affected_artifact,
            "quarantine_disposition_status": "AUTHORITATIVELY_DISPOSED",
            "quarantine_disposition_observer_id": "repository-observer",
            "quarantine_disposition_observer_authority_digest": OTHER_SHA,
            "quarantine_disposition_authentication_evidence_digest": external_proof(
                "repository-observer",
                OTHER_SHA,
                {
                    "observer_id": "repository-observer",
                    "authority_digest": OTHER_SHA,
                    "affected_artifact_digest": affected_artifact,
                    "subject_digest": SHA,
                    "status": "AUTHORITATIVELY_DISPOSED",
                    "observed_at": "2026-08-02T00:01:00Z",
                },
            ),
        }
    )
    resumed = cp.resume(
        context(
            evidence=resume_evidence,
            work=stopped_work,
            rollout=RolloutStatus(changed_production="REMOVED"),
            actor=disposition_actor,
        )
    )
    assert resumed.target is LifecycleState.CONTRACT_RECEIVED


def test_repository_drift_requires_quiesced_digest_bound_work(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.IMPLEMENTATION_IN_PROGRESS)
    required = evidence_for(
        LifecycleState.IMPLEMENTATION_IN_PROGRESS,
        LifecycleState.REPOSITORY_ANALYSED,
        reason="repository_drift",
    )

    with pytest.raises(TransitionDeniedError, match="drift"):
        cp.transition(
            LifecycleState.REPOSITORY_ANALYSED,
            context(
                evidence=required,
                work=WorkStatus(
                    worker_leases_active=1,
                    workers_stopped=False,
                    mutation_capability_active=True,
                    partial_output_disposition="unverified",
                ),
            ),
            reason="repository_drift",
        )

    assert cp.state is LifecycleState.IMPLEMENTATION_IN_PROGRESS
    stopped_work = WorkStatus(
        workers_stopped=True,
        mutation_capability_active=False,
        partial_output_disposition="frozen-unverified-non-admissible",
    )
    bind_work_evidence(required, stopped_work)
    admitted = cp.transition(
        LifecycleState.REPOSITORY_ANALYSED,
        context(evidence=required, work=stopped_work),
        reason="repository_drift",
    )
    assert admitted.target is LifecycleState.REPOSITORY_ANALYSED


def test_production_approval_cannot_be_reused_for_an_unbound_rollout(
    tmp_path: Path,
) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.PRODUCTION_APPROVAL_REQUIRED)
    attempt = MutationAttempt(
        attempt_id="attempt-production-unbound",
        idempotency_key="production:run-65:unbound",
        subject_digest=SHA,
        action="deploy_production",
        step_plan_digest=OTHER_SHA,
        status="PLANNED",
    )
    prejournal(cp, attempt)
    record_result(cp, attempt, status="SUCCEEDED", result_digest=SHA)
    required = evidence_for(
        LifecycleState.PRODUCTION_APPROVAL_REQUIRED,
        LifecycleState.PRODUCTION_DEPLOYED,
        reason="production_admitted",
    )
    required.update(record_active_canary_binding(cp))
    required.update(
        {
            "production_attempt_digest": object_digest(asdict(attempt)),
            "production_result_digest": SHA,
        }
    )
    prior_rollout = dict(required)
    prior_rollout["configuration_digest"] = object_digest("prior-production-config")
    stale_approval = replace(
        production_approval_for(prior_rollout),
        approval_id="production-approval-stale",
    )
    required["production_approval_digest"] = object_digest(asdict(stale_approval))

    with pytest.raises(TransitionDeniedError, match="production approval"):
        cp.transition(
            LifecycleState.PRODUCTION_DEPLOYED,
            context(
                evidence=required,
                mutation=attempt,
                approvals=(stale_approval,),
                rollout=RolloutStatus(canary="ACTIVE"),
            ),
            reason="production_admitted",
        )

    assert cp.state is LifecycleState.PRODUCTION_APPROVAL_REQUIRED


def test_product_input_requires_revoked_digest_bound_mutation_capability(
    tmp_path: Path,
) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.IMPLEMENTATION_IN_PROGRESS)
    required = evidence_for(
        LifecycleState.IMPLEMENTATION_IN_PROGRESS,
        LifecycleState.PRODUCT_INPUT_REQUIRED,
        reason="authority_invalidated",
    )

    with pytest.raises(TransitionDeniedError, match="product input"):
        cp.transition(
            LifecycleState.PRODUCT_INPUT_REQUIRED,
            context(
                evidence=required,
                work=WorkStatus(
                    workers_stopped=True,
                    mutation_capability_active=True,
                    partial_output_disposition="frozen-unverified-non-admissible",
                ),
            ),
            reason="authority_invalidated",
        )

    assert cp.state is LifecycleState.IMPLEMENTATION_IN_PROGRESS
    stopped_work = WorkStatus(
        workers_stopped=True,
        mutation_capability_active=False,
        partial_output_disposition="frozen-unverified-non-admissible",
    )
    bind_work_evidence(required, stopped_work)
    admitted = cp.transition(
        LifecycleState.PRODUCT_INPUT_REQUIRED,
        context(evidence=required, work=stopped_work),
        reason="authority_invalidated",
    )
    assert admitted.target is LifecycleState.PRODUCT_INPUT_REQUIRED


def test_concurrent_creation_cannot_diverge_metadata_from_initial_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_append = LifecycleControlPlane._append
    entrants = threading.Barrier(2)

    def synchronized_initial_append(
        self: LifecycleControlPlane, **kwargs: object
    ) -> lifecycle.LifecycleEvent:
        if kwargs.get("kind") == "STATE_CREATED":
            with suppress(threading.BrokenBarrierError):
                entrants.wait(timeout=0.25)
        return original_append(self, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(LifecycleControlPlane, "_append", synchronized_initial_append)
    policy, _ = budgets()
    barrier = threading.Barrier(2)

    def create(run_id: str, subject_digest: str) -> LifecycleControlPlane:
        barrier.wait()
        return LifecycleControlPlane.create(
            tmp_path,
            run_id=run_id,
            subject_digest=subject_digest,
            initial_state=LifecycleState.CONTRACT_RECEIVED,
            budget_policy=policy,
            lifecycle_policy=PHASE_ZERO_POLICY,
        )

    successes: list[LifecycleControlPlane] = []
    failures: list[BaseException] = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (
            executor.submit(create, "run-winner-a", SHA),
            executor.submit(create, "run-winner-b", OTHER_SHA),
        )
        for future in futures:
            try:
                successes.append(future.result())
            except BaseException as exc:  # noqa: BLE001 - capture the losing creator
                failures.append(exc)

    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], (TransitionDeniedError, ValueError))
    replayed = LifecycleControlPlane.load(tmp_path)
    assert replayed.run_id == successes[0].run_id
    assert replayed.subject_digest == successes[0].subject_digest


def test_completion_revocation_requires_active_claim_and_monitor_authority(
    tmp_path: Path,
) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.PRODUCTION_DEPLOYED)
    cp.transition(
        LifecycleState.COMPLETED,
        context(evidence=completion_evidence_with_review_binding(cp)),
        reason="observation_window_passed",
    )
    invalidation = evidence_for(
        LifecycleState.COMPLETED,
        LifecycleState.LIVE_VERIFICATION_FAILED,
        reason="completion_evidence_invalidated",
    )

    with pytest.raises(TransitionDeniedError, match="completion"):
        cp.transition(
            LifecycleState.LIVE_VERIFICATION_FAILED,
            context(evidence=invalidation),
            reason="completion_evidence_invalidated",
        )

    assert cp.state is LifecycleState.COMPLETED
    assert cp.completion_claim_active


def test_native_merge_requires_the_exact_persisted_review_binding(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.PR_READY)
    reviewed_commit = "a" * 40
    reviewed_tree = object_digest("reviewed-tree")
    review_evidence = object_digest("review-evidence")
    review_digest = object_digest("formal-review")
    cp._append(
        kind="REVIEW_BINDING_ADMITTED",
        outcome="RECORDED",
        source=cp.state,
        target=cp.state,
        reason="formal_review_clear",
        actor="codex",
        evidence_refs={
            "subject_digest": SHA,
            "reviewed_commit_sha": reviewed_commit,
            "prospective_tree_digest": reviewed_tree,
            "verification_bundle_digest": review_evidence,
            "review_digest": review_digest,
        },
        observed_at="2026-08-02T00:01:00Z",
    )
    planned_evidence = evidence_for(
        LifecycleState.PR_READY,
        LifecycleState.PR_MERGED,
        reason="native_merge_linearized",
    )
    planned_evidence.update(
        {
            "queue_subject_digest": SHA,
            "head_commit_sha": reviewed_commit,
            "head_digest": object_digest(reviewed_commit),
            "prospective_tree_digest": reviewed_tree,
            "verification_bundle_digest": review_evidence,
            "formal_review_digest": review_digest,
        }
    )
    merge_output = {
        "head_commit_sha": reviewed_commit,
        "merge_commit_sha": "b" * 40,
        "merge_tree_digest": reviewed_tree,
        "merge_method_digest": object_digest("protected-native-merge"),
        "merge_actor_digest": object_digest("github-merge-queue"),
    }
    merge_result_digest = object_digest(merge_output)
    planned_evidence.update(merge_output, merge_result_digest=merge_result_digest)
    attempt = MutationAttempt(
        attempt_id="merge-attempt-1",
        idempotency_key="merge:run-65:1",
        subject_digest=SHA,
        action="enqueue_merge",
        step_plan_digest=mutation_subject_digest("enqueue_merge", planned_evidence),
        status="PLANNED",
    )
    prejournal(cp, attempt)
    record_result(cp, attempt, status="SUCCEEDED", result_digest=merge_result_digest)
    planned_evidence["merge_attempt_digest"] = object_digest(asdict(attempt))
    evidence = {**planned_evidence, "prospective_tree_digest": object_digest("unreviewed-tree")}

    with pytest.raises(TransitionDeniedError, match="review binding"):
        cp.transition(
            LifecycleState.PR_MERGED,
            context(evidence=evidence, mutation=attempt),
            reason="native_merge_linearized",
        )

    evidence["prospective_tree_digest"] = reviewed_tree
    merged = cp.transition(
        LifecycleState.PR_MERGED,
        context(evidence=evidence, mutation=attempt, usage=cp.budget_usage),
        reason="native_merge_linearized",
    )
    assert merged.target is LifecycleState.PR_MERGED

    staging_evidence = evidence_for(
        LifecycleState.PR_MERGED,
        LifecycleState.STAGING_DEPLOYED,
        reason="staging_admitted",
    )
    staging_evidence["merge_digest"] = object_digest("unrelated-merge")
    staging_attempt = MutationAttempt(
        attempt_id="stage-unrelated-merge",
        idempotency_key="stage:run-65:unrelated-merge",
        subject_digest=SHA,
        action="deploy_staging",
        step_plan_digest=mutation_subject_digest("deploy_staging", staging_evidence),
        status="PLANNED",
    )
    prejournal(cp, staging_attempt)
    record_result(cp, staging_attempt, status="SUCCEEDED", result_digest=SHA)
    staging_evidence["staging_attempt_digest"] = object_digest(asdict(staging_attempt))
    staging_evidence["staging_result_digest"] = SHA
    with pytest.raises(TransitionDeniedError, match="merge result|integrated merge"):
        cp.transition(
            LifecycleState.STAGING_DEPLOYED,
            context(evidence=staging_evidence, mutation=staging_attempt),
            reason="staging_admitted",
        )


def test_phase_four_merge_keeps_advisory_and_post_ready_formal_review_distinct(
    tmp_path: Path,
) -> None:
    merge_admission_bundle = object_digest("sealed-merge-admission-profile")
    observed_bundles: list[tuple[str, dict[str, str]]] = []

    def verify_bundle(digest: str, bindings: Mapping[str, str]) -> bool:
        observed_bundles.append((digest, dict(bindings)))
        return (
            digest == merge_admission_bundle
            and bindings.get("profile") == "merge_admission"
            and bool(bindings.get("as_of"))
        )

    cp = control_plane(
        tmp_path,
        state=LifecycleState.PR_READY,
        lifecycle_policy=lifecycle.PHASE_FOUR_POLICY,
        bundle_verifier=verify_bundle,
    )
    reviewed_commit = "a" * 40
    reviewed_tree = object_digest("reviewed-tree")
    advisory_bundle = object_digest("advisory-bundle")
    advisory_digest = object_digest("advisory-analysis")
    review_policy_evidence = {
        name: "a" * 40 if name.endswith("_sha") else object_digest(name)
        for name in lifecycle._PHASE_FOUR_REVIEW_FIELDS
    }
    cp._append(
        kind="REVIEW_BINDING_ADMITTED",
        outcome="RECORDED",
        source=cp.state,
        target=cp.state,
        reason="advisory_readiness_clear",
        actor="codex-advisory",
        evidence_refs={
            "subject_digest": SHA,
            "reviewed_commit_sha": reviewed_commit,
            "prospective_tree_digest": reviewed_tree,
            "verification_bundle_digest": advisory_bundle,
            "review_digest": advisory_digest,
            **review_policy_evidence,
        },
        observed_at="2026-08-01T23:59:00Z",
    )
    approval = Approval(
        approval_id="formal-review-after-ready",
        actor="codex",
        subject_digest=SHA,
        kind="FORMAL_REVIEW",
        eligible=True,
        active=True,
        reviewed_commit_sha=reviewed_commit,
        reviewed_candidate_digest=reviewed_tree,
        review_evidence_digest=advisory_bundle,
        submitted_at="2026-08-02T00:00:00Z",
    )
    approval = replace(
        approval,
        authentication_evidence_digest=external_proof(
            approval.actor,
            SHA,
            lifecycle._production_approval_payload(approval),
        ),
    )
    formal_digest = object_digest(asdict(approval))
    rule = lifecycle.PHASE_FOUR_POLICY.rule(
        LifecycleState.PR_READY,
        LifecycleState.PR_MERGED,
        reason="native_merge_linearized",
    )
    planned_evidence = {
        name: (
            SHA
            if name == "subject_digest"
            else "a" * 40
            if name.endswith("_sha")
            else object_digest(name)
        )
        for name in rule.required_evidence
    }
    planned_evidence.update(
        review_policy_evidence,
        subject_digest=SHA,
        queue_subject_digest=SHA,
        head_commit_sha=reviewed_commit,
        head_digest=object_digest(reviewed_commit),
        prospective_tree_digest=reviewed_tree,
        verification_bundle_digest=advisory_bundle,
        merge_admission_bundle_digest=merge_admission_bundle,
        formal_review_digest=formal_digest,
        finding_source_set_digest=object_digest(dict(TRUST_POLICY.finding_sources)),
        finding_inventory_epochs_digest=object_digest(
            dict.fromkeys(TRUST_POLICY.finding_sources, OTHER_SHA)
        ),
    )
    merge_output = {
        "head_commit_sha": reviewed_commit,
        "merge_commit_sha": "b" * 40,
        "merge_tree_digest": reviewed_tree,
        "merge_method_digest": object_digest("protected-native-merge"),
        "merge_actor_digest": object_digest("github-merge-queue"),
    }
    merge_result_digest = object_digest(merge_output)
    planned_evidence.update(merge_output, merge_result_digest=merge_result_digest)
    attempt = MutationAttempt(
        attempt_id="phase-four-merge",
        idempotency_key="merge:phase-four:1",
        subject_digest=SHA,
        action="enqueue_merge",
        step_plan_digest=mutation_subject_digest("enqueue_merge", planned_evidence),
        status="PLANNED",
    )
    prejournal(cp, attempt, evidence=planned_evidence)
    record_result(cp, attempt, status="SUCCEEDED", result_digest=merge_result_digest)
    planned_evidence["merge_attempt_digest"] = object_digest(asdict(attempt))

    with pytest.raises(TransitionDeniedError, match="native merge-gate"):
        cp.transition(
            LifecycleState.PR_MERGED,
            context(
                evidence=planned_evidence,
                approvals=(approval,),
                mutation=attempt,
                usage=cp.budget_usage,
            ),
            reason="native_merge_linearized",
        )

    native_gate_actor = "github-merge-queue"
    native_gate_authority = TRUST_POLICY.native_merge_gates[native_gate_actor]
    native_gate_payload = lifecycle._native_merge_gate_payload(planned_evidence)
    planned_evidence.update(
        native_merge_gate_actor=native_gate_actor,
        native_merge_gate_authority_digest=native_gate_authority,
        native_merge_gate_digest=object_digest(native_gate_payload),
        native_merge_gate_authentication_evidence_digest=external_proof(
            native_gate_actor,
            native_gate_authority,
            native_gate_payload,
        ),
    )

    drifted_evidence = dict(planned_evidence)
    drifted_evidence["security_policy_digest"] = object_digest("changed-security-policy")
    drifted_native_gate_payload = lifecycle._native_merge_gate_payload(drifted_evidence)
    drifted_evidence.update(
        native_merge_gate_digest=object_digest(drifted_native_gate_payload),
        native_merge_gate_authentication_evidence_digest=external_proof(
            native_gate_actor,
            native_gate_authority,
            drifted_native_gate_payload,
        ),
    )
    with pytest.raises(TransitionDeniedError, match="review binding"):
        cp.transition(
            LifecycleState.PR_MERGED,
            context(
                evidence=drifted_evidence,
                approvals=(approval,),
                mutation=attempt,
                usage=cp.budget_usage,
            ),
            reason="native_merge_linearized",
        )

    merged = cp.transition(
        LifecycleState.PR_MERGED,
        context(
            evidence=planned_evidence,
            approvals=(approval,),
            mutation=attempt,
            usage=cp.budget_usage,
        ),
        reason="native_merge_linearized",
    )

    assert merged.target is LifecycleState.PR_MERGED
    assert formal_digest != advisory_digest
    assert len(observed_bundles) >= 2
    assert all(digest == merge_admission_bundle for digest, _ in observed_bundles)


def test_phase_four_merge_revalidates_bundle_after_prejournal(tmp_path: Path) -> None:
    bundle_available = True
    verification_calls = 0
    merge_admission_bundle = object_digest("expiring-merge-admission-profile")

    def verify_bundle(digest: str, bindings: Mapping[str, str]) -> bool:
        nonlocal verification_calls
        verification_calls += 1
        return bool(
            bundle_available
            and digest == merge_admission_bundle
            and bindings.get("profile") == "merge_admission"
            and bool(bindings.get("as_of"))
        )

    cp = control_plane(
        tmp_path,
        state=LifecycleState.PR_READY,
        lifecycle_policy=lifecycle.PHASE_FOUR_POLICY,
        bundle_verifier=verify_bundle,
    )
    reviewed_commit = "a" * 40
    reviewed_tree = object_digest("reviewed-tree")
    advisory_bundle = object_digest("advisory-bundle")
    review_policy_evidence = {
        name: "a" * 40 if name.endswith("_sha") else object_digest(name)
        for name in lifecycle._PHASE_FOUR_REVIEW_FIELDS
    }
    cp._append(
        kind="REVIEW_BINDING_ADMITTED",
        outcome="RECORDED",
        source=cp.state,
        target=cp.state,
        reason="advisory_readiness_clear",
        actor="codex-advisory",
        evidence_refs={
            "subject_digest": SHA,
            "reviewed_commit_sha": reviewed_commit,
            "prospective_tree_digest": reviewed_tree,
            "verification_bundle_digest": advisory_bundle,
            "review_digest": object_digest("advisory-analysis"),
            **review_policy_evidence,
        },
        observed_at="2026-08-01T23:59:00Z",
    )
    rule = lifecycle.PHASE_FOUR_POLICY.rule(
        LifecycleState.PR_READY,
        LifecycleState.PR_MERGED,
        reason="native_merge_linearized",
    )
    evidence = {
        name: (
            SHA
            if name == "subject_digest"
            else "a" * 40
            if name.endswith("_sha")
            else object_digest(name)
        )
        for name in rule.required_evidence
    }
    evidence.update(
        review_policy_evidence,
        subject_digest=SHA,
        queue_subject_digest=SHA,
        head_commit_sha=reviewed_commit,
        head_digest=object_digest(reviewed_commit),
        prospective_tree_digest=reviewed_tree,
        verification_bundle_digest=advisory_bundle,
        merge_admission_bundle_digest=merge_admission_bundle,
        finding_source_set_digest=object_digest(dict(TRUST_POLICY.finding_sources)),
        finding_inventory_epochs_digest=object_digest(
            dict.fromkeys(TRUST_POLICY.finding_sources, OTHER_SHA)
        ),
    )
    attempt = MutationAttempt(
        attempt_id="phase-four-expiring-merge",
        idempotency_key="merge:phase-four:expiring",
        subject_digest=SHA,
        action="enqueue_merge",
        step_plan_digest=mutation_subject_digest("enqueue_merge", evidence),
        status="PLANNED",
    )
    stale_authorization = replace(
        mutation_authorization(cp, attempt),
        observed_at="2026-08-02T00:00:00Z",
        expires_at="2026-08-02T00:05:00Z",
        authentication_evidence_digest="",
    )
    stale_payload = {
        "authorizer_id": stale_authorization.authorizer_id,
        "authority_digest": stale_authorization.authority_digest,
        "subject_digest": stale_authorization.subject_digest,
        "source_state": stale_authorization.source_state.value,
        "action": stale_authorization.action,
        "attempt_id": stale_authorization.attempt_id,
        "idempotency_key": stale_authorization.idempotency_key,
        "step_plan_digest": stale_authorization.step_plan_digest,
        "steps": list(stale_authorization.steps),
        "observed_at": stale_authorization.observed_at,
        "expires_at": stale_authorization.expires_at,
    }
    stale_authorization = replace(
        stale_authorization,
        authentication_evidence_digest=external_proof(
            stale_authorization.authorizer_id,
            stale_authorization.authority_digest,
            stale_payload,
        ),
    )
    with pytest.raises(TransitionDeniedError, match="current external lifecycle authority"):
        cp.prejournal_mutation(
            attempt,
            authorization=stale_authorization,
            evidence=evidence,
        )
    assert verification_calls == 0

    prejournal(cp, attempt, evidence=evidence)
    assert verification_calls == 1
    bundle_available = False

    with pytest.raises(TransitionDeniedError, match="merge-admission EvidenceBundle"):
        cp.transition(
            LifecycleState.PR_MERGED,
            context(evidence=evidence, mutation=attempt),
            reason="native_merge_linearized",
        )

    assert cp.state is LifecycleState.PR_READY
    assert verification_calls == 2


def test_budget_extension_rejects_caller_computable_owner_proof(tmp_path: Path) -> None:
    cp = control_plane(tmp_path)
    extended = replace(
        cp.budget_policy,
        version="budget-v2-untrusted",
        limits={**cp.budget_policy.limits, "tokens": 125},
        approved_by="owner-alice",
    )
    authorization = extension_authorization(cp, extended, amounts={"tokens": 25})
    authorization = replace(
        authorization,
        evidence_digest=object_digest(
            lifecycle._budget_extension_authorization_payload(authorization)
        ),
    )
    with pytest.raises(TransitionDeniedError, match="trusted|owner.*authority"):
        cp.admit_budget_policy(
            extended,
            authorization=authorization,
            authority=authority(observed_at="2026-08-02T12:00:00Z"),
            observed_at="2026-08-02T12:00:00Z",
        )


def test_production_artifact_must_match_the_artifact_exercised_by_canary(
    tmp_path: Path,
) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.PRODUCTION_APPROVAL_REQUIRED)
    canary_attempt = object_digest("canary-attempt")
    canary_evidence = {
        "subject_digest": SHA,
        "merge_commit_sha": "a" * 40,
        "merge_digest": object_digest("merge"),
        "artifact_digest": object_digest("artifact-a"),
        "configuration_digest": object_digest("config-a"),
        "migration_plan_digest": object_digest("migration-a"),
        "deployment_target_digest": object_digest("target"),
        "rollout_plan_digest": object_digest("rollout"),
        "staging_digest": object_digest("staging-a"),
        "canary_id_digest": object_digest("canary-a"),
        "canary_attempt_digest": canary_attempt,
    }
    canary_evidence["canary_status_digest"] = object_digest(
        {
            "canary_id_digest": canary_evidence["canary_id_digest"],
            "deployment_attempt_digest": canary_attempt,
            "deployment_result_digest": SHA,
            "subject_digest": SHA,
            "status": "ACTIVE",
        }
    )
    cp._append(
        kind="CANARY_BINDING_ADMITTED",
        outcome="RECORDED",
        source=cp.state,
        target=cp.state,
        reason="canary_admitted",
        actor="fixture",
        evidence_refs=canary_evidence,
        observed_at="2026-08-02T00:01:00Z",
    )
    attempt = MutationAttempt(
        attempt_id="production-attempt-artifact-b",
        idempotency_key="production:run-65:artifact-b",
        subject_digest=SHA,
        action="deploy_production",
        step_plan_digest=OTHER_SHA,
        status="PLANNED",
    )
    prejournal(cp, attempt)
    record_result(cp, attempt, status="SUCCEEDED", result_digest=SHA)
    evidence = evidence_for(
        LifecycleState.PRODUCTION_APPROVAL_REQUIRED,
        LifecycleState.PRODUCTION_DEPLOYED,
        reason="production_admitted",
    )
    evidence.update(canary_evidence)
    evidence["artifact_digest"] = object_digest("artifact-b")
    evidence["configuration_digest"] = object_digest("config-b")
    evidence["production_attempt_digest"] = object_digest(asdict(attempt))
    evidence["production_result_digest"] = SHA
    approval = production_approval_for(evidence)
    evidence["production_approval_digest"] = object_digest(asdict(approval))

    with pytest.raises(TransitionDeniedError, match="canary.*artifact|artifact.*canary"):
        cp.transition(
            LifecycleState.PRODUCTION_DEPLOYED,
            context(
                evidence=evidence,
                mutation=attempt,
                approvals=(approval,),
                rollout=RolloutStatus(canary="ACTIVE"),
            ),
            reason="production_admitted",
        )


@pytest.mark.parametrize(
    "unsafe_work",
    (
        WorkStatus(worker_leases_active=1, workers_stopped=False),
        WorkStatus(mutation_capability_active=True),
    ),
)
def test_every_budget_stop_requires_digest_bound_worker_quiescence(
    tmp_path: Path, unsafe_work: WorkStatus
) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.VERIFICATION_FAILED)
    _, exhausted = budgets(tokens=101)
    evidence = evidence_for(
        LifecycleState.VERIFICATION_FAILED,
        LifecycleState.BUDGET_EXCEEDED,
        reason="verification_budget_exhausted",
    )
    work_digest = object_digest(asdict(unsafe_work))
    evidence.update(
        {
            "worker_quiescence_digest": work_digest,
            "work_disposition_digest": work_digest,
            "mutation_revocation_digest": work_digest,
        }
    )

    with pytest.raises(TransitionDeniedError, match="worker|mutation capability"):
        cp.transition(
            LifecycleState.BUDGET_EXCEEDED,
            context(usage=exhausted, work=unsafe_work, evidence=evidence),
            reason="verification_budget_exhausted",
        )


def test_pr_ready_resume_revalidates_the_persisted_review_inputs(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.PR_READY)
    reviewed_commit = "a" * 40
    reviewed_tree = object_digest("reviewed-tree")
    review_evidence = object_digest("review-evidence")
    review_digest = object_digest("formal-review")
    cp._append(
        kind="REVIEW_BINDING_ADMITTED",
        outcome="RECORDED",
        source=cp.state,
        target=cp.state,
        reason="formal_review_clear",
        actor="codex",
        evidence_refs={
            "subject_digest": SHA,
            "reviewed_commit_sha": reviewed_commit,
            "prospective_tree_digest": reviewed_tree,
            "verification_bundle_digest": review_evidence,
            "review_digest": review_digest,
        },
        observed_at="2026-08-02T00:01:00Z",
    )
    stop_evidence = evidence_for(
        LifecycleState.PR_READY,
        LifecycleState.BLOCKED,
        reason="merge_protection_incident",
    )
    bind_work_evidence(stop_evidence, WorkStatus())
    cp.transition(
        LifecycleState.BLOCKED,
        context(evidence=stop_evidence),
        reason="merge_protection_incident",
    )

    with pytest.raises(TransitionDeniedError, match="unchanged|review inputs|observation"):
        cp.resume(
            context(
                evidence={
                    "subject_digest": SHA,
                    "incident_closure_digest": SHA,
                    "restored_capability_digest": OTHER_SHA,
                    "unchanged_inputs_digest": OTHER_SHA,
                    "reviewed_commit_sha": reviewed_commit,
                    "prospective_tree_digest": object_digest("changed-tree"),
                    "verification_bundle_digest": review_evidence,
                    "review_digest": review_digest,
                }
            )
        )

    review_inputs = {
        "reviewed_commit_sha": reviewed_commit,
        "prospective_tree_digest": reviewed_tree,
        "verification_bundle_digest": review_evidence,
        "review_digest": review_digest,
    }
    resume_evidence = {
        "subject_digest": SHA,
        "incident_closure_digest": SHA,
        "restored_capability_digest": OTHER_SHA,
        "unchanged_inputs_digest": object_digest(review_inputs),
        **review_inputs,
    }
    resume_context = context(usage=cp.budget_usage, evidence=resume_evidence)
    bind_repository_observation(resume_context.evidence)
    assert cp._trusted_repository_observation_valid(resume_context, review_inputs)
    resumed = cp.resume(resume_context)
    assert resumed.target is LifecycleState.PR_READY


def test_mutation_result_requires_authenticated_exact_attempt_adapter_evidence(
    tmp_path: Path,
) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.PR_MERGED)
    attempt = MutationAttempt(
        attempt_id="adapter-proof-attempt",
        idempotency_key="adapter:run-65:1",
        subject_digest=SHA,
        action="deploy_staging",
        step_plan_digest=OTHER_SHA,
        status="PLANNED",
    )
    prejournal(cp, attempt)

    with pytest.raises(TransitionDeniedError, match="adapter"):
        cp.record_mutation_result(attempt, status="SUCCEEDED", result_digest=SHA)


def test_creation_recovers_the_exact_metadata_only_crash_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = LifecycleControlPlane._append_locked
    calls = 0

    def crash_once(self: LifecycleControlPlane, **kwargs: object) -> lifecycle.LifecycleEvent:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("simulated crash before the first durable event")
        return original(self, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(LifecycleControlPlane, "_append_locked", crash_once)
    policy, _ = budgets()
    with pytest.raises(RuntimeError, match="simulated crash"):
        LifecycleControlPlane.create(
            tmp_path,
            run_id="recoverable-run",
            subject_digest=SHA,
            initial_state=LifecycleState.CONTRACT_RECEIVED,
            budget_policy=policy,
            lifecycle_policy=PHASE_ZERO_POLICY,
        )

    recovered = LifecycleControlPlane.create(
        tmp_path,
        run_id="recoverable-run",
        subject_digest=SHA,
        initial_state=LifecycleState.CONTRACT_RECEIVED,
        budget_policy=policy,
        lifecycle_policy=PHASE_ZERO_POLICY,
    )
    assert recovered.run_id == "recoverable-run"
    assert LifecycleControlPlane.load(tmp_path).events == recovered.events


def test_creation_retry_accepts_authenticated_legacy_metadata_at_historical_default(
    tmp_path: Path,
) -> None:
    policy, _ = budgets()
    LifecycleControlPlane.create(
        tmp_path,
        run_id="legacy-run",
        subject_digest=SHA,
        initial_state=LifecycleState.CONTRACT_RECEIVED,
        budget_policy=policy,
    )
    metadata_path = tmp_path / "lifecycle-metadata.json"
    metadata = json.loads(metadata_path.read_text())
    metadata.pop("retention_days")
    metadata_path.write_text(json.dumps(metadata, sort_keys=True, separators=(",", ":")))

    ledger_path = tmp_path / "lifecycle-events.jsonl"
    initial = json.loads(ledger_path.read_text())
    initial["evidence_refs"]["metadata_digest"] = object_digest(metadata)
    initial["evidence_digest"] = object_digest(initial["evidence_refs"])
    body = {key: value for key, value in initial.items() if key != "event_digest"}
    initial["event_digest"] = object_digest(body)
    ledger_path.write_text(json.dumps(initial, sort_keys=True, separators=(",", ":")) + "\n")

    with pytest.raises(ValueError, match="different metadata"):
        LifecycleControlPlane.create(
            tmp_path,
            run_id="legacy-run",
            subject_digest=SHA,
            initial_state=LifecycleState.CONTRACT_RECEIVED,
            budget_policy=policy,
            retention_days=365,
        )

    recovered = LifecycleControlPlane.create(
        tmp_path,
        run_id="legacy-run",
        subject_digest=SHA,
        initial_state=LifecycleState.CONTRACT_RECEIVED,
        budget_policy=policy,
        retention_days=30,
    )

    assert recovered.run_id == "legacy-run"
    assert recovered.state is LifecycleState.CONTRACT_RECEIVED


def test_creation_retry_persists_legacy_metadata_before_first_event(tmp_path: Path) -> None:
    policy, _ = budgets()
    LifecycleControlPlane.create(
        tmp_path,
        run_id="legacy-interrupted-run",
        subject_digest=SHA,
        initial_state=LifecycleState.CONTRACT_RECEIVED,
        budget_policy=policy,
    )
    metadata_path = tmp_path / "lifecycle-metadata.json"
    metadata = json.loads(metadata_path.read_text())
    metadata.pop("retention_days")
    metadata_path.write_text(json.dumps(metadata, sort_keys=True, separators=(",", ":")))
    (tmp_path / "lifecycle-events.jsonl").unlink()

    recovered = LifecycleControlPlane.create(
        tmp_path,
        run_id="legacy-interrupted-run",
        subject_digest=SHA,
        initial_state=LifecycleState.CONTRACT_RECEIVED,
        budget_policy=policy,
        retention_days=30,
    )

    assert json.loads(metadata_path.read_text())["retention_days"] == 30
    assert LifecycleControlPlane.load(tmp_path).events == recovered.events


def test_creation_retry_preserves_an_expired_completed_lifecycle_run(tmp_path: Path) -> None:
    run_dir = tmp_path / "requested-run"
    existing = control_plane(run_dir, state=LifecycleState.COMPLETED)
    old = datetime(2020, 1, 1, tzinfo=UTC).timestamp()
    os.utime(existing.ledger_path, (old, old))
    policy, _ = budgets()

    recovered = LifecycleControlPlane.create(
        run_dir,
        run_id="run-65",
        subject_digest=SHA,
        initial_state=LifecycleState.CONTRACT_RECEIVED,
        budget_policy=policy,
        lifecycle_policy=PHASE_ZERO_POLICY,
        trust_policy=TRUST_POLICY,
        evidence_verifier=verify_external_proof,
        retention_days=30,
        trusted_clock=lambda: datetime(2030, 1, 31, tzinfo=UTC),
    )

    assert recovered.state is LifecycleState.COMPLETED
    assert existing.ledger_path.exists()


def test_budget_policy_limits_cannot_be_mutated_without_admission() -> None:
    policy, _ = budgets()

    with pytest.raises(TypeError):
        policy.limits["tokens"] = 1_000_000  # type: ignore[index]


def test_persisted_event_evidence_is_immutable_in_memory(tmp_path: Path) -> None:
    cp = control_plane(tmp_path)
    event = cp.record_observation(
        source="live-observer",
        subject_digest=SHA,
        payload_digest=OTHER_SHA,
        signature=external_proof(
            "live-observer",
            SHA,
            {
                "source": "live-observer",
                "subject_digest": SHA,
                "payload_digest": OTHER_SHA,
                "observed_at": "2026-08-02T00:02:00Z",
            },
        ),
        observed_at="2026-08-02T00:02:00Z",
    )

    with pytest.raises(TypeError):
        event.evidence_refs["payload_digest"] = SHA  # type: ignore[index]


def test_authoritative_runtime_state_cannot_be_mutated_outside_events(tmp_path: Path) -> None:
    cp = control_plane(tmp_path)

    with pytest.raises(AttributeError):
        cp.state = LifecycleState.COMPLETED  # type: ignore[misc]
    with pytest.raises(AttributeError):
        cp.events = ()  # type: ignore[misc]
    with pytest.raises(TypeError):
        cp.budget_usage.counters["tokens"] = 1_000_000  # type: ignore[index]


def test_authority_digest_cannot_be_reused_with_forged_current_fields(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.DRAFT_PR_OPEN)
    evidence = evidence_for(
        LifecycleState.DRAFT_PR_OPEN,
        LifecycleState.IMPLEMENTATION_IN_PROGRESS,
        reason="begin_work",
    )
    valid = context(evidence=evidence)
    forged = replace(valid.authority, contract_version="forged-contract-v2")

    with pytest.raises(TransitionDeniedError, match="authority"):
        cp.transition(
            LifecycleState.IMPLEMENTATION_IN_PROGRESS,
            replace(valid, authority=forged),
            reason="begin_work",
        )


def test_adapter_result_rejects_self_asserted_untrusted_authority(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.PR_MERGED)
    attempt = MutationAttempt(
        attempt_id="untrusted-adapter-attempt",
        idempotency_key="adapter:run-65:untrusted",
        subject_digest=SHA,
        action="deploy_staging",
        step_plan_digest=OTHER_SHA,
        status="PLANNED",
    )
    prejournal(cp, attempt)
    fabricated = adapter_result_evidence(attempt, status="SUCCEEDED", result_digest=SHA)
    fabricated = replace(
        fabricated,
        authentication_evidence_digest=object_digest(
            {
                "adapter_id": fabricated.adapter_id,
                "role": fabricated.role,
                "authenticated": fabricated.authenticated,
                "capabilities": sorted(fabricated.capabilities),
                "subject_digest": fabricated.subject_digest,
                "authority_digest": fabricated.authority_digest,
                "attempt_id": fabricated.attempt_id,
                "idempotency_key": fabricated.idempotency_key,
                "action": fabricated.action,
                "step_plan_digest": fabricated.step_plan_digest,
                "status": fabricated.status,
                "result_digest": fabricated.result_digest,
            }
        ),
    )

    with pytest.raises(TransitionDeniedError, match="trusted|adapter authority"):
        cp.record_mutation_result(
            attempt,
            status="SUCCEEDED",
            result_digest=SHA,
            adapter_evidence=fabricated,
        )


def test_merge_rejects_attempt_not_bound_to_reviewed_queue_subject(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.PR_READY)
    reviewed_commit = "a" * 40
    reviewed_tree = object_digest("reviewed-tree")
    review_bundle = object_digest("review-bundle")
    review_digest = object_digest("formal-review")
    cp._append(
        kind="REVIEW_BINDING_ADMITTED",
        outcome="RECORDED",
        source=cp.state,
        target=cp.state,
        reason="formal_review_clear",
        actor="codex",
        evidence_refs={
            "subject_digest": SHA,
            "reviewed_commit_sha": reviewed_commit,
            "prospective_tree_digest": reviewed_tree,
            "verification_bundle_digest": review_bundle,
            "review_digest": review_digest,
        },
        observed_at="2026-08-02T00:01:00Z",
    )
    attempt = MutationAttempt(
        attempt_id="merge-wrong-subject",
        idempotency_key="merge:run-65:wrong-subject",
        subject_digest=SHA,
        action="enqueue_merge",
        step_plan_digest=object_digest("different queue subject"),
        status="PLANNED",
    )
    prejournal(cp, attempt)
    evidence = evidence_for(
        LifecycleState.PR_READY,
        LifecycleState.PR_MERGED,
        reason="native_merge_linearized",
    )
    evidence.update(
        {
            "queue_subject_digest": SHA,
            "head_commit_sha": reviewed_commit,
            "head_digest": object_digest(reviewed_commit),
            "prospective_tree_digest": reviewed_tree,
            "verification_bundle_digest": review_bundle,
            "formal_review_digest": review_digest,
        }
    )
    merge_output = {
        "head_commit_sha": reviewed_commit,
        "merge_commit_sha": "b" * 40,
        "merge_tree_digest": reviewed_tree,
        "merge_method_digest": object_digest("protected-native-merge"),
        "merge_actor_digest": object_digest("github-merge-queue"),
    }
    merge_result_digest = object_digest(merge_output)
    evidence.update(
        merge_output,
        merge_result_digest=merge_result_digest,
        merge_attempt_digest=object_digest(asdict(attempt)),
    )
    record_result(cp, attempt, status="SUCCEEDED", result_digest=merge_result_digest)

    with pytest.raises(TransitionDeniedError, match="mutation.*subject|step plan"):
        cp.transition(
            LifecycleState.PR_MERGED,
            context(evidence=evidence, mutation=attempt),
            reason="native_merge_linearized",
        )


def test_canary_rejects_attempt_not_bound_to_rollout_subject(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.STAGING_DEPLOYED)
    attempt = MutationAttempt(
        attempt_id="canary-wrong-artifact",
        idempotency_key="canary:run-65:wrong-artifact",
        subject_digest=SHA,
        action="deploy_canary",
        step_plan_digest=object_digest("artifact-a"),
        status="PLANNED",
    )
    prejournal(cp, attempt)
    record_result(cp, attempt, status="SUCCEEDED", result_digest=SHA)
    evidence = evidence_for(
        LifecycleState.STAGING_DEPLOYED,
        LifecycleState.CANARY_DEPLOYED,
        reason="canary_admitted",
    )
    evidence["subject_digest"] = SHA
    evidence["canary_attempt_digest"] = object_digest(asdict(attempt))
    evidence["canary_result_digest"] = SHA
    evidence["canary_status_digest"] = object_digest(
        {
            "canary_id_digest": evidence["canary_id_digest"],
            "deployment_attempt_digest": evidence["canary_attempt_digest"],
            "deployment_result_digest": SHA,
            "subject_digest": SHA,
            "status": "ACTIVE",
        }
    )

    with pytest.raises(TransitionDeniedError, match="mutation.*subject|step plan"):
        cp.transition(
            LifecycleState.CANARY_DEPLOYED,
            context(
                evidence=evidence,
                mutation=attempt,
                rollout=RolloutStatus(staging="ACTIVE", canary="ACTIVE"),
            ),
            reason="canary_admitted",
        )


def test_pr_ready_resume_requires_fresh_trusted_repository_observation(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.PR_READY)
    review_inputs = {
        "reviewed_commit_sha": "a" * 40,
        "prospective_tree_digest": object_digest("tree"),
        "verification_bundle_digest": object_digest("bundle"),
        "review_digest": object_digest("review"),
    }
    cp._append(
        kind="REVIEW_BINDING_ADMITTED",
        outcome="RECORDED",
        source=cp.state,
        target=cp.state,
        reason="formal_review_clear",
        actor="codex",
        evidence_refs={"subject_digest": SHA, **review_inputs},
        observed_at="2026-08-02T00:01:00Z",
    )
    stop_evidence = evidence_for(
        LifecycleState.PR_READY,
        LifecycleState.BLOCKED,
        reason="merge_protection_incident",
    )
    bind_work_evidence(stop_evidence, WorkStatus())
    cp.transition(
        LifecycleState.BLOCKED,
        context(evidence=stop_evidence),
        reason="merge_protection_incident",
    )

    with pytest.raises(TransitionDeniedError, match="repository observation|fresh.*observation"):
        cp.resume(
            context(
                evidence={
                    "subject_digest": SHA,
                    "incident_closure_digest": SHA,
                    "restored_capability_digest": OTHER_SHA,
                    "unchanged_inputs_digest": object_digest(review_inputs),
                    **review_inputs,
                }
            )
        )


def test_budget_policy_cannot_be_replaced_outside_admission(tmp_path: Path) -> None:
    cp = control_plane(tmp_path)
    unauthorized = replace(
        cp.budget_policy,
        version="budget-v999",
        limits={name: value * 100 for name, value in cp.budget_policy.limits.items()},
    )

    with pytest.raises(AttributeError):
        cp.budget_policy = unauthorized  # type: ignore[misc]


def test_budget_stop_rejects_self_asserted_quiescence_and_revocation(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.VERIFICATION_FAILED)
    _, exhausted = budgets(tokens=101)
    evidence = evidence_for(
        LifecycleState.VERIFICATION_FAILED,
        LifecycleState.BUDGET_EXCEEDED,
        reason="verification_budget_exhausted",
    )
    bind_work_evidence(evidence, WorkStatus())
    evidence["work_control_authentication_evidence_digest"] = object_digest(
        {
            "controller_id": evidence["work_controller_id"],
            "authority_digest": evidence["work_controller_authority_digest"],
            "subject_digest": SHA,
            "quiescence_digest": evidence["worker_quiescence_digest"],
            "revocation_digest": evidence["mutation_revocation_digest"],
            "observed_at": evidence["work_control_observed_at"],
        }
    )

    with pytest.raises(TransitionDeniedError, match="trusted|quiescence|revocation"):
        cp.transition(
            LifecycleState.BUDGET_EXCEEDED,
            context(usage=exhausted, evidence=evidence),
            reason="verification_budget_exhausted",
        )


def test_lifecycle_identity_and_authoritative_usage_are_not_caller_replaceable(
    tmp_path: Path,
) -> None:
    cp = control_plane(tmp_path)

    with pytest.raises(AttributeError):
        cp.subject_digest = OTHER_SHA  # type: ignore[misc]
    with pytest.raises(AttributeError):
        cp.budget_usage = BudgetUsage()  # type: ignore[misc]


def test_prejournal_rejects_an_authorization_not_bound_to_current_state(
    tmp_path: Path,
) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.PR_MERGED)
    attempt = MutationAttempt(
        attempt_id="authority-fence-attempt",
        idempotency_key="stage:run-65:authority-fence",
        subject_digest=SHA,
        action="deploy_staging",
        step_plan_digest=OTHER_SHA,
        status="PLANNED",
    )
    stale = replace(mutation_authorization(cp, attempt), source_state=LifecycleState.PR_READY)

    with pytest.raises(TransitionDeniedError, match="current external lifecycle authority"):
        cp.prejournal_mutation(attempt, authorization=stale)


def test_prejournal_rejects_a_stale_lifecycle_head_before_adapter_release(
    tmp_path: Path,
) -> None:
    current = control_plane(tmp_path, state=LifecycleState.PR_MERGED)
    stale = LifecycleControlPlane.load(tmp_path, evidence_verifier=verify_external_proof)
    current._append(
        kind="OBSERVATION",
        outcome="RECORDED",
        source=LifecycleState.PR_MERGED,
        target=LifecycleState.PR_MERGED,
        reason="new_observation",
        actor="fixture",
        evidence_refs={"subject_digest": SHA},
        observed_at="2026-08-02T00:02:00Z",
    )
    attempt = MutationAttempt(
        attempt_id="stale-release-attempt",
        idempotency_key="stage:run-65:stale-release",
        subject_digest=SHA,
        action="deploy_staging",
        step_plan_digest=OTHER_SHA,
        status="PLANNED",
    )

    with pytest.raises(TransitionDeniedError, match="reload before mutation release"):
        stale.prejournal_mutation(attempt, authorization=mutation_authorization(stale, attempt))


def test_budget_stop_rejects_a_self_asserted_meter_snapshot(tmp_path: Path) -> None:
    cp = control_plane(tmp_path, state=LifecycleState.IMPLEMENTATION_IN_PROGRESS)
    _, exhausted = budgets(tokens=101)
    required = evidence_for(
        LifecycleState.IMPLEMENTATION_IN_PROGRESS,
        LifecycleState.BUDGET_EXCEEDED,
        reason="delivery_budget_exhausted",
    )
    stopped = WorkStatus(partial_output_disposition="frozen-unverified-non-admissible")
    bind_work_evidence(required, stopped)
    valid = context(usage=exhausted, work=stopped, evidence=required)
    forged = dict(valid.evidence)
    forged["budget_meter_authentication_evidence_digest"] = object_digest("self-asserted")

    with pytest.raises(TransitionDeniedError, match="trusted complete budget telemetry"):
        cp.transition(
            LifecycleState.BUDGET_EXCEEDED,
            replace(valid, evidence=forged),
            reason="delivery_budget_exhausted",
        )


def test_production_mutation_subject_binds_the_authority_fence() -> None:
    baseline = dict.fromkeys(lifecycle._MUTATION_SUBJECT_FIELDS["deploy_production"], SHA)
    changed = dict(baseline)
    changed["authority_fence_digest"] = OTHER_SHA

    assert mutation_subject_digest("deploy_production", baseline) != mutation_subject_digest(
        "deploy_production", changed
    )
