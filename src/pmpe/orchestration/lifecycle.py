"""Versioned, fail-closed lifecycle control plane.

The module intentionally separates proposals and observations from authoritative
state transitions.  Callers provide digest-bound evidence; this control plane
validates the applicable policy rule and appends the only authoritative event.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any, NoReturn

from pmpe.domain.serialize import atomic_write_json


class TransitionDeniedError(RuntimeError):
    """A proposed lifecycle transition failed closed."""


class LifecycleState(StrEnum):
    CONTRACT_RECEIVED = "CONTRACT_RECEIVED"
    CONTRACT_INVALID = "CONTRACT_INVALID"
    PRODUCT_INPUT_REQUIRED = "PRODUCT_INPUT_REQUIRED"
    CONTRACT_APPROVED = "CONTRACT_APPROVED"
    REPOSITORY_ANALYSED = "REPOSITORY_ANALYSED"
    ARCHITECTURE_PROPOSED = "ARCHITECTURE_PROPOSED"
    ARCHITECTURE_APPROVED = "ARCHITECTURE_APPROVED"
    TEST_PLAN_CREATED = "TEST_PLAN_CREATED"
    TEST_PLAN_VALIDATED = "TEST_PLAN_VALIDATED"
    IMPLEMENTATION_PLANNED = "IMPLEMENTATION_PLANNED"
    DRAFT_PR_OPEN = "DRAFT_PR_OPEN"
    IMPLEMENTATION_IN_PROGRESS = "IMPLEMENTATION_IN_PROGRESS"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    REPAIR_IN_PROGRESS = "REPAIR_IN_PROGRESS"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    REVIEW_FAILED = "REVIEW_FAILED"
    PR_READY = "PR_READY"
    PR_MERGED = "PR_MERGED"
    STAGING_DEPLOYED = "STAGING_DEPLOYED"
    STAGING_FAILED = "STAGING_FAILED"
    CANARY_DEPLOYED = "CANARY_DEPLOYED"
    CANARY_FAILED = "CANARY_FAILED"
    PRODUCTION_APPROVAL_REQUIRED = "PRODUCTION_APPROVAL_REQUIRED"
    PRODUCTION_DEPLOYED = "PRODUCTION_DEPLOYED"
    LIVE_VERIFICATION_FAILED = "LIVE_VERIFICATION_FAILED"
    ROLLBACK_IN_PROGRESS = "ROLLBACK_IN_PROGRESS"
    ROLLED_BACK = "ROLLED_BACK"
    BLOCKED = "BLOCKED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    COMPLETED = "COMPLETED"


_BUDGET_DIMENSIONS = frozenset(
    {
        "tokens",
        "credits",
        "elapsed_seconds",
        "external_compute_seconds",
        "spend_microunits",
    }
)


@dataclass(frozen=True)
class AuthoritySnapshot:
    contract_version: str
    publisher_version: str
    contract_active: bool
    publisher_active: bool
    observed_at: str
    digest: str

    @property
    def current(self) -> bool:
        return bool(
            self.contract_active
            and self.publisher_active
            and self.contract_version
            and self.publisher_version
            and self.observed_at
            and self.digest
        )


@dataclass(frozen=True)
class BudgetPolicy:
    version: str
    limits: dict[str, int]
    repair_attempts_per_finding: int
    repair_attempts_per_stage: int
    reserved_safety_units: int
    approved_by: str

    def __post_init__(self) -> None:
        if not self.version or not self.approved_by:
            raise ValueError("budget policy must be versioned and approved")
        if set(self.limits) != _BUDGET_DIMENSIONS:
            raise ValueError("every delivery budget dimension must be configured")
        if any(value <= 0 for value in self.limits.values()):
            raise ValueError("budget limits must be positive")
        if self.repair_attempts_per_finding <= 0 or self.repair_attempts_per_stage <= 0:
            raise ValueError("repair budgets must be positive")
        if self.reserved_safety_units <= 0:
            raise ValueError("reserved safety budget must be positive")


@dataclass(frozen=True)
class BudgetUsage:
    counters: dict[str, int] = field(default_factory=dict)
    repair_attempts_by_finding: dict[str, int] = field(default_factory=dict)
    repair_attempts_by_stage: dict[str, int] = field(default_factory=dict)
    safety_units_used: int = 0

    def __post_init__(self) -> None:
        values = (
            *self.counters.values(),
            *self.repair_attempts_by_finding.values(),
            *self.repair_attempts_by_stage.values(),
            self.safety_units_used,
        )
        if any(value < 0 for value in values):
            raise ValueError("budget usage counters cannot be negative")

    def exhausted_dimensions(self, policy: BudgetPolicy) -> tuple[str, ...]:
        return tuple(
            sorted(
                name for name, limit in policy.limits.items() if self.counters.get(name, 0) >= limit
            )
        )

    def safety_available(self, policy: BudgetPolicy) -> bool:
        return self.safety_units_used < policy.reserved_safety_units


@dataclass(frozen=True)
class RolloutStatus:
    staging: str = "NONE"
    canary: str = "NONE"
    changed_production: str = "NONE"

    def __post_init__(self) -> None:
        admitted = {"NONE", "ACTIVE", "UNKNOWN", "REMOVED"}
        if {self.staging, self.canary, self.changed_production} - admitted:
            raise ValueError("rollout status is not admitted")

    @property
    def has_exposure(self) -> bool:
        return self.canary in {"ACTIVE", "UNKNOWN"} or self.changed_production in {
            "ACTIVE",
            "UNKNOWN",
        }

    @property
    def has_resources(self) -> bool:
        return self.staging in {"ACTIVE", "UNKNOWN"} or self.has_exposure


@dataclass(frozen=True)
class WorkStatus:
    worker_leases_active: int = 0
    workers_stopped: bool = True
    partial_output_disposition: str = "none"

    def __post_init__(self) -> None:
        if self.worker_leases_active < 0:
            raise ValueError("worker lease count cannot be negative")


@dataclass(frozen=True)
class Approval:
    approval_id: str
    actor: str
    subject_digest: str
    kind: str
    eligible: bool
    active: bool


@dataclass(frozen=True)
class FindingSignal:
    finding_id: str
    source: str
    exact_subject_digest: str
    severity: str
    credible: bool
    blocking: bool
    reviewer_eligible: bool


@dataclass(frozen=True)
class MutationAttempt:
    attempt_id: str
    idempotency_key: str
    subject_digest: str
    action: str
    step_plan_digest: str
    status: str
    steps: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not all(
            (
                self.attempt_id,
                self.idempotency_key,
                self.subject_digest,
                self.action,
                self.step_plan_digest,
            )
        ):
            raise ValueError("mutation attempt metadata is incomplete")
        if self.status != "PLANNED":
            raise ValueError("a mutation attempt must be pre-journaled as PLANNED")


@dataclass(frozen=True)
class MutationResult:
    attempt_id: str
    idempotency_key: str
    status: str
    result_digest: str | None

    @property
    def successful(self) -> bool:
        return self.status == "SUCCEEDED" and self.result_digest is not None


@dataclass(frozen=True)
class TransitionContext:
    actor: str
    permissions: frozenset[str]
    evidence: dict[str, str]
    authority: AuthoritySnapshot
    budget_usage: BudgetUsage
    rollout: RolloutStatus
    work: WorkStatus
    approvals: tuple[Approval, ...] = ()
    finding: FindingSignal | None = None
    mutation: MutationAttempt | None = None
    resume_state: LifecycleState | None = None
    observed_at: str = ""


@dataclass(frozen=True)
class TransitionRule:
    source: LifecycleState
    target: LifecycleState
    reason: str
    required_evidence: tuple[str, ...]
    guards: frozenset[str] = frozenset()
    permission: str = "lifecycle.transition"
    mutation_action: str | None = None


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40,64}$")


def _malformed_evidence(evidence: dict[str, str], names: tuple[str, ...]) -> tuple[str, ...]:
    malformed: list[str] = []
    for name in names:
        value = evidence.get(name, "")
        if name == "release_sha":
            if not _GIT_SHA.fullmatch(value):
                malformed.append(name)
        elif name.endswith("_digest") and not _SHA256.fullmatch(value):
            malformed.append(name)
    return tuple(sorted(malformed))


class LifecyclePolicy:
    def __init__(self, version: str, rules: tuple[TransitionRule, ...]) -> None:
        self.version = version
        self.rules = rules
        keys = {(rule.source, rule.target, rule.reason) for rule in rules}
        if len(keys) != len(rules):
            raise ValueError("lifecycle policy contains a duplicate rule")
        payload = {
            "version": version,
            "rules": [
                {
                    "source": rule.source.value,
                    "target": rule.target.value,
                    "reason": rule.reason,
                    "required_evidence": rule.required_evidence,
                    "guards": sorted(rule.guards),
                    "permission": rule.permission,
                    "mutation_action": rule.mutation_action,
                }
                for rule in rules
            ],
        }
        self.digest = _digest(payload)

    def rule(
        self, source: LifecycleState, target: LifecycleState, *, reason: str
    ) -> TransitionRule:
        matches = [
            rule
            for rule in self.rules
            if rule.source is source and rule.target is target and rule.reason == reason
        ]
        if len(matches) != 1:
            raise TransitionDeniedError(
                f"illegal transition {source.value} -> {target.value} ({reason})"
            )
        return matches[0]

    def rules_from(self, state: LifecycleState) -> tuple[TransitionRule, ...]:
        return tuple(rule for rule in self.rules if rule.source is state)


def _r(
    source: LifecycleState,
    target: LifecycleState,
    reason: str,
    evidence: tuple[str, ...] = ("subject_digest", "evidence_bundle_digest"),
    *guards: str,
    mutation: str | None = None,
) -> TransitionRule:
    return TransitionRule(
        source,
        target,
        reason,
        evidence,
        frozenset(guards),
        mutation_action=mutation,
    )


S = LifecycleState
_FORWARD = ("authority", "budget")
_STOP = ("safe_stop",)
_MUTATION = ("authority", "budget", "mutation")
_SAFETY = ("safety", "mutation")


_RULES: tuple[TransitionRule, ...] = (
    _r(
        S.CONTRACT_RECEIVED,
        S.CONTRACT_INVALID,
        "contract_rejected",
        ("intake_receipt_digest", "diagnostic_digest", "deletion_attestation_digest"),
    ),
    _r(
        S.CONTRACT_INVALID,
        S.CONTRACT_RECEIVED,
        "corrected_contract",
        ("correction_receipt_digest", "lineage_digest", "disposition_digest"),
    ),
    _r(
        S.CONTRACT_RECEIVED,
        S.PRODUCT_INPUT_REQUIRED,
        "product_truth_missing",
        ("intake_receipt_digest", "diagnostic_digest", "input_request_digest"),
        "safe_stop",
    ),
    _r(
        S.PRODUCT_INPUT_REQUIRED,
        S.CONTRACT_RECEIVED,
        "superseding_contract",
        ("correction_receipt_digest", "approval_digest", "work_disposition_digest"),
    ),
    _r(
        S.CONTRACT_RECEIVED,
        S.CONTRACT_APPROVED,
        "contract_admitted",
        ("intake_receipt_digest", "contract_digest", "approval_digest", "admission_digest"),
        *_FORWARD,
    ),
    _r(
        S.CONTRACT_APPROVED,
        S.REPOSITORY_ANALYSED,
        "repository_admitted",
        ("contract_digest", "snapshot_digest", "governance_digest"),
        *_FORWARD,
    ),
    _r(
        S.CONTRACT_APPROVED,
        S.BLOCKED,
        "repository_unavailable",
        ("blocker_digest", "resume_gate_digest"),
        *_STOP,
    ),
    _r(
        S.REPOSITORY_ANALYSED,
        S.ARCHITECTURE_PROPOSED,
        "architecture_compiled",
        ("snapshot_digest", "governance_digest", "architecture_pack_digest"),
        *_FORWARD,
    ),
    _r(
        S.ARCHITECTURE_PROPOSED,
        S.PRODUCT_INPUT_REQUIRED,
        "architecture_input_missing",
        ("architecture_attempt_digest", "input_request_digest"),
        *_STOP,
    ),
    _r(
        S.ARCHITECTURE_PROPOSED,
        S.ARCHITECTURE_APPROVED,
        "architecture_approved",
        ("architecture_pack_digest", "engineering_approval_digest"),
        *_FORWARD,
    ),
    _r(
        S.ARCHITECTURE_APPROVED,
        S.TEST_PLAN_CREATED,
        "test_plan_compiled",
        ("architecture_pack_digest", "test_plan_digest"),
        *_FORWARD,
    ),
    _r(
        S.ARCHITECTURE_APPROVED,
        S.PRODUCT_INPUT_REQUIRED,
        "test_oracle_missing",
        ("compiler_diagnostic_digest", "input_request_digest"),
        *_STOP,
    ),
    _r(
        S.TEST_PLAN_CREATED,
        S.TEST_PLAN_VALIDATED,
        "test_plan_validated",
        ("test_plan_digest", "coverage_matrix_digest", "meaningful_red_plan_digest"),
        *_FORWARD,
    ),
    _r(
        S.TEST_PLAN_CREATED,
        S.PRODUCT_INPUT_REQUIRED,
        "test_oracle_missing",
        ("unmapped_requirements_digest", "input_request_digest"),
        *_STOP,
    ),
    _r(
        S.TEST_PLAN_VALIDATED,
        S.IMPLEMENTATION_PLANNED,
        "implementation_planned",
        ("test_plan_digest", "task_plan_digest", "atomic_scope_digest"),
        *_FORWARD,
    ),
    _r(
        S.IMPLEMENTATION_PLANNED,
        S.DRAFT_PR_OPEN,
        "draft_pr_admitted",
        (
            "governance_attempt_digest",
            "issue_digest",
            "branch_digest",
            "red_commit_digest",
            "draft_pr_digest",
            "governance_observation_digest",
        ),
        "authority",
        "budget",
        "mutation",
        mutation="open_draft_pr",
    ),
    _r(
        S.DRAFT_PR_OPEN,
        S.IMPLEMENTATION_IN_PROGRESS,
        "begin_work",
        ("draft_pr_digest", "meaningful_red_digest", "budget_ledger_digest", "worktree_digest"),
        *_FORWARD,
    ),
    _r(
        S.DRAFT_PR_OPEN,
        S.BUDGET_EXCEEDED,
        "delivery_budget_exhausted",
        (
            "budget_ledger_digest",
            "zero_implementation_digest",
            "worktree_disposition_digest",
            "resume_gate_digest",
        ),
        "budget_stop",
    ),
    _r(
        S.DRAFT_PR_OPEN,
        S.PRODUCT_INPUT_REQUIRED,
        "meaningful_red_needs_product_truth",
        ("meaningful_red_digest", "pre_code_tree_digest", "input_request_digest"),
        "product_input",
    ),
    _r(
        S.IMPLEMENTATION_IN_PROGRESS,
        S.VERIFICATION_FAILED,
        "candidate_ready_for_verification",
        ("candidate_digest", "test_execution_digest"),
        *_FORWARD,
    ),
    _r(
        S.IMPLEMENTATION_IN_PROGRESS,
        S.REVIEW_REQUIRED,
        "verification_passed",
        ("candidate_digest", "verification_bundle_digest"),
        *_FORWARD,
    ),
    _r(
        S.IMPLEMENTATION_IN_PROGRESS,
        S.BUDGET_EXCEEDED,
        "delivery_budget_exhausted",
        (
            "budget_ledger_digest",
            "worker_stop_digest",
            "partial_tree_digest",
            "worktree_disposition_digest",
        ),
        "budget_stop",
    ),
    _r(
        S.IMPLEMENTATION_IN_PROGRESS,
        S.PRODUCT_INPUT_REQUIRED,
        "product_truth_missing",
        ("worker_stop_digest", "partial_tree_digest", "input_request_digest"),
        "product_input",
    ),
    _r(
        S.VERIFICATION_FAILED,
        S.REPAIR_IN_PROGRESS,
        "accepted_finding",
        ("finding_digest", "candidate_digest", "repair_scope_digest"),
        "authority",
        "budget",
        "repair",
    ),
    _r(
        S.VERIFICATION_FAILED,
        S.REVIEW_REQUIRED,
        "verification_rerun_passed",
        ("candidate_digest", "verification_bundle_digest"),
        *_FORWARD,
    ),
    _r(
        S.VERIFICATION_FAILED,
        S.BUDGET_EXCEEDED,
        "verification_budget_exhausted",
        ("budget_ledger_digest", "resume_gate_digest"),
        "budget_stop",
    ),
    _r(
        S.VERIFICATION_FAILED,
        S.PRODUCT_INPUT_REQUIRED,
        "product_truth_missing",
        ("verification_digest", "input_request_digest"),
        "product_input",
    ),
    _r(
        S.VERIFICATION_FAILED,
        S.BLOCKED,
        "verification_infrastructure_missing",
        ("blocker_digest", "safe_state_digest"),
        *_STOP,
    ),
    _r(
        S.REPAIR_IN_PROGRESS,
        S.VERIFICATION_FAILED,
        "repair_candidate_ready",
        ("repair_digest", "candidate_digest"),
        *_FORWARD,
    ),
    _r(
        S.REPAIR_IN_PROGRESS,
        S.REVIEW_REQUIRED,
        "repair_verified",
        ("repair_digest", "verification_bundle_digest"),
        *_FORWARD,
    ),
    _r(
        S.REPAIR_IN_PROGRESS,
        S.BUDGET_EXCEEDED,
        "delivery_budget_exhausted",
        (
            "budget_ledger_digest",
            "worker_stop_digest",
            "partial_tree_digest",
            "worktree_disposition_digest",
        ),
        "budget_stop",
    ),
    _r(
        S.REPAIR_IN_PROGRESS,
        S.PRODUCT_INPUT_REQUIRED,
        "product_truth_missing",
        ("worker_stop_digest", "repair_disposition_digest", "input_request_digest"),
        "product_input",
    ),
    _r(
        S.REVIEW_REQUIRED,
        S.PR_READY,
        "formal_review_clear",
        ("review_digest", "verification_bundle_digest", "prospective_tree_digest"),
        "authority",
        "budget",
        "review_clear",
    ),
    _r(
        S.REVIEW_REQUIRED,
        S.REVIEW_FAILED,
        "blocking_finding",
        ("review_event_digest", "finding_digest", "ready_revocation_digest"),
        "blocking_finding",
    ),
    _r(
        S.REVIEW_REQUIRED,
        S.VERIFICATION_FAILED,
        "check_stale",
        ("check_event_digest", "candidate_digest"),
    ),
    _r(
        S.REVIEW_REQUIRED,
        S.IMPLEMENTATION_IN_PROGRESS,
        "head_changed",
        ("candidate_change_digest", "review_invalidation_digest"),
    ),
    _r(
        S.REVIEW_REQUIRED,
        S.REPOSITORY_ANALYSED,
        "repository_drift",
        ("drift_digest", "work_disposition_digest", "snapshot_digest", "governance_digest"),
        "drift",
    ),
    _r(
        S.REVIEW_FAILED,
        S.REPAIR_IN_PROGRESS,
        "accepted_finding",
        ("finding_digest", "candidate_digest", "repair_scope_digest"),
        "authority",
        "budget",
        "repair",
    ),
    _r(
        S.REVIEW_FAILED,
        S.REVIEW_REQUIRED,
        "finding_rejected_with_evidence",
        ("finding_disposition_digest", "candidate_digest", "verification_bundle_digest"),
        *_FORWARD,
    ),
    _r(
        S.REVIEW_FAILED,
        S.PRODUCT_INPUT_REQUIRED,
        "product_truth_missing",
        ("finding_digest", "input_request_digest", "candidate_disposition_digest"),
        "product_input",
    ),
    _r(
        S.PR_READY,
        S.PR_MERGED,
        "native_merge_linearized",
        (
            "queue_subject_digest",
            "head_digest",
            "base_digest",
            "prospective_tree_digest",
            "required_checks_digest",
            "formal_review_digest",
        ),
        "authority",
        "budget",
        "mutation",
        mutation="enqueue_merge",
    ),
    _r(
        S.PR_READY,
        S.REVIEW_FAILED,
        "blocking_finding",
        ("review_event_digest", "finding_digest", "ready_revocation_digest"),
        "blocking_finding",
    ),
    _r(
        S.PR_READY,
        S.VERIFICATION_FAILED,
        "required_check_invalidated",
        ("check_event_digest", "ready_revocation_digest", "approval_invalidation_digest"),
    ),
    _r(
        S.PR_READY,
        S.IMPLEMENTATION_IN_PROGRESS,
        "head_changed",
        ("head_change_digest", "ready_revocation_digest"),
    ),
    _r(
        S.PR_READY,
        S.REPOSITORY_ANALYSED,
        "repository_drift",
        ("drift_digest", "ready_revocation_digest", "snapshot_digest", "governance_digest"),
        "drift",
    ),
    _r(
        S.PR_READY,
        S.BLOCKED,
        "merge_protection_incident",
        ("incident_digest", "governance_digest"),
        *_STOP,
    ),
    _r(
        S.PR_READY,
        S.PRODUCT_INPUT_REQUIRED,
        "authority_invalidated",
        (
            "authority_event_digest",
            "work_disposition_digest",
            "zero_resource_digest",
            "ready_revocation_attempt_digest",
            "ready_revocation_observation_digest",
        ),
        "product_input",
        "mutation",
        mutation="convert_pr_to_draft",
    ),
    _r(
        S.PR_MERGED,
        S.STAGING_DEPLOYED,
        "staging_admitted",
        ("merge_digest", "artifact_digest", "staging_attempt_digest", "staging_result_digest"),
        *_MUTATION,
        mutation="deploy_staging",
    ),
    _r(
        S.PR_MERGED,
        S.STAGING_FAILED,
        "staging_failed",
        ("staging_attempt_digest", "cleanup_attempt_digest", "zero_resource_digest"),
        "safety",
        "mutation",
        mutation="cleanup_staging",
    ),
    _r(
        S.PR_MERGED,
        S.BLOCKED,
        "staging_infrastructure_missing",
        ("blocker_digest", "zero_resource_digest"),
        *_STOP,
    ),
    _r(
        S.STAGING_DEPLOYED,
        S.CANARY_DEPLOYED,
        "canary_admitted",
        (
            "staging_digest",
            "canary_authorization_digest",
            "canary_attempt_digest",
            "canary_result_digest",
        ),
        *_MUTATION,
        mutation="deploy_canary",
    ),
    _r(
        S.STAGING_DEPLOYED,
        S.STAGING_FAILED,
        "staging_cleanup",
        ("cleanup_attempt_digest", "cleanup_result_digest", "zero_resource_digest"),
        "safety",
        "mutation",
        mutation="cleanup_staging",
    ),
    _r(
        S.STAGING_DEPLOYED,
        S.ROLLBACK_IN_PROGRESS,
        "canary_mutation_indeterminate",
        ("canary_attempt_digest", "rollback_attempt_digest", "resource_status_digest"),
        *_SAFETY,
        mutation="rollback",
    ),
    _r(
        S.STAGING_DEPLOYED,
        S.BUDGET_EXCEEDED,
        "delivery_budget_exhausted",
        (
            "budget_ledger_digest",
            "cleanup_attempt_digest",
            "zero_resource_digest",
            "resume_gate_digest",
        ),
        "budget_stop",
        "mutation",
        mutation="cleanup_staging",
    ),
    _r(
        S.STAGING_DEPLOYED,
        S.BLOCKED,
        "canary_authorization_missing",
        ("cleanup_attempt_digest", "zero_resource_digest", "blocker_digest"),
        "safe_stop",
        "mutation",
        mutation="cleanup_staging",
    ),
    _r(
        S.STAGING_FAILED,
        S.PR_MERGED,
        "fresh_deployment_required",
        ("zero_resource_digest", "no_defect_digest", "resume_gate_digest"),
        *_FORWARD,
    ),
    _r(
        S.STAGING_FAILED,
        S.PRODUCT_INPUT_REQUIRED,
        "product_authority_invalidated",
        ("zero_resource_digest", "input_request_digest"),
        "product_input",
    ),
    _r(
        S.STAGING_FAILED,
        S.REPOSITORY_ANALYSED,
        "candidate_remediation",
        ("zero_resource_digest", "snapshot_digest", "governance_digest"),
    ),
    _r(
        S.STAGING_FAILED,
        S.BLOCKED,
        "infrastructure_unavailable",
        ("zero_resource_digest", "blocker_digest", "original_attempt_digest"),
        "safety_block",
        mutation="cleanup_staging",
    ),
    _r(
        S.CANARY_DEPLOYED,
        S.PRODUCTION_APPROVAL_REQUIRED,
        "canary_window_passed",
        ("canary_digest", "slo_window_digest", "approval_request_digest"),
        *_FORWARD,
    ),
    _r(
        S.CANARY_DEPLOYED,
        S.CANARY_FAILED,
        "canary_failed",
        ("canary_failure_digest", "rollback_attempt_digest"),
        "safety",
        "mutation",
        mutation="rollback",
    ),
    _r(
        S.CANARY_DEPLOYED,
        S.ROLLBACK_IN_PROGRESS,
        "governance_stop",
        ("governance_stop_digest", "rollback_attempt_digest"),
        *_SAFETY,
        mutation="rollback",
    ),
    _r(
        S.CANARY_FAILED,
        S.ROLLBACK_IN_PROGRESS,
        "rollback_started",
        ("canary_failure_digest", "rollback_attempt_digest"),
        *_SAFETY,
        mutation="rollback",
    ),
    _r(
        S.PRODUCTION_APPROVAL_REQUIRED,
        S.PRODUCTION_DEPLOYED,
        "production_admitted",
        (
            "production_approval_digest",
            "authority_fence_digest",
            "production_attempt_digest",
            "production_result_digest",
        ),
        *_MUTATION,
        mutation="deploy_production",
    ),
    _r(
        S.PRODUCTION_APPROVAL_REQUIRED,
        S.CANARY_FAILED,
        "canary_breach",
        ("canary_failure_digest", "rollback_attempt_digest"),
        *_SAFETY,
        mutation="rollback",
    ),
    _r(
        S.PRODUCTION_APPROVAL_REQUIRED,
        S.ROLLBACK_IN_PROGRESS,
        "production_mutation_indeterminate",
        ("production_attempt_digest", "rollback_attempt_digest"),
        *_SAFETY,
        mutation="rollback",
    ),
    _r(
        S.PRODUCTION_APPROVAL_REQUIRED,
        S.STAGING_DEPLOYED,
        "approval_reset_no_defect",
        ("approval_disposition_digest", "canary_teardown_digest", "staging_revalidation_digest"),
        "safety",
        "mutation",
        mutation="teardown_canary",
    ),
    _r(
        S.PRODUCTION_APPROVAL_REQUIRED,
        S.STAGING_FAILED,
        "approval_reset_cleanup",
        (
            "approval_disposition_digest",
            "canary_teardown_digest",
            "staging_cleanup_digest",
            "zero_resource_digest",
        ),
        "safety",
        "mutation",
        mutation="cleanup_staging",
    ),
    _r(
        S.PRODUCTION_DEPLOYED,
        S.COMPLETED,
        "observation_window_passed",
        (
            "release_sha",
            "live_verification_digest",
            "rollback_readiness_digest",
            "observation_window_digest",
            "evidence_bundle_digest",
        ),
        "authority",
        "completion",
    ),
    _r(
        S.PRODUCTION_DEPLOYED,
        S.LIVE_VERIFICATION_FAILED,
        "live_gate_failed",
        ("release_sha", "live_failure_digest", "telemetry_digest"),
    ),
    _r(
        S.PRODUCTION_DEPLOYED,
        S.ROLLBACK_IN_PROGRESS,
        "governance_stop",
        ("governance_stop_digest", "rollback_attempt_digest"),
        *_SAFETY,
        mutation="rollback",
    ),
    _r(
        S.LIVE_VERIFICATION_FAILED,
        S.ROLLBACK_IN_PROGRESS,
        "rollback_started",
        ("live_failure_digest", "rollback_attempt_digest"),
        *_SAFETY,
        mutation="rollback",
    ),
    _r(
        S.ROLLBACK_IN_PROGRESS,
        S.ROLLED_BACK,
        "rollback_verified",
        (
            "rollback_attempt_digest",
            "rollback_result_digest",
            "restoration_verification_digest",
            "incident_digest",
        ),
        "safety",
        "mutation",
        mutation="rollback",
    ),
    _r(
        S.ROLLBACK_IN_PROGRESS,
        S.BLOCKED,
        "rollback_indeterminate",
        (
            "rollback_attempt_digest",
            "incident_digest",
            "resource_status_digest",
            "original_attempt_digest",
        ),
        "safety_block",
        mutation="rollback",
    ),
    _r(
        S.ROLLED_BACK,
        S.STAGING_DEPLOYED,
        "no_defect_readmission",
        ("rollback_bundle_digest", "zero_exposure_digest", "staging_revalidation_digest"),
        *_FORWARD,
    ),
    _r(
        S.ROLLED_BACK,
        S.STAGING_FAILED,
        "staging_cleanup",
        ("rollback_bundle_digest", "cleanup_attempt_digest", "zero_resource_digest"),
        "safety",
        "mutation",
        mutation="cleanup_staging",
    ),
    _r(
        S.ROLLED_BACK,
        S.PRODUCT_INPUT_REQUIRED,
        "product_truth_missing",
        ("rollback_bundle_digest", "zero_resource_digest", "input_request_digest"),
        "product_input",
    ),
    _r(
        S.ROLLED_BACK,
        S.REPOSITORY_ANALYSED,
        "candidate_remediation",
        ("rollback_bundle_digest", "zero_resource_digest", "snapshot_digest", "governance_digest"),
    ),
    _r(
        S.ROLLED_BACK,
        S.BUDGET_EXCEEDED,
        "delivery_budget_exhausted",
        (
            "rollback_bundle_digest",
            "budget_ledger_digest",
            "zero_resource_digest",
            "resume_gate_digest",
        ),
        "budget_stop",
    ),
    _r(
        S.BLOCKED,
        S.ROLLBACK_IN_PROGRESS,
        "resume_safety_rollback",
        ("incident_digest", "original_attempt_digest", "restored_capability_digest"),
        "safety_resume",
        mutation="rollback",
    ),
    _r(
        S.BLOCKED,
        S.STAGING_FAILED,
        "resume_safety_cleanup",
        ("incident_digest", "original_attempt_digest", "restored_capability_digest"),
        "safety_resume",
        mutation="cleanup_staging",
    ),
    _r(
        S.BLOCKED,
        S.CONTRACT_RECEIVED,
        "superseding_contract",
        ("incident_closure_digest", "intake_receipt_digest", "correction_relation_digest"),
        "safe_stop",
    ),
    _r(
        S.BLOCKED,
        S.REPOSITORY_ANALYSED,
        "repository_readmitted",
        ("incident_closure_digest", "snapshot_digest", "governance_digest"),
        "safe_stop",
    ),
    _r(
        S.BUDGET_EXCEEDED,
        S.BLOCKED,
        "extension_unavailable",
        ("budget_ledger_digest", "resume_gate_digest"),
        "safe_stop",
    ),
    _r(
        S.COMPLETED,
        S.LIVE_VERIFICATION_FAILED,
        "completion_evidence_invalidated",
        ("completion_event_digest", "invalidation_digest", "incident_digest"),
        "revoke_completion",
    ),
    _r(
        S.COMPLETED,
        S.BLOCKED,
        "completion_evidence_unavailable",
        ("completion_event_digest", "invalidation_digest", "safe_state_digest"),
        "revoke_completion",
        "safe_stop",
    ),
)


_DRIFT_SOURCES = (
    S.ARCHITECTURE_PROPOSED,
    S.ARCHITECTURE_APPROVED,
    S.TEST_PLAN_CREATED,
    S.TEST_PLAN_VALIDATED,
    S.IMPLEMENTATION_PLANNED,
    S.DRAFT_PR_OPEN,
    S.IMPLEMENTATION_IN_PROGRESS,
    S.VERIFICATION_FAILED,
    S.REPAIR_IN_PROGRESS,
    S.REVIEW_FAILED,
)
_AUTHORITY_SOURCES = (
    S.CONTRACT_APPROVED,
    S.REPOSITORY_ANALYSED,
    S.ARCHITECTURE_PROPOSED,
    S.ARCHITECTURE_APPROVED,
    S.TEST_PLAN_CREATED,
    S.TEST_PLAN_VALIDATED,
    S.IMPLEMENTATION_PLANNED,
    S.DRAFT_PR_OPEN,
    S.IMPLEMENTATION_IN_PROGRESS,
    S.VERIFICATION_FAILED,
    S.REPAIR_IN_PROGRESS,
    S.REVIEW_REQUIRED,
    S.REVIEW_FAILED,
    S.PR_READY,
    S.PR_MERGED,
    S.BUDGET_EXCEEDED,
)

PHASE_ZERO_POLICY = LifecyclePolicy(
    "phase-zero-v1",
    _RULES
    + tuple(
        _r(
            source,
            S.REPOSITORY_ANALYSED,
            "repository_drift",
            ("drift_digest", "work_disposition_digest", "snapshot_digest", "governance_digest"),
            "drift",
        )
        for source in _DRIFT_SOURCES
        if not any(
            rule.source is source
            and rule.target is S.REPOSITORY_ANALYSED
            and rule.reason == "repository_drift"
            for rule in _RULES
        )
    )
    + tuple(
        _r(
            source,
            S.PRODUCT_INPUT_REQUIRED,
            "authority_invalidated",
            ("authority_event_digest", "work_disposition_digest", "zero_resource_digest"),
            "product_input",
        )
        for source in _AUTHORITY_SOURCES
        if not any(
            rule.source is source
            and rule.target is S.PRODUCT_INPUT_REQUIRED
            and rule.reason == "authority_invalidated"
            for rule in _RULES
        )
    ),
)


@dataclass(frozen=True)
class LifecycleEvent:
    sequence: int
    kind: str
    outcome: str
    source: LifecycleState
    target: LifecycleState
    reason: str
    actor: str
    subject_digest: str
    policy_digest: str
    evidence_digest: str
    evidence_refs: dict[str, str]
    budget_usage: dict[str, Any] | None
    observed_at: str
    resume_state: LifecycleState | None
    previous_digest: str
    event_digest: str
    detail: str = ""


@dataclass(frozen=True)
class MigrationResult:
    state: LifecycleState
    source_version: object
    source_stage: str
    digest: str


def migrate_legacy_state(payload: dict[str, object]) -> MigrationResult:
    version = payload.get("version")
    stage = str(payload.get("stage", ""))
    mappings: dict[object, dict[str, LifecycleState]] = {
        2: {
            "assessment": S.REPOSITORY_ANALYSED,
            "architecture": S.ARCHITECTURE_PROPOSED,
            "plan": S.IMPLEMENTATION_PLANNED,
            "implement": S.IMPLEMENTATION_IN_PROGRESS,
            "review": S.REVIEW_REQUIRED,
            "retest": S.VERIFICATION_FAILED,
            "draft_pr": S.DRAFT_PR_OPEN,
            "deploy": S.PR_MERGED,
        },
        3: {
            "contract": S.CONTRACT_APPROVED,
            "assessment": S.REPOSITORY_ANALYSED,
            "architecture": S.ARCHITECTURE_PROPOSED,
            "plan": S.IMPLEMENTATION_PLANNED,
            "implementation": S.IMPLEMENTATION_IN_PROGRESS,
            "review": S.REVIEW_REQUIRED,
            "draft_pr": S.DRAFT_PR_OPEN,
            "deploy": S.PR_MERGED,
            "verify": S.PRODUCTION_DEPLOYED,
        },
    }
    try:
        state = mappings[version][stage]
    except KeyError as exc:
        raise ValueError(f"unsupported legacy state version={version!r} stage={stage!r}") from exc
    body = {"source_version": version, "source_stage": stage, "state": state.value}
    return MigrationResult(state, version, stage, _digest(body))


class LifecycleControlPlane:
    """Append-only lifecycle authority with deterministic replay."""

    _LEDGER_NAME = "lifecycle-events.jsonl"
    _META_NAME = "lifecycle-metadata.json"
    _MUTATIONS_NAME = "lifecycle-mutations.jsonl"
    _LOCK_NAME = "lifecycle.lock"

    def __init__(
        self,
        run_dir: Path,
        *,
        run_id: str,
        subject_digest: str,
        state: LifecycleState,
        budget_policy: BudgetPolicy,
        events: list[LifecycleEvent] | None = None,
    ) -> None:
        self.run_dir = Path(run_dir)
        self.run_id = run_id
        self.subject_digest = subject_digest
        self.state = state
        self.budget_policy = budget_policy
        self.events = events or []
        self.completion_claim_active = False
        self._mutation_keys: dict[str, str] = {}
        self._mutation_attempts: dict[str, MutationAttempt] = {}
        self._mutation_results: dict[str, MutationResult] = {}
        self.budget_usage = BudgetUsage()

    @property
    def ledger_path(self) -> Path:
        return self.run_dir / self._LEDGER_NAME

    @property
    def mutation_path(self) -> Path:
        return self.run_dir / self._MUTATIONS_NAME

    @property
    def lock_path(self) -> Path:
        return self.run_dir / self._LOCK_NAME

    @contextmanager
    def _exclusive_lock(self) -> Iterator[None]:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    @classmethod
    def create(
        cls,
        run_dir: Path,
        *,
        run_id: str,
        subject_digest: str,
        initial_state: LifecycleState,
        budget_policy: BudgetPolicy,
    ) -> LifecycleControlPlane:
        path = Path(run_dir)
        path.mkdir(parents=True, exist_ok=True)
        ledger = path / cls._LEDGER_NAME
        if ledger.exists():
            raise ValueError("lifecycle ledger already exists")
        cp = cls(
            path,
            run_id=run_id,
            subject_digest=subject_digest,
            state=initial_state,
            budget_policy=budget_policy,
        )
        metadata: dict[str, Any] = {
            "run_id": run_id,
            "subject_digest": subject_digest,
            "budget_policy": asdict(budget_policy),
            "budget_policy_digest": _digest(asdict(budget_policy)),
        }
        atomic_write_json(path / cls._META_NAME, metadata)
        cp._append(
            kind="STATE_CREATED",
            outcome="APPLIED",
            source=initial_state,
            target=initial_state,
            reason="create",
            actor="control-plane",
            evidence_refs={"budget_policy_digest": str(metadata["budget_policy_digest"])},
            observed_at="",
        )
        return cp

    @classmethod
    def load(cls, run_dir: Path) -> LifecycleControlPlane:
        path = Path(run_dir)
        raw_events = [
            json.loads(line)
            for line in (path / cls._LEDGER_NAME).read_text().splitlines()
            if line.strip()
        ]
        if not raw_events:
            raise ValueError("lifecycle ledger is empty")
        events: list[LifecycleEvent] = []
        previous = ""
        for raw in raw_events:
            supplied = str(raw.get("event_digest", ""))
            body = {key: value for key, value in raw.items() if key != "event_digest"}
            if raw.get("previous_digest", "") != previous or _digest(body) != supplied:
                raise ValueError("lifecycle event digest chain is invalid")
            event = cls._event_from_dict(raw)
            events.append(event)
            previous = supplied
        metadata = json.loads((path / cls._META_NAME).read_text())
        raw_policy = dict(metadata["budget_policy"])
        if _digest(raw_policy) != metadata.get("budget_policy_digest"):
            raise ValueError("lifecycle budget policy digest is invalid")
        budget_policy = BudgetPolicy(
            version=str(raw_policy["version"]),
            limits={str(key): int(value) for key, value in dict(raw_policy["limits"]).items()},
            repair_attempts_per_finding=int(raw_policy["repair_attempts_per_finding"]),
            repair_attempts_per_stage=int(raw_policy["repair_attempts_per_stage"]),
            reserved_safety_units=int(raw_policy["reserved_safety_units"]),
            approved_by=str(raw_policy["approved_by"]),
        )
        cp = cls(
            path,
            run_id=str(metadata["run_id"]),
            subject_digest=str(metadata["subject_digest"]),
            state=events[0].target,
            budget_policy=budget_policy,
            events=events,
        )
        cp._load_mutations()
        for event in events[1:]:
            if event.outcome == "APPLIED":
                cp.state = event.target
            if event.budget_usage is not None:
                cp.budget_usage = cp._merge_budget_usage(
                    BudgetUsage(**event.budget_usage), reject_lower=True
                )
            if event.kind == "MUTATION_RESULT":
                attempt_id = event.evidence_refs.get("attempt_id", "")
                key = event.evidence_refs.get("idempotency_key", "")
                if attempt_id and key:
                    cp._mutation_results[key] = MutationResult(
                        attempt_id=attempt_id,
                        idempotency_key=key,
                        status=event.detail,
                        result_digest=(
                            event.evidence_refs.get("result_digest")
                            if event.evidence_refs.get("result_digest") != "UNKNOWN"
                            else None
                        ),
                    )
            if event.kind == "COMPLETION_CLAIMED":
                cp.completion_claim_active = True
            elif event.kind == "COMPLETION_REVOKED":
                cp.completion_claim_active = False
        return cp

    def admit_budget_policy(self, policy: BudgetPolicy) -> None:
        if policy.version == self.budget_policy.version:
            raise TransitionDeniedError("budget extension must have a new version")
        if any(policy.limits[name] < limit for name, limit in self.budget_policy.limits.items()):
            raise TransitionDeniedError("budget extension cannot reduce an existing limit")
        if policy.repair_attempts_per_finding < self.budget_policy.repair_attempts_per_finding:
            raise TransitionDeniedError("budget extension cannot reduce the finding repair limit")
        if policy.repair_attempts_per_stage < self.budget_policy.repair_attempts_per_stage:
            raise TransitionDeniedError("budget extension cannot reduce the stage repair limit")
        if policy.reserved_safety_units < self.budget_policy.reserved_safety_units:
            raise TransitionDeniedError("budget extension cannot reduce reserved safety")
        self.budget_policy = policy
        metadata = json.loads((self.run_dir / self._META_NAME).read_text())
        metadata["budget_policy"] = asdict(policy)
        metadata["budget_policy_digest"] = _digest(asdict(policy))
        atomic_write_json(self.run_dir / self._META_NAME, metadata)

    def _merge_budget_usage(self, supplied: BudgetUsage, *, reject_lower: bool) -> BudgetUsage:
        prior = self.budget_usage
        dimensions = set(prior.counters) | set(supplied.counters)
        findings = set(prior.repair_attempts_by_finding) | set(supplied.repair_attempts_by_finding)
        stages = set(prior.repair_attempts_by_stage) | set(supplied.repair_attempts_by_stage)
        regressions = [
            name
            for name in dimensions
            if supplied.counters.get(name, 0) < prior.counters.get(name, 0)
        ]
        regressions.extend(
            f"finding:{name}"
            for name in findings
            if supplied.repair_attempts_by_finding.get(name, 0)
            < prior.repair_attempts_by_finding.get(name, 0)
        )
        regressions.extend(
            f"stage:{name}"
            for name in stages
            if supplied.repair_attempts_by_stage.get(name, 0)
            < prior.repair_attempts_by_stage.get(name, 0)
        )
        if supplied.safety_units_used < prior.safety_units_used:
            regressions.append("reserved_safety_units")
        if reject_lower and regressions:
            raise TransitionDeniedError(
                "budget usage cannot decrease: " + ", ".join(sorted(regressions))
            )
        return BudgetUsage(
            counters={
                name: max(prior.counters.get(name, 0), supplied.counters.get(name, 0))
                for name in dimensions
            },
            repair_attempts_by_finding={
                name: max(
                    prior.repair_attempts_by_finding.get(name, 0),
                    supplied.repair_attempts_by_finding.get(name, 0),
                )
                for name in findings
            },
            repair_attempts_by_stage={
                name: max(
                    prior.repair_attempts_by_stage.get(name, 0),
                    supplied.repair_attempts_by_stage.get(name, 0),
                )
                for name in stages
            },
            safety_units_used=max(prior.safety_units_used, supplied.safety_units_used),
        )

    @staticmethod
    def _event_from_dict(raw: dict[str, Any]) -> LifecycleEvent:
        return LifecycleEvent(
            sequence=int(raw["sequence"]),
            kind=str(raw["kind"]),
            outcome=str(raw["outcome"]),
            source=S(str(raw["source"])),
            target=S(str(raw["target"])),
            reason=str(raw["reason"]),
            actor=str(raw["actor"]),
            subject_digest=str(raw["subject_digest"]),
            policy_digest=str(raw["policy_digest"]),
            evidence_digest=str(raw["evidence_digest"]),
            evidence_refs={
                str(key): str(value) for key, value in dict(raw.get("evidence_refs", {})).items()
            },
            budget_usage=(
                dict(raw["budget_usage"]) if raw.get("budget_usage") is not None else None
            ),
            observed_at=str(raw["observed_at"]),
            resume_state=(S(str(raw["resume_state"])) if raw.get("resume_state") else None),
            previous_digest=str(raw["previous_digest"]),
            event_digest=str(raw["event_digest"]),
            detail=str(raw.get("detail", "")),
        )

    def _append(
        self,
        *,
        kind: str,
        outcome: str,
        source: LifecycleState,
        target: LifecycleState,
        reason: str,
        actor: str,
        evidence_refs: dict[str, str],
        observed_at: str,
        budget_usage: BudgetUsage | None = None,
        resume_state: LifecycleState | None = None,
        detail: str = "",
    ) -> LifecycleEvent:
        with self._exclusive_lock():
            persisted = (
                [
                    json.loads(line)
                    for line in self.ledger_path.read_text().splitlines()
                    if line.strip()
                ]
                if self.ledger_path.exists()
                else []
            )
            expected_previous = self.events[-1].event_digest if self.events else ""
            persisted_previous = str(persisted[-1].get("event_digest", "")) if persisted else ""
            if len(persisted) != len(self.events) or persisted_previous != expected_previous:
                raise TransitionDeniedError(
                    "stale lifecycle writer lost the append compare-and-swap"
                )
            body: dict[str, Any] = {
                "sequence": len(self.events) + 1,
                "kind": kind,
                "outcome": outcome,
                "source": source.value,
                "target": target.value,
                "reason": reason,
                "actor": actor,
                "subject_digest": self.subject_digest,
                "policy_digest": PHASE_ZERO_POLICY.digest,
                "evidence_digest": _digest(evidence_refs),
                "evidence_refs": evidence_refs,
                "budget_usage": asdict(budget_usage) if budget_usage is not None else None,
                "observed_at": observed_at,
                "resume_state": resume_state.value if resume_state else None,
                "previous_digest": expected_previous,
                "detail": detail,
            }
            body["event_digest"] = _digest(body)
            event = self._event_from_dict(body)
            with self.ledger_path.open("a") as stream:
                stream.write(json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        self.events.append(event)
        return event

    def _deny(
        self,
        target: LifecycleState,
        context: TransitionContext,
        reason: str,
        detail: str,
    ) -> NoReturn:
        persisted_usage = self._merge_budget_usage(context.budget_usage, reject_lower=False)
        self._append(
            kind="TRANSITION",
            outcome="DENIED",
            source=self.state,
            target=target,
            reason=reason,
            actor=context.actor,
            evidence_refs=dict(context.evidence),
            observed_at=context.observed_at,
            budget_usage=persisted_usage,
            resume_state=context.resume_state,
            detail=detail,
        )
        raise TransitionDeniedError(detail)

    def transition(
        self, target: LifecycleState, context: TransitionContext, *, reason: str
    ) -> LifecycleEvent:
        source = self.state
        try:
            usage = self._merge_budget_usage(context.budget_usage, reject_lower=True)
        except TransitionDeniedError as exc:
            self._deny(target, context, reason, str(exc))
            raise AssertionError("unreachable") from exc
        if context.rollout.has_exposure and target in {
            S.BLOCKED,
            S.PRODUCT_INPUT_REQUIRED,
            S.BUDGET_EXCEEDED,
        }:
            self._deny(target, context, reason, "active rollout exposure requires rollback")
        try:
            rule = PHASE_ZERO_POLICY.rule(source, target, reason=reason)
        except TransitionDeniedError as exc:
            self._deny(target, context, reason, str(exc))
            raise AssertionError("unreachable") from exc
        if rule.permission not in context.permissions:
            self._deny(target, context, reason, "actor lacks lifecycle transition permission")
        missing = [name for name in rule.required_evidence if not context.evidence.get(name)]
        if missing:
            self._deny(
                target,
                context,
                reason,
                "required evidence is missing: " + ", ".join(sorted(missing)),
            )
        malformed = _malformed_evidence(context.evidence, rule.required_evidence)
        if malformed:
            self._deny(
                target,
                context,
                reason,
                "required evidence is not a canonical digest: " + ", ".join(malformed),
            )
        guards = rule.guards
        if "authority" in guards and not context.authority.current:
            self._deny(target, context, reason, "contract or publisher authority is not current")
        exhausted = usage.exhausted_dimensions(self.budget_policy)
        if "budget" in guards and exhausted:
            self._deny(target, context, reason, "delivery budget is exhausted")
        if "safe_stop" in guards and context.rollout.has_resources:
            self._deny(target, context, reason, "safe stop requires zero rollout-owned resources")
        if "product_input" in guards:
            if context.rollout.has_resources:
                self._deny(target, context, reason, "product input requires cleanup or rollback")
            if context.work.worker_leases_active or not context.work.workers_stopped:
                self._deny(target, context, reason, "product input requires stopped workers")
        if "budget_stop" in guards:
            if not exhausted:
                self._deny(target, context, reason, "budget stop requires proven exhaustion")
            if source in {S.IMPLEMENTATION_IN_PROGRESS, S.REPAIR_IN_PROGRESS}:
                if context.work.worker_leases_active or not context.work.workers_stopped:
                    self._deny(target, context, reason, "worker leases must be quiescent")
                if context.work.partial_output_disposition not in {
                    "frozen-unverified-non-admissible",
                    "disposed-unverified-non-admissible",
                }:
                    self._deny(target, context, reason, "partial work has no safe disposition")
            if context.rollout.has_resources:
                self._deny(target, context, reason, "budget stop requires zero rollout resources")
            safe_resume = {
                S.DRAFT_PR_OPEN: S.DRAFT_PR_OPEN,
                S.IMPLEMENTATION_IN_PROGRESS: S.IMPLEMENTATION_IN_PROGRESS,
                S.VERIFICATION_FAILED: S.VERIFICATION_FAILED,
                S.REPAIR_IN_PROGRESS: S.REPAIR_IN_PROGRESS,
                S.STAGING_DEPLOYED: S.PR_MERGED,
                S.ROLLED_BACK: S.ROLLED_BACK,
            }.get(source)
            if safe_resume is None or context.resume_state is not safe_resume:
                self._deny(
                    target,
                    context,
                    reason,
                    "budget stop resume target is not the interrupted safe gate",
                )
        if "repair" in guards:
            finding = context.finding
            if finding is None or finding.exact_subject_digest != self.subject_digest:
                self._deny(target, context, reason, "repair requires an exact-subject finding")
            finding_attempts = usage.repair_attempts_by_finding.get(finding.finding_id, 0)
            stage_attempts = usage.repair_attempts_by_stage.get(source.value, 0)
            if (
                finding_attempts >= self.budget_policy.repair_attempts_per_finding
                or stage_attempts >= self.budget_policy.repair_attempts_per_stage
            ):
                self._deny(target, context, reason, "repair attempt limit is exhausted")
        if "blocking_finding" in guards:
            finding = context.finding
            if (
                finding is None
                or finding.exact_subject_digest != self.subject_digest
                or not finding.credible
                or not finding.blocking
                or finding.severity.upper() not in {"CRITICAL", "HIGH", "MEDIUM"}
            ):
                self._deny(target, context, reason, "no normalized exact-subject blocker")
        if "review_clear" in guards and not any(
            approval.kind == "FORMAL_REVIEW"
            and approval.eligible
            and approval.active
            and approval.subject_digest == self.subject_digest
            for approval in context.approvals
        ):
            self._deny(target, context, reason, "eligible formal review is required")
        if "mutation" in guards:
            attempt = context.mutation
            if attempt is None or attempt.status != "PLANNED":
                self._deny(target, context, reason, "pre-journaled mutation attempt is required")
            if attempt.subject_digest != self.subject_digest:
                self._deny(target, context, reason, "mutation attempt subject does not match")
            if rule.mutation_action and attempt.action != rule.mutation_action:
                self._deny(target, context, reason, "mutation attempt action does not match")
            if rule.mutation_action == "open_draft_pr" and attempt.steps != (
                "issue",
                "branch",
                "red_commit",
                "draft_pr",
            ):
                self._deny(
                    target,
                    context,
                    reason,
                    "draft PR mutation steps must be issue, branch, red commit, draft PR",
                )
            try:
                self._register_mutation(attempt)
            except TransitionDeniedError as exc:
                self._deny(target, context, reason, str(exc))
            starts_safety_action = target is S.ROLLBACK_IN_PROGRESS
            result = self._mutation_results.get(attempt.idempotency_key)
            if not starts_safety_action and (result is None or not result.successful):
                self._deny(
                    target,
                    context,
                    reason,
                    "a successful exact-attempt mutation result is required",
                )
            if result is not None and result.attempt_id != attempt.attempt_id:
                self._deny(target, context, reason, "mutation result attempt does not match")
        if "safety_block" in guards:
            attempt = context.mutation
            if attempt is None or rule.mutation_action != attempt.action:
                self._deny(target, context, reason, "blocked safety action is not attributable")
            if context.evidence.get("original_attempt_digest") != _digest(asdict(attempt)):
                self._deny(target, context, reason, "blocked safety attempt digest does not match")
            try:
                self._register_mutation(attempt)
            except TransitionDeniedError as exc:
                self._deny(target, context, reason, str(exc))
            expected_resume = {
                "rollback": S.ROLLBACK_IN_PROGRESS,
                "cleanup_staging": S.STAGING_FAILED,
            }[attempt.action]
            if context.resume_state is not expected_resume:
                self._deny(target, context, reason, "blocked safety resume target is invalid")
        if "safety" in guards and not usage.safety_available(self.budget_policy):
            self._deny(target, context, reason, "reserved safety budget is exhausted")
        if "safety_resume" in guards:
            stopped = next(
                (
                    event
                    for event in reversed(self.events)
                    if event.outcome == "APPLIED" and event.target is S.BLOCKED
                ),
                None,
            )
            attempt = context.mutation
            if (
                stopped is None
                or stopped.resume_state is not target
                or context.resume_state is not target
                or attempt is None
                or attempt.action != rule.mutation_action
                or context.evidence.get("original_attempt_digest") != _digest(asdict(attempt))
                or stopped.evidence_refs.get("original_attempt_digest")
                != context.evidence.get("original_attempt_digest")
            ):
                self._deny(
                    target,
                    context,
                    reason,
                    "safety resume is not bound to the original blocked action",
                )
            try:
                self._register_mutation(attempt)
            except TransitionDeniedError as exc:
                self._deny(target, context, reason, str(exc))
        if "completion" in guards and self.completion_claim_active:
            self._deny(target, context, reason, "completion claim is already active")

        kind = "TRANSITION"
        if target is S.COMPLETED:
            kind = "COMPLETION_CLAIMED"
        elif source is S.COMPLETED:
            kind = "COMPLETION_REVOKED"
        if "repair" in guards and context.finding is not None:
            finding_id = context.finding.finding_id
            by_finding = dict(usage.repair_attempts_by_finding)
            by_stage = dict(usage.repair_attempts_by_stage)
            by_finding[finding_id] = by_finding.get(finding_id, 0) + 1
            by_stage[source.value] = by_stage.get(source.value, 0) + 1
            usage = replace(
                usage,
                repair_attempts_by_finding=by_finding,
                repair_attempts_by_stage=by_stage,
            )
        if "safety" in guards or "safety_resume" in guards:
            usage = replace(usage, safety_units_used=usage.safety_units_used + 1)
        event = self._append(
            kind=kind,
            outcome="APPLIED",
            source=source,
            target=target,
            reason=reason,
            actor=context.actor,
            evidence_refs=dict(context.evidence),
            observed_at=context.observed_at,
            budget_usage=usage,
            resume_state=context.resume_state,
        )
        self.state = target
        self.budget_usage = usage
        if kind == "COMPLETION_CLAIMED":
            self.completion_claim_active = True
        elif kind == "COMPLETION_REVOKED":
            self.completion_claim_active = False
        return event

    def _register_mutation(self, attempt: MutationAttempt) -> None:
        with self._exclusive_lock():
            attempts = self._read_mutation_attempts()
            prior = attempts.get(attempt.idempotency_key)
            if prior is not None and prior != attempt:
                raise TransitionDeniedError(
                    "idempotency key is already bound to a different complete mutation plan"
                )
            if prior is None:
                body = asdict(attempt)
                body["record_digest"] = _digest(body)
                with self.mutation_path.open("a") as stream:
                    stream.write(json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
            self._mutation_keys[attempt.idempotency_key] = attempt.attempt_id
            self._mutation_attempts[attempt.idempotency_key] = attempt

    def _read_mutation_attempts(self) -> dict[str, MutationAttempt]:
        attempts: dict[str, MutationAttempt] = {}
        if not self.mutation_path.exists():
            return attempts
        for line in self.mutation_path.read_text().splitlines():
            if not line.strip():
                continue
            raw = json.loads(line)
            supplied = str(raw.pop("record_digest", ""))
            if _digest(raw) != supplied:
                raise ValueError("lifecycle mutation journal digest is invalid")
            attempt = MutationAttempt(
                attempt_id=str(raw["attempt_id"]),
                idempotency_key=str(raw["idempotency_key"]),
                subject_digest=str(raw["subject_digest"]),
                action=str(raw["action"]),
                step_plan_digest=str(raw["step_plan_digest"]),
                status=str(raw["status"]),
                steps=tuple(str(step) for step in raw.get("steps", ())),
            )
            prior = attempts.get(attempt.idempotency_key)
            if prior is not None and prior != attempt:
                raise ValueError("lifecycle mutation journal reuses an idempotency key")
            attempts[attempt.idempotency_key] = attempt
        return attempts

    def _load_mutations(self) -> None:
        for key, attempt in self._read_mutation_attempts().items():
            self._mutation_keys[key] = attempt.attempt_id
            self._mutation_attempts[key] = attempt

    def record_mutation_result(
        self,
        attempt: MutationAttempt,
        *,
        status: str,
        result_digest: str | None,
    ) -> MutationResult:
        if status not in {"SUCCEEDED", "FAILED", "UNKNOWN"}:
            raise TransitionDeniedError("mutation result status is not admitted")
        if attempt.subject_digest != self.subject_digest:
            raise TransitionDeniedError("mutation attempt subject does not match")
        if status == "SUCCEEDED" and (
            result_digest is None or _SHA256.fullmatch(result_digest) is None
        ):
            raise TransitionDeniedError("successful mutation requires a canonical result digest")
        self._register_mutation(attempt)
        prior = self._mutation_results.get(attempt.idempotency_key)
        if prior is not None:
            if prior.attempt_id != attempt.attempt_id:
                raise TransitionDeniedError("mutation result attempt does not match")
            if prior.status != status or prior.result_digest != result_digest:
                raise TransitionDeniedError("mutation result is already sealed")
            return prior
        result = MutationResult(
            attempt.attempt_id,
            attempt.idempotency_key,
            status,
            result_digest,
        )
        self._append(
            kind="MUTATION_RESULT",
            outcome="RECORDED",
            source=self.state,
            target=self.state,
            reason=attempt.action,
            actor="adapter",
            evidence_refs={
                "attempt_id": attempt.attempt_id,
                "idempotency_key": attempt.idempotency_key,
                "result_digest": result_digest or "UNKNOWN",
            },
            observed_at="",
            detail=status,
        )
        self._mutation_results[attempt.idempotency_key] = result
        return result

    def record_observation(
        self,
        *,
        source: str,
        subject_digest: str,
        payload_digest: str,
        signature: str,
        observed_at: str,
    ) -> LifecycleEvent:
        if subject_digest != self.subject_digest:
            raise TransitionDeniedError("observation subject does not match the lifecycle subject")
        if not source or not payload_digest or not signature or not observed_at:
            raise TransitionDeniedError("observation is not digest-bound and attributable")
        return self._append(
            kind="OBSERVATION",
            outcome="RECORDED",
            source=self.state,
            target=self.state,
            reason=source,
            actor=source,
            evidence_refs={
                "subject_digest": subject_digest,
                "payload_digest": payload_digest,
                "signature": signature,
            },
            observed_at=observed_at,
        )

    def resume(self, context: TransitionContext) -> LifecycleEvent:
        """Resume only the exact safe gate recorded by a prior stop event."""

        if self.state not in {S.BLOCKED, S.BUDGET_EXCEEDED}:
            self._deny(self.state, context, "resume", "only a stopped lifecycle can resume")
        recorded = next(
            (
                event.resume_state
                for event in reversed(self.events)
                if event.outcome == "APPLIED"
                and event.target is self.state
                and event.resume_state is not None
            ),
            None,
        )
        if recorded is None or context.resume_state is not recorded:
            self._deny(
                context.resume_state or self.state,
                context,
                "resume",
                "resume target does not match the recorded safe state",
            )
        if context.rollout.has_resources:
            self._deny(
                recorded, context, "resume", "ordinary resume requires zero rollout resources"
            )
        if context.work.worker_leases_active or not context.work.workers_stopped:
            self._deny(recorded, context, "resume", "ordinary resume requires stopped workers")
        if not context.authority.current:
            self._deny(recorded, context, "resume", "authority must be current before resume")
        try:
            usage = self._merge_budget_usage(context.budget_usage, reject_lower=True)
        except TransitionDeniedError as exc:
            self._deny(recorded, context, "resume", str(exc))
            raise AssertionError("unreachable") from exc
        if usage.exhausted_dimensions(self.budget_policy):
            self._deny(recorded, context, "resume", "approved budget extension is not effective")
        source = self.state
        event = self._append(
            kind="TRANSITION",
            outcome="APPLIED",
            source=source,
            target=recorded,
            reason="recorded_safe_resume",
            actor=context.actor,
            evidence_refs=dict(context.evidence),
            observed_at=context.observed_at,
            budget_usage=usage,
            resume_state=recorded,
        )
        self.state = recorded
        self.budget_usage = usage
        return event
