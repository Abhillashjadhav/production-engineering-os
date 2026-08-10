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
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, NoReturn

from pmpe.domain.serialize import atomic_write_json

EvidenceVerifier = Callable[[str, str, Mapping[str, Any], str], bool]


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
    valid_until: str
    digest: str

    @property
    def digest_valid(self) -> bool:
        return self.digest == _digest(
            {
                "contract_version": self.contract_version,
                "publisher_version": self.publisher_version,
                "contract_active": self.contract_active,
                "publisher_active": self.publisher_active,
                "observed_at": self.observed_at,
                "valid_until": self.valid_until,
            }
        )

    @property
    def current(self) -> bool:
        return bool(
            self.contract_active
            and self.publisher_active
            and self.contract_version
            and self.publisher_version
            and self.observed_at
            and self.valid_until
            and self.digest
        )

    def current_at(self, transition_observed_at: str) -> bool:
        """Require an unexpired authority observation made for this transition."""

        if not self.current or not self.digest_valid or not transition_observed_at:
            return False
        try:
            authority_observed = datetime.fromisoformat(self.observed_at.replace("Z", "+00:00"))
            valid_until = datetime.fromisoformat(self.valid_until.replace("Z", "+00:00"))
            transition_observed = datetime.fromisoformat(
                transition_observed_at.replace("Z", "+00:00")
            )
        except ValueError:
            return False
        if any(
            value.tzinfo is None for value in (authority_observed, valid_until, transition_observed)
        ):
            return False
        return authority_observed == transition_observed < valid_until


@dataclass(frozen=True)
class BudgetPolicy:
    version: str
    limits: Mapping[str, int]
    repair_attempts_per_finding: int
    repair_attempts_per_stage: int
    reserved_safety_units: int
    approved_by: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "limits", MappingProxyType(dict(self.limits)))
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
class EvidenceTrustPolicy:
    """Immutable authority roots for external evidence producers."""

    adapter_authorities: Mapping[str, str] = field(default_factory=dict)
    budget_owner_authorities: Mapping[str, str] = field(default_factory=dict)
    repository_observers: Mapping[str, str] = field(default_factory=dict)
    work_controllers: Mapping[str, str] = field(default_factory=dict)
    production_approvers: Mapping[str, str] = field(default_factory=dict)
    budget_meters: Mapping[str, str] = field(default_factory=dict)
    formal_reviewers: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "adapter_authorities",
            "budget_owner_authorities",
            "repository_observers",
            "work_controllers",
            "production_approvers",
            "budget_meters",
            "formal_reviewers",
        ):
            values = dict(getattr(self, name))
            if any(
                not identity or _SHA256.fullmatch(digest) is None
                for identity, digest in values.items()
            ):
                raise ValueError("evidence trust roots require named canonical authorities")
            object.__setattr__(self, name, MappingProxyType(values))


@dataclass(frozen=True)
class BudgetUsage:
    counters: Mapping[str, int] = field(default_factory=dict)
    repair_attempts_by_finding: Mapping[str, int] = field(default_factory=dict)
    repair_attempts_by_stage: Mapping[str, int] = field(default_factory=dict)
    safety_units_used: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "counters", MappingProxyType(dict(self.counters)))
        object.__setattr__(
            self,
            "repair_attempts_by_finding",
            MappingProxyType(dict(self.repair_attempts_by_finding)),
        )
        object.__setattr__(
            self,
            "repair_attempts_by_stage",
            MappingProxyType(dict(self.repair_attempts_by_stage)),
        )
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
    mutation_capability_active: bool = False
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
    reviewed_commit_sha: str = ""
    reviewed_candidate_digest: str = ""
    review_evidence_digest: str = ""
    authentication_evidence_digest: str = ""


@dataclass(frozen=True)
class TransitionActor:
    """Authenticated authority presented for one exact lifecycle subject."""

    actor_id: str
    role: str
    authenticated: bool
    capabilities: frozenset[str]
    subject_digest: str
    authority_digest: str
    authentication_evidence_digest: str


@dataclass(frozen=True)
class BudgetExtensionAuthorization:
    """Owner authority for one bounded, exact-subject budget extension."""

    extension_id: str
    owner_id: str
    owner_role: str
    authenticated: bool
    capabilities: frozenset[str]
    run_id: str
    subject_digest: str
    authority_digest: str
    credential_digest: str
    prior_policy_digest: str
    proposed_policy_digest: str
    amounts: dict[str, int]
    reason: str
    valid_from: str
    valid_until: str
    evidence_digest: str


@dataclass(frozen=True)
class FindingSignal:
    finding_id: str
    source: str
    exact_subject_digest: str
    severity: str
    credible: bool
    blocking: bool
    reviewer_eligible: bool
    category: str = ""
    disposition: str = ""
    affected_scope_digest: str = ""


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
class AdapterResultEvidence:
    """Authenticated adapter claim for one exact mutation result."""

    adapter_id: str
    role: str
    authenticated: bool
    capabilities: frozenset[str]
    subject_digest: str
    authority_digest: str
    attempt_id: str
    idempotency_key: str
    action: str
    step_plan_digest: str
    status: str
    result_digest: str | None
    authentication_evidence_digest: str


@dataclass(frozen=True)
class TransitionContext:
    actor: TransitionActor
    evidence: dict[str, str]
    authority: AuthoritySnapshot
    budget_usage: BudgetUsage
    rollout: RolloutStatus
    work: WorkStatus
    approvals: tuple[Approval, ...] = ()
    finding: FindingSignal | None = None
    mutation: MutationAttempt | None = None
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


def _budget_policy_payload(policy: BudgetPolicy) -> dict[str, Any]:
    return {
        "version": policy.version,
        "limits": dict(policy.limits),
        "repair_attempts_per_finding": policy.repair_attempts_per_finding,
        "repair_attempts_per_stage": policy.repair_attempts_per_stage,
        "reserved_safety_units": policy.reserved_safety_units,
        "approved_by": policy.approved_by,
    }


def _trust_policy_payload(policy: EvidenceTrustPolicy) -> dict[str, Any]:
    return {
        "adapter_authorities": dict(policy.adapter_authorities),
        "budget_owner_authorities": dict(policy.budget_owner_authorities),
        "repository_observers": dict(policy.repository_observers),
        "work_controllers": dict(policy.work_controllers),
        "production_approvers": dict(policy.production_approvers),
        "budget_meters": dict(policy.budget_meters),
        "formal_reviewers": dict(policy.formal_reviewers),
    }


def _budget_usage_payload(usage: BudgetUsage) -> dict[str, Any]:
    return {
        "counters": dict(usage.counters),
        "repair_attempts_by_finding": dict(usage.repair_attempts_by_finding),
        "repair_attempts_by_stage": dict(usage.repair_attempts_by_stage),
        "safety_units_used": usage.safety_units_used,
    }


def _adapter_result_evidence_payload(evidence: AdapterResultEvidence) -> dict[str, Any]:
    return {
        "adapter_id": evidence.adapter_id,
        "role": evidence.role,
        "authenticated": evidence.authenticated,
        "capabilities": sorted(evidence.capabilities),
        "subject_digest": evidence.subject_digest,
        "authority_digest": evidence.authority_digest,
        "attempt_id": evidence.attempt_id,
        "idempotency_key": evidence.idempotency_key,
        "action": evidence.action,
        "step_plan_digest": evidence.step_plan_digest,
        "status": evidence.status,
        "result_digest": evidence.result_digest,
    }


def _actor_evidence_digest(actor: TransitionActor) -> str:
    return _digest(
        {
            "actor_id": actor.actor_id,
            "role": actor.role,
            "authenticated": actor.authenticated,
            "capabilities": sorted(actor.capabilities),
            "subject_digest": actor.subject_digest,
            "authority_digest": actor.authority_digest,
        }
    )


def _actor_authentication_payload(actor: TransitionActor) -> dict[str, Any]:
    """The externally attested actor claim, excluding its proof."""

    return {
        "actor_id": actor.actor_id,
        "role": actor.role,
        "authenticated": actor.authenticated,
        "capabilities": sorted(actor.capabilities),
        "subject_digest": actor.subject_digest,
        "authority_digest": actor.authority_digest,
    }


def _production_approval_payload(approval: Approval) -> dict[str, Any]:
    payload = asdict(approval)
    payload.pop("authentication_evidence_digest")
    return payload


def _budget_extension_authorization_payload(
    authorization: BudgetExtensionAuthorization,
) -> dict[str, Any]:
    return {
        "extension_id": authorization.extension_id,
        "owner_id": authorization.owner_id,
        "owner_role": authorization.owner_role,
        "authenticated": authorization.authenticated,
        "capabilities": sorted(authorization.capabilities),
        "run_id": authorization.run_id,
        "subject_digest": authorization.subject_digest,
        "authority_digest": authorization.authority_digest,
        "credential_digest": authorization.credential_digest,
        "prior_policy_digest": authorization.prior_policy_digest,
        "proposed_policy_digest": authorization.proposed_policy_digest,
        "amounts": authorization.amounts,
        "reason": authorization.reason,
        "valid_from": authorization.valid_from,
        "valid_until": authorization.valid_until,
    }


_PRODUCTION_APPROVAL_SCOPE_FIELDS = (
    "subject_digest",
    "merge_commit_sha",
    "merge_digest",
    "artifact_digest",
    "configuration_digest",
    "migration_plan_digest",
    "deployment_target_digest",
    "rollout_plan_digest",
    "staging_digest",
    "canary_id_digest",
    "canary_attempt_digest",
    "canary_status_digest",
)

_CANARY_ROLLOUT_SUBJECT_FIELDS = (
    "subject_digest",
    "merge_commit_sha",
    "merge_digest",
    "artifact_digest",
    "configuration_digest",
    "migration_plan_digest",
    "deployment_target_digest",
    "rollout_plan_digest",
    "staging_digest",
)


def _production_approval_scope_digest(evidence: dict[str, str]) -> str:
    return _digest({name: evidence.get(name, "") for name in _PRODUCTION_APPROVAL_SCOPE_FIELDS})


_MUTATION_SUBJECT_FIELDS: dict[str, tuple[str, ...]] = {
    "open_draft_pr": (
        "subject_digest",
        "governance_attempt_digest",
        "issue_digest",
        "branch_digest",
        "red_commit_digest",
        "draft_pr_digest",
    ),
    "enqueue_merge": (
        "subject_digest",
        "queue_subject_digest",
        "head_commit_sha",
        "head_digest",
        "base_digest",
        "prospective_tree_digest",
        "required_checks_digest",
        "formal_review_digest",
        "verification_bundle_digest",
    ),
    "deploy_staging": ("subject_digest", "merge_digest", "artifact_digest"),
    "deploy_canary": (
        *_CANARY_ROLLOUT_SUBJECT_FIELDS,
        "canary_authorization_digest",
        "canary_id_digest",
    ),
    "deploy_production": (*_PRODUCTION_APPROVAL_SCOPE_FIELDS, "production_approval_digest"),
    "convert_pr_to_draft": (
        "subject_digest",
        "ready_revocation_attempt_digest",
        "ready_revocation_observation_digest",
    ),
    "cleanup_staging": (
        "subject_digest",
        "zero_resource_digest",
    ),
    "rollback": ("subject_digest",),
    "teardown_canary": (
        "subject_digest",
        "canary_teardown_digest",
        "zero_resource_digest",
    ),
}


def mutation_subject_digest(action: str, evidence: Mapping[str, str]) -> str:
    """Return the immutable external-effect subject for a guarded mutation."""

    fields = _MUTATION_SUBJECT_FIELDS.get(action)
    if fields is None:
        raise ValueError(f"mutation action {action!r} has no exact-subject binding")
    return _digest({name: evidence.get(name, "") for name in fields})


_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40,64}$")
_FINDING_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_FINDING_SOURCE = re.compile(r"^[a-z0-9][a-z0-9._:-]*$")


def _normalized_engineering_finding(
    finding: FindingSignal | None,
    subject_digest: str,
    *,
    accepted_for_repair: bool,
) -> bool:
    if finding is None:
        return False
    admitted_dispositions = (
        {"ACCEPTED_FOR_REPAIR"} if accepted_for_repair else {"ACCEPTED", "ACCEPTED_FOR_REPAIR"}
    )
    return bool(
        _FINDING_ID.fullmatch(finding.finding_id)
        and _FINDING_SOURCE.fullmatch(finding.source)
        and finding.exact_subject_digest == subject_digest
        and finding.severity.upper() in {"CRITICAL", "HIGH", "MEDIUM"}
        and finding.credible
        and finding.blocking
        and finding.category == "ENGINEERING"
        and finding.disposition in admitted_dispositions
        and _SHA256.fullmatch(finding.affected_scope_digest)
    )


def _malformed_evidence(evidence: dict[str, str], names: tuple[str, ...]) -> tuple[str, ...]:
    malformed: list[str] = []
    for name in names:
        value = evidence.get(name, "")
        if name == "release_sha" or name.endswith("_commit_sha"):
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
    guard_set = frozenset(guards)
    guard_evidence: tuple[str, ...] = ()
    if "drift" in guard_set:
        guard_evidence += (
            "work_disposition_digest",
            "worker_quiescence_digest",
            "mutation_revocation_digest",
            "review_invalidation_digest",
        )
    if "product_input" in guard_set:
        guard_evidence += (
            "work_disposition_digest",
            "worker_quiescence_digest",
            "mutation_revocation_digest",
        )
    if "budget_stop" in guard_set:
        guard_evidence += (
            "work_disposition_digest",
            "worker_quiescence_digest",
            "mutation_revocation_digest",
        )
    if "revoke_completion" in guard_set:
        guard_evidence += (
            "subject_digest",
            "monitor_identity_digest",
            "monitor_authentication_evidence_digest",
        )
    required_evidence = tuple(dict.fromkeys((*evidence, *guard_evidence)))
    return TransitionRule(
        source,
        target,
        reason,
        required_evidence,
        guard_set,
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
        S.CONTRACT_RECEIVED,
        S.BLOCKED,
        "quarantine_disposition_indeterminate",
        (
            "subject_digest",
            "intake_receipt_digest",
            "affected_artifact_digest",
            "quarantine_disposition_status",
            "quarantine_disposition_digest",
            "exposure_digest",
            "incident_digest",
            "worker_quiescence_digest",
            "mutation_revocation_digest",
            "retry_gate_digest",
        ),
        "security_incident_block",
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
        (
            "subject_digest",
            "review_digest",
            "verification_bundle_digest",
            "prospective_tree_digest",
            "reviewed_commit_sha",
        ),
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
            "head_commit_sha",
            "head_digest",
            "base_digest",
            "prospective_tree_digest",
            "required_checks_digest",
            "formal_review_digest",
            "verification_bundle_digest",
            "merge_attempt_digest",
            "merge_result_digest",
            "merge_commit_sha",
            "merge_tree_digest",
            "merge_method_digest",
            "merge_actor_digest",
        ),
        "authority",
        "budget",
        "mutation",
        "merge_binding",
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
        S.BLOCKED,
        "post_merge_blocking_finding",
        (
            "subject_digest",
            "finding_digest",
            "worker_quiescence_digest",
            "mutation_revocation_digest",
            "zero_resource_digest",
        ),
        "blocking_finding",
        "safe_stop",
    ),
    _r(
        S.PR_MERGED,
        S.STAGING_DEPLOYED,
        "staging_admitted",
        ("merge_digest", "artifact_digest", "staging_attempt_digest", "staging_result_digest"),
        *_MUTATION,
        "no_blocking_finding",
        "integrated_merge",
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
            "subject_digest",
            "merge_commit_sha",
            "merge_digest",
            "artifact_digest",
            "configuration_digest",
            "migration_plan_digest",
            "deployment_target_digest",
            "rollout_plan_digest",
            "staging_digest",
            "canary_authorization_digest",
            "canary_id_digest",
            "canary_attempt_digest",
            "canary_result_digest",
            "canary_status_digest",
        ),
        *_MUTATION,
        "canary_binding",
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
        (
            "canary_no_mutation_digest",
            "cleanup_attempt_digest",
            "zero_resource_digest",
            "blocker_digest",
        ),
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
        (
            "subject_digest",
            "merge_commit_sha",
            "merge_digest",
            "artifact_digest",
            "configuration_digest",
            "migration_plan_digest",
            "deployment_target_digest",
            "rollout_plan_digest",
            "staging_digest",
            "canary_digest",
            "canary_id_digest",
            "canary_attempt_digest",
            "canary_status_digest",
            "slo_window_digest",
            "approval_request_digest",
        ),
        *_FORWARD,
        "active_canary",
    ),
    _r(
        S.CANARY_DEPLOYED,
        S.ROLLBACK_IN_PROGRESS,
        "canary_failed",
        (
            "subject_digest",
            "canary_id_digest",
            "canary_status_digest",
            "canary_attempt_digest",
            "canary_result_digest",
            "canary_failure_digest",
            "rollback_attempt_digest",
            "resource_status_digest",
        ),
        *_SAFETY,
        "active_canary",
        mutation="rollback",
    ),
    _r(
        S.CANARY_DEPLOYED,
        S.ROLLBACK_IN_PROGRESS,
        "governance_stop",
        (
            "subject_digest",
            "canary_id_digest",
            "canary_attempt_digest",
            "canary_status_digest",
            "governance_stop_digest",
            "rollback_attempt_digest",
        ),
        *_SAFETY,
        "active_canary",
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
            "subject_digest",
            "merge_commit_sha",
            "merge_digest",
            "artifact_digest",
            "configuration_digest",
            "migration_plan_digest",
            "deployment_target_digest",
            "rollout_plan_digest",
            "staging_digest",
            "canary_id_digest",
            "canary_attempt_digest",
            "canary_status_digest",
            "production_approval_digest",
            "authority_fence_digest",
            "production_attempt_digest",
            "production_result_digest",
        ),
        *_MUTATION,
        "production_approval",
        "active_canary",
        mutation="deploy_production",
    ),
    _r(
        S.PRODUCTION_APPROVAL_REQUIRED,
        S.ROLLBACK_IN_PROGRESS,
        "canary_breach",
        (
            "subject_digest",
            "canary_id_digest",
            "canary_status_digest",
            "canary_attempt_digest",
            "canary_result_digest",
            "canary_failure_digest",
            "rollback_attempt_digest",
            "resource_status_digest",
        ),
        *_SAFETY,
        "active_canary",
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
            "subject_digest",
            "release_sha",
            "reviewed_commit_sha",
            "reviewed_candidate_digest",
            "review_evidence_digest",
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
            "subject_digest",
            "rollback_attempt_digest",
            "rollback_result_digest",
            "rollback_exposure_digest",
            "restoration_verification_digest",
            "incident_digest",
        ),
        "safety",
        "mutation",
        "zero_exposure",
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
_ORDINARY_SAFE_RESUME_TARGETS = (
    S.CONTRACT_RECEIVED,
    S.CONTRACT_APPROVED,
    S.REPOSITORY_ANALYSED,
    S.VERIFICATION_FAILED,
    S.PR_READY,
    S.PR_MERGED,
    S.PRODUCTION_DEPLOYED,
)
_BUDGET_SAFE_RESUME_TARGETS = (
    S.DRAFT_PR_OPEN,
    S.IMPLEMENTATION_IN_PROGRESS,
    S.VERIFICATION_FAILED,
    S.REPAIR_IN_PROGRESS,
    S.PR_MERGED,
    S.ROLLED_BACK,
)
_RECORDED_RESUME_EVIDENCE = (
    "subject_digest",
    "incident_closure_digest",
    "restored_capability_digest",
    "unchanged_inputs_digest",
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
    )
    + tuple(
        _r(
            S.BLOCKED,
            target,
            "recorded_safe_resume",
            _RECORDED_RESUME_EVIDENCE,
            "authority",
            "budget",
        )
        for target in _ORDINARY_SAFE_RESUME_TARGETS
    )
    + tuple(
        _r(
            S.BUDGET_EXCEEDED,
            target,
            "recorded_safe_resume",
            _RECORDED_RESUME_EVIDENCE,
            "authority",
            "budget",
        )
        for target in _BUDGET_SAFE_RESUME_TARGETS
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
    evidence_refs: Mapping[str, str]
    budget_usage: Mapping[str, Any] | None
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
        trust_policy: EvidenceTrustPolicy | None = None,
        evidence_verifier: EvidenceVerifier | None = None,
        events: list[LifecycleEvent] | None = None,
    ) -> None:
        self.run_dir = Path(run_dir)
        self.run_id = run_id
        self._subject_digest = subject_digest
        self._state = state
        self._budget_policy = budget_policy
        self._trust_policy = trust_policy or EvidenceTrustPolicy()
        self._evidence_verifier = evidence_verifier
        self._events = list(events or ())
        self._operation_lock = threading.RLock()
        self._completion_claim_active = False
        self._mutation_keys: dict[str, str] = {}
        self._mutation_attempts: dict[str, MutationAttempt] = {}
        self._mutation_results: dict[str, MutationResult] = {}
        self._verified_mutation_result_keys: set[str] = set()
        self._budget_usage = BudgetUsage()

    @property
    def subject_digest(self) -> str:
        """The metadata-bound lifecycle identity; never caller-replaceable."""
        return self._subject_digest

    @property
    def budget_usage(self) -> BudgetUsage:
        """Authoritative usage changes only through ledger append/replay."""
        return self._budget_usage

    @property
    def state(self) -> LifecycleState:
        return self._state

    @property
    def events(self) -> tuple[LifecycleEvent, ...]:
        return tuple(self._events)

    @property
    def completion_claim_active(self) -> bool:
        return self._completion_claim_active

    @property
    def budget_policy(self) -> BudgetPolicy:
        return self._budget_policy

    @property
    def trust_policy(self) -> EvidenceTrustPolicy:
        return self._trust_policy

    @property
    def ledger_path(self) -> Path:
        return self.run_dir / self._LEDGER_NAME

    @property
    def mutation_path(self) -> Path:
        return self.run_dir / self._MUTATIONS_NAME

    @property
    def lock_path(self) -> Path:
        return self.run_dir / self._LOCK_NAME

    def _trusted_work_evidence_valid(self, context: TransitionContext) -> bool:
        evidence = context.evidence
        controller = evidence.get("work_controller_id", "")
        authority_digest = evidence.get("work_controller_authority_digest", "")
        observed_at = evidence.get("work_control_observed_at", "")
        lease_epoch = evidence.get("work_lease_epoch_digest", "")
        capability_epoch = evidence.get("mutation_capability_epoch_digest", "")
        work_digest = _digest(asdict(context.work))
        quiescence = _digest(
            {
                "controller_id": controller,
                "authority_digest": authority_digest,
                "subject_digest": self.subject_digest,
                "work_digest": work_digest,
                "lease_epoch_digest": lease_epoch,
                "observed_at": observed_at,
                "status": "QUIESCED",
            }
        )
        revocation = _digest(
            {
                "controller_id": controller,
                "authority_digest": authority_digest,
                "subject_digest": self.subject_digest,
                "work_digest": work_digest,
                "capability_epoch_digest": capability_epoch,
                "observed_at": observed_at,
                "status": "REVOKED",
            }
        )
        authentication_payload = {
            "controller_id": controller,
            "authority_digest": authority_digest,
            "subject_digest": self.subject_digest,
            "quiescence_digest": quiescence,
            "revocation_digest": revocation,
            "observed_at": observed_at,
        }
        return bool(
            controller
            and self.trust_policy.work_controllers.get(controller) == authority_digest
            and observed_at == context.observed_at
            and _SHA256.fullmatch(lease_epoch)
            and _SHA256.fullmatch(capability_epoch)
            and evidence.get("worker_quiescence_digest") == quiescence
            and evidence.get("mutation_revocation_digest") == revocation
            and self._verify_external_evidence(
                controller,
                authority_digest,
                authentication_payload,
                evidence.get("work_control_authentication_evidence_digest", ""),
            )
        )

    def _trusted_repository_observation_valid(
        self, context: TransitionContext, review_inputs: Mapping[str, str]
    ) -> bool:
        evidence = context.evidence
        observer = evidence.get("repository_observer_id", "")
        authority_digest = evidence.get("repository_observer_authority_digest", "")
        observed_at = evidence.get("repository_observed_at", "")
        observation = _digest(
            {
                "observer_id": observer,
                "authority_digest": authority_digest,
                "subject_digest": self.subject_digest,
                "review_inputs": dict(review_inputs),
                "observed_at": observed_at,
            }
        )
        authentication_payload = {
            "observer_id": observer,
            "authority_digest": authority_digest,
            "subject_digest": self.subject_digest,
            "observation_digest": observation,
            "observed_at": observed_at,
        }
        return bool(
            observer
            and self.trust_policy.repository_observers.get(observer) == authority_digest
            and observed_at == context.observed_at
            and evidence.get("repository_observation_digest") == observation
            and self._verify_external_evidence(
                observer,
                authority_digest,
                authentication_payload,
                evidence.get("repository_observation_authentication_evidence_digest", ""),
            )
        )

    def _trusted_budget_usage_valid(self, context: TransitionContext) -> bool:
        evidence = context.evidence
        meter = evidence.get("budget_meter_id", "")
        authority_digest = evidence.get("budget_meter_authority_digest", "")
        payload = {
            "meter_id": meter,
            "authority_digest": authority_digest,
            "subject_digest": self.subject_digest,
            "budget_policy_digest": _digest(_budget_policy_payload(self.budget_policy)),
            "budget_usage_digest": _digest(_budget_usage_payload(context.budget_usage)),
            "observed_at": context.observed_at,
        }
        return bool(
            meter
            and self.trust_policy.budget_meters.get(meter) == authority_digest
            and evidence.get("budget_usage_digest") == payload["budget_usage_digest"]
            and self._verify_external_evidence(
                meter,
                authority_digest,
                payload,
                evidence.get("budget_meter_authentication_evidence_digest", ""),
            )
        )

    def _verify_external_evidence(
        self,
        identity: str,
        authority_digest: str,
        payload: Mapping[str, Any],
        proof: str,
    ) -> bool:
        if self._evidence_verifier is None or not proof:
            return False
        try:
            return bool(self._evidence_verifier(identity, authority_digest, payload, proof))
        except Exception:
            return False

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
        trust_policy: EvidenceTrustPolicy | None = None,
        evidence_verifier: EvidenceVerifier | None = None,
    ) -> LifecycleControlPlane:
        if initial_state is not LifecycleState.CONTRACT_RECEIVED:
            raise ValueError(
                "new lifecycle runs must start at CONTRACT_RECEIVED; "
                "use the explicit migration admission path"
            )
        path = Path(run_dir)
        path.mkdir(parents=True, exist_ok=True)
        cp = cls(
            path,
            run_id=run_id,
            subject_digest=subject_digest,
            state=initial_state,
            budget_policy=budget_policy,
            trust_policy=trust_policy,
            evidence_verifier=evidence_verifier,
        )
        policy_payload = _budget_policy_payload(budget_policy)
        trust_payload = _trust_policy_payload(cp.trust_policy)
        metadata: dict[str, Any] = {
            "run_id": run_id,
            "subject_digest": subject_digest,
            "budget_policy": policy_payload,
            "budget_policy_digest": _digest(policy_payload),
            "trust_policy": trust_payload,
            "trust_policy_digest": _digest(trust_payload),
        }
        with cp._operation_lock, cp._exclusive_lock():
            ledger = path / cls._LEDGER_NAME
            metadata_path = path / cls._META_NAME
            if metadata_path.exists():
                persisted_metadata = json.loads(metadata_path.read_text())
                if persisted_metadata != metadata:
                    raise ValueError("lifecycle run already exists with different metadata")
                if ledger.exists():
                    return cls.load(path, evidence_verifier=evidence_verifier)
            elif ledger.exists():
                raise ValueError("lifecycle ledger exists without bound metadata")
            else:
                atomic_write_json(metadata_path, metadata)
            cp._append_locked(
                kind="STATE_CREATED",
                outcome="APPLIED",
                source=initial_state,
                target=initial_state,
                reason="create",
                actor="control-plane",
                evidence_refs={
                    "budget_policy_digest": str(metadata["budget_policy_digest"]),
                    "run_id_digest": _digest(run_id),
                    "metadata_digest": _digest(metadata),
                    "trust_policy_digest": str(metadata["trust_policy_digest"]),
                },
                observed_at="",
            )
        return cp

    @staticmethod
    def _budget_policy_from_dict(raw_policy: dict[str, Any]) -> BudgetPolicy:
        return BudgetPolicy(
            version=str(raw_policy["version"]),
            limits={str(key): int(value) for key, value in dict(raw_policy["limits"]).items()},
            repair_attempts_per_finding=int(raw_policy["repair_attempts_per_finding"]),
            repair_attempts_per_stage=int(raw_policy["repair_attempts_per_stage"]),
            reserved_safety_units=int(raw_policy["reserved_safety_units"]),
            approved_by=str(raw_policy["approved_by"]),
        )

    @classmethod
    def load(
        cls, run_dir: Path, *, evidence_verifier: EvidenceVerifier | None = None
    ) -> LifecycleControlPlane:
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
        initial = events[0]
        if (
            initial.kind != "STATE_CREATED"
            or initial.subject_digest != metadata.get("subject_digest")
            or initial.evidence_refs.get("budget_policy_digest")
            != metadata.get("budget_policy_digest")
            or initial.evidence_refs.get("run_id_digest")
            != _digest(str(metadata.get("run_id", "")))
            or initial.evidence_refs.get("metadata_digest") != _digest(metadata)
        ):
            raise ValueError("lifecycle metadata is not bound to the initial event")
        budget_policy = cls._budget_policy_from_dict(raw_policy)
        raw_trust = dict(metadata.get("trust_policy", {}))
        if raw_trust and _digest(raw_trust) != metadata.get("trust_policy_digest"):
            raise ValueError("lifecycle evidence trust policy digest is invalid")
        trust_policy = EvidenceTrustPolicy(
            adapter_authorities=dict(raw_trust.get("adapter_authorities", {})),
            budget_owner_authorities=dict(raw_trust.get("budget_owner_authorities", {})),
            repository_observers=dict(raw_trust.get("repository_observers", {})),
            work_controllers=dict(raw_trust.get("work_controllers", {})),
            production_approvers=dict(raw_trust.get("production_approvers", {})),
            budget_meters=dict(raw_trust.get("budget_meters", {})),
            formal_reviewers=dict(raw_trust.get("formal_reviewers", {})),
        )
        if raw_trust and initial.evidence_refs.get("trust_policy_digest") != _digest(raw_trust):
            raise ValueError("lifecycle evidence trust policy is not bound to the initial event")
        cp = cls(
            path,
            run_id=str(metadata["run_id"]),
            subject_digest=str(metadata["subject_digest"]),
            state=events[0].target,
            budget_policy=budget_policy,
            trust_policy=trust_policy,
            evidence_verifier=evidence_verifier,
            events=events,
        )
        cp._load_mutations()
        for event in events[1:]:
            if event.source is not cp.state:
                raise ValueError("lifecycle event source does not match replay state")
            if event.outcome == "APPLIED":
                cp._state = event.target
            elif event.outcome == "RECORDED" and event.target is not cp.state:
                raise ValueError("recorded lifecycle event cannot change replay state")
            if event.budget_usage is not None:
                cp._budget_usage = cp._merge_budget_usage(
                    BudgetUsage(**event.budget_usage), reject_lower=True
                )
            if event.kind == "MUTATION_RESULT":
                attempt_id = event.evidence_refs.get("attempt_id", "")
                key = event.evidence_refs.get("idempotency_key", "")
                if attempt_id and key:
                    result_digest = (
                        event.evidence_refs.get("result_digest")
                        if event.evidence_refs.get("result_digest") != "UNKNOWN"
                        else None
                    )
                    try:
                        capabilities = frozenset(
                            str(value)
                            for value in json.loads(
                                event.evidence_refs.get("adapter_capabilities_json", "")
                            )
                        )
                    except (json.JSONDecodeError, TypeError) as exc:
                        raise ValueError("mutation result adapter evidence is malformed") from exc
                    adapter_evidence = AdapterResultEvidence(
                        adapter_id=event.evidence_refs.get("adapter_id", ""),
                        role=event.evidence_refs.get("adapter_role", ""),
                        authenticated=True,
                        capabilities=capabilities,
                        subject_digest=event.subject_digest,
                        authority_digest=event.evidence_refs.get("adapter_authority_digest", ""),
                        attempt_id=attempt_id,
                        idempotency_key=key,
                        action=event.reason,
                        step_plan_digest=event.evidence_refs.get("adapter_step_plan_digest", ""),
                        status=event.detail,
                        result_digest=result_digest,
                        authentication_evidence_digest=event.evidence_refs.get(
                            "adapter_authentication_evidence_digest", ""
                        ),
                    )
                    if (
                        "lifecycle.mutation.result.record" not in adapter_evidence.capabilities
                        or cp.trust_policy.adapter_authorities.get(adapter_evidence.adapter_id)
                        != adapter_evidence.authority_digest
                        or adapter_evidence.step_plan_digest
                        != cp._mutation_attempts.get(key, adapter_evidence).step_plan_digest
                        or not adapter_evidence.authentication_evidence_digest
                        or (
                            cp._evidence_verifier is not None
                            and not cp._verify_external_evidence(
                                adapter_evidence.adapter_id,
                                adapter_evidence.authority_digest,
                                _adapter_result_evidence_payload(adapter_evidence),
                                adapter_evidence.authentication_evidence_digest,
                            )
                        )
                    ):
                        raise ValueError("mutation result adapter evidence is invalid")
                    cp._mutation_results[key] = MutationResult(
                        attempt_id=attempt_id,
                        idempotency_key=key,
                        status=event.detail,
                        result_digest=result_digest,
                    )
                    if cp._evidence_verifier is not None:
                        cp._verified_mutation_result_keys.add(key)
            if event.kind == "BUDGET_POLICY_ADMITTED":
                policy_json = event.evidence_refs.get("budget_policy_json", "")
                if policy_json:
                    try:
                        admitted_raw = json.loads(policy_json)
                    except json.JSONDecodeError as exc:
                        raise ValueError("admitted budget policy is not valid JSON") from exc
                    if (
                        not isinstance(admitted_raw, dict)
                        or json.dumps(admitted_raw, sort_keys=True, separators=(",", ":"))
                        != policy_json
                    ):
                        raise ValueError("admitted budget policy is not canonical")
                    admitted = cls._budget_policy_from_dict(admitted_raw)
                    prior_digest = _digest(_budget_policy_payload(cp.budget_policy))
                    admitted_digest = _digest(_budget_policy_payload(admitted))
                    if (
                        event.evidence_refs.get("prior_policy_digest") != prior_digest
                        or event.evidence_refs.get("proposed_policy_digest") != admitted_digest
                        or event.evidence_refs.get("budget_policy_digest") != admitted_digest
                        or _SHA256.fullmatch(
                            event.evidence_refs.get("authorization_evidence_digest", "")
                        )
                        is None
                    ):
                        raise ValueError("admitted budget policy evidence is inconsistent")
                    cp._budget_policy = admitted
            if event.kind == "COMPLETION_CLAIMED":
                cp._completion_claim_active = True
            elif event.kind == "COMPLETION_REVOKED":
                cp._completion_claim_active = False
        return cp

    @staticmethod
    def _budget_extension_amounts(current: BudgetPolicy, proposed: BudgetPolicy) -> dict[str, int]:
        current_values = {
            **current.limits,
            "repair_attempts_per_finding": current.repair_attempts_per_finding,
            "repair_attempts_per_stage": current.repair_attempts_per_stage,
            "reserved_safety_units": current.reserved_safety_units,
        }
        proposed_values = {
            **proposed.limits,
            "repair_attempts_per_finding": proposed.repair_attempts_per_finding,
            "repair_attempts_per_stage": proposed.repair_attempts_per_stage,
            "reserved_safety_units": proposed.reserved_safety_units,
        }
        return {
            name: proposed_values[name] - value
            for name, value in current_values.items()
            if proposed_values[name] != value
        }

    def admit_budget_policy(
        self,
        policy: BudgetPolicy,
        *,
        authorization: BudgetExtensionAuthorization | None = None,
        authority: AuthoritySnapshot | None = None,
        observed_at: str = "",
    ) -> None:
        if authorization is None or authority is None:
            raise TransitionDeniedError("authenticated budget owner authority is required")
        if (
            not authorization.owner_id
            or not authorization.owner_role
            or not authorization.authenticated
            or "lifecycle.budget.extend" not in authorization.capabilities
        ):
            raise TransitionDeniedError("authenticated budget owner authority is required")
        if (
            authorization.run_id != self.run_id
            or authorization.subject_digest != self.subject_digest
        ):
            raise TransitionDeniedError("budget extension run or subject does not match")
        if (
            not authority.current_at(observed_at)
            or authorization.authority_digest != authority.digest
            or authorization.owner_id != policy.approved_by
        ):
            raise TransitionDeniedError("budget extension owner authority is not current")
        if not authorization.extension_id or not authorization.reason:
            raise TransitionDeniedError("budget extension identity and reason are required")
        if (
            _SHA256.fullmatch(authorization.credential_digest) is None
            or _SHA256.fullmatch(authorization.evidence_digest) is None
        ):
            raise TransitionDeniedError("budget extension evidence digest is not canonical")
        authorization_body = _budget_extension_authorization_payload(authorization)
        if self.trust_policy.budget_owner_authorities.get(
            authorization.owner_id
        ) != authorization.credential_digest or not self._verify_external_evidence(
            authorization.owner_id,
            authorization.credential_digest,
            authorization_body,
            authorization.evidence_digest,
        ):
            raise TransitionDeniedError("trusted budget-owner authority is required")
        try:
            valid_from = datetime.fromisoformat(authorization.valid_from.replace("Z", "+00:00"))
            valid_until = datetime.fromisoformat(authorization.valid_until.replace("Z", "+00:00"))
            observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise TransitionDeniedError("budget extension validity is malformed") from exc
        if valid_from.tzinfo is None or valid_until.tzinfo is None or observed.tzinfo is None:
            raise TransitionDeniedError("budget extension validity must include a timezone")
        if valid_from > observed or observed >= valid_until:
            raise TransitionDeniedError("budget extension is outside its validity window")
        current_digest = _digest(_budget_policy_payload(self.budget_policy))
        proposed_digest = _digest(_budget_policy_payload(policy))
        if (
            authorization.prior_policy_digest != current_digest
            or authorization.proposed_policy_digest != proposed_digest
        ):
            raise TransitionDeniedError("budget extension is not bound to the exact policies")
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
        amounts = self._budget_extension_amounts(self.budget_policy, policy)
        if not amounts or any(amount <= 0 for amount in amounts.values()):
            raise TransitionDeniedError("budget extension amounts must be positive and bounded")
        if authorization.amounts != amounts:
            raise TransitionDeniedError(
                "budget extension amount does not match the proposed policy"
            )
        self._append(
            kind="BUDGET_POLICY_ADMITTED",
            outcome="RECORDED",
            source=self.state,
            target=self.state,
            reason=authorization.reason,
            actor=authorization.owner_id,
            evidence_refs={
                "extension_id": authorization.extension_id,
                "run_id": authorization.run_id,
                "subject_digest": authorization.subject_digest,
                "authority_digest": authorization.authority_digest,
                "credential_digest": authorization.credential_digest,
                "prior_policy_digest": current_digest,
                "proposed_policy_digest": proposed_digest,
                "budget_policy_digest": proposed_digest,
                "budget_policy_json": json.dumps(
                    _budget_policy_payload(policy), sort_keys=True, separators=(",", ":")
                ),
                "amounts_digest": _digest(amounts),
                "authorization_evidence_digest": authorization.evidence_digest,
                "valid_from": authorization.valid_from,
                "valid_until": authorization.valid_until,
            },
            observed_at=observed_at,
            expected_budget_policy_digest=current_digest,
            admitted_budget_policy=policy,
        )

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
            evidence_refs=MappingProxyType(
                {str(key): str(value) for key, value in dict(raw.get("evidence_refs", {})).items()}
            ),
            budget_usage=(
                MappingProxyType(dict(raw["budget_usage"]))
                if raw.get("budget_usage") is not None
                else None
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
        expected_budget_policy_digest: str | None = None,
        admitted_budget_policy: BudgetPolicy | None = None,
    ) -> LifecycleEvent:
        with self._operation_lock, self._exclusive_lock():
            return self._append_locked(
                kind=kind,
                outcome=outcome,
                source=source,
                target=target,
                reason=reason,
                actor=actor,
                evidence_refs=evidence_refs,
                observed_at=observed_at,
                budget_usage=budget_usage,
                resume_state=resume_state,
                detail=detail,
                expected_budget_policy_digest=expected_budget_policy_digest,
                admitted_budget_policy=admitted_budget_policy,
            )

    def _append_locked(
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
        expected_budget_policy_digest: str | None = None,
        admitted_budget_policy: BudgetPolicy | None = None,
    ) -> LifecycleEvent:
        """Append while both the instance and lifecycle file locks are held."""

        persisted = (
            [json.loads(line) for line in self.ledger_path.read_text().splitlines() if line.strip()]
            if self.ledger_path.exists()
            else []
        )
        expected_previous = self._events[-1].event_digest if self._events else ""
        persisted_previous = str(persisted[-1].get("event_digest", "")) if persisted else ""
        if len(persisted) != len(self._events) or persisted_previous != expected_previous:
            raise TransitionDeniedError("stale lifecycle writer lost the append compare-and-swap")
        if (
            expected_budget_policy_digest is not None
            and _digest(_budget_policy_payload(self.budget_policy)) != expected_budget_policy_digest
        ):
            raise TransitionDeniedError("stale budget policy admission lost compare-and-swap")
        body: dict[str, Any] = {
            "sequence": len(self._events) + 1,
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
            "budget_usage": _budget_usage_payload(budget_usage)
            if budget_usage is not None
            else None,
            "observed_at": observed_at,
            "resume_state": resume_state.value if resume_state else None,
            "previous_digest": expected_previous,
            "detail": detail,
        }
        body["event_digest"] = _digest(body)
        event = self._event_from_dict(body)
        serialized = json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n"
        if not persisted and not self._events:
            temporary = self.ledger_path.with_suffix(self.ledger_path.suffix + ".tmp")
            with temporary.open("w") as stream:
                stream.write(serialized)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.ledger_path)
        else:
            with self.ledger_path.open("a") as stream:
                stream.write(serialized)
                stream.flush()
                os.fsync(stream.fileno())
        self._events.append(event)
        if admitted_budget_policy is not None:
            self._budget_policy = admitted_budget_policy
        return event

    def _deny(
        self,
        target: LifecycleState,
        context: TransitionContext,
        reason: str,
        detail: str,
    ) -> NoReturn:
        supplied = replace(
            context.budget_usage,
            safety_units_used=self.budget_usage.safety_units_used,
        )
        persisted_usage = self._merge_budget_usage(supplied, reject_lower=False)
        self._append(
            kind="TRANSITION",
            outcome="DENIED",
            source=self.state,
            target=target,
            reason=reason,
            actor=context.actor.actor_id,
            evidence_refs=dict(context.evidence),
            observed_at=context.observed_at,
            budget_usage=persisted_usage,
            detail=detail,
        )
        self._budget_usage = persisted_usage
        raise TransitionDeniedError(detail)

    def _latest_canary_binding(self) -> LifecycleEvent | None:
        return next(
            (
                event
                for event in reversed(self.events)
                if event.reason == "canary_admitted"
                and (
                    (event.outcome == "APPLIED" and event.target is S.CANARY_DEPLOYED)
                    or event.kind == "CANARY_BINDING_ADMITTED"
                )
            ),
            None,
        )

    def _latest_review_binding(self) -> LifecycleEvent | None:
        return next(
            (
                event
                for event in reversed(self.events)
                if event.reason == "formal_review_clear"
                and (
                    (event.outcome == "APPLIED" and event.target is S.PR_READY)
                    or event.kind == "REVIEW_BINDING_ADMITTED"
                )
            ),
            None,
        )

    def _latest_merge_binding(self) -> LifecycleEvent | None:
        return next(
            (
                event
                for event in reversed(self.events)
                if event.reason == "native_merge_linearized"
                and event.outcome == "APPLIED"
                and event.target is S.PR_MERGED
            ),
            None,
        )

    def transition(
        self, target: LifecycleState, context: TransitionContext, *, reason: str
    ) -> LifecycleEvent:
        """Validate and append one transition against one serialized source state."""

        with self._operation_lock:
            return self._transition_locked(target, context, reason=reason)

    def _transition_locked(
        self, target: LifecycleState, context: TransitionContext, *, reason: str
    ) -> LifecycleEvent:
        context = replace(
            context,
            evidence=dict(context.evidence),
            budget_usage=BudgetUsage(
                counters=dict(context.budget_usage.counters),
                repair_attempts_by_finding=dict(context.budget_usage.repair_attempts_by_finding),
                repair_attempts_by_stage=dict(context.budget_usage.repair_attempts_by_stage),
                safety_units_used=context.budget_usage.safety_units_used,
            ),
        )
        source = self.state
        actor = context.actor
        event_evidence = dict(context.evidence)
        if (
            not actor.actor_id
            or not actor.role
            or not actor.authenticated
            or actor.subject_digest != self.subject_digest
            or actor.authority_digest != context.authority.digest
            or not context.authority.digest_valid
            or _SHA256.fullmatch(actor.authority_digest) is None
            or not self._verify_external_evidence(
                actor.actor_id,
                actor.authority_digest,
                _actor_authentication_payload(actor),
                actor.authentication_evidence_digest,
            )
        ):
            self._deny(target, context, reason, "actor authority is invalid for this subject")
        if context.budget_usage.safety_units_used != self.budget_usage.safety_units_used:
            self._deny(
                target,
                context,
                reason,
                "reserved safety usage is controlled only by the lifecycle authority",
            )
        try:
            usage = self._merge_budget_usage(context.budget_usage, reject_lower=True)
        except TransitionDeniedError as exc:
            self._deny(target, context, reason, str(exc))
            raise AssertionError("unreachable") from exc
        exposure_preserving_block = (
            source is S.ROLLBACK_IN_PROGRESS
            and target is S.BLOCKED
            and reason == "rollback_indeterminate"
        ) or (
            source is S.CONTRACT_RECEIVED
            and target is S.BLOCKED
            and reason == "quarantine_disposition_indeterminate"
        )
        if (
            context.rollout.has_exposure
            and target in {S.BLOCKED, S.PRODUCT_INPUT_REQUIRED, S.BUDGET_EXCEEDED}
            and not exposure_preserving_block
        ):
            self._deny(target, context, reason, "active rollout exposure requires rollback")
        try:
            rule = PHASE_ZERO_POLICY.rule(source, target, reason=reason)
        except TransitionDeniedError as exc:
            self._deny(target, context, reason, str(exc))
            raise AssertionError("unreachable") from exc
        if rule.permission not in actor.capabilities:
            self._deny(target, context, reason, "actor authority lacks the required capability")
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
        if (
            "subject_digest" in context.evidence
            and context.evidence["subject_digest"] != self.subject_digest
        ):
            self._deny(
                target,
                context,
                reason,
                "subject evidence does not match the lifecycle subject",
            )
        guards = rule.guards
        if target is S.STAGING_FAILED and context.rollout.has_resources:
            self._deny(
                target,
                context,
                reason,
                "staging failure requires zero rollout-owned resources",
            )
        if "budget" in guards and not self._trusted_budget_usage_valid(context):
            self._deny(target, context, reason, "trusted complete budget telemetry is required")
        admitted_resume_state: LifecycleState | None = None
        if source is S.CANARY_DEPLOYED and context.rollout.canary not in {
            "ACTIVE",
            "UNKNOWN",
        }:
            self._deny(
                target,
                context,
                reason,
                "canary exposure is not evidenced; zero exposure cannot be inferred",
            )
        if reason == "canary_mutation_indeterminate" and context.rollout.canary != "UNKNOWN":
            self._deny(
                target,
                context,
                reason,
                "indeterminate canary mutation requires unknown canary exposure",
            )
        if reason == "canary_breach" and context.rollout.canary not in {"ACTIVE", "UNKNOWN"}:
            self._deny(target, context, reason, "canary breach requires evidenced exposure")
        if "authority" in guards and not context.authority.current_at(context.observed_at):
            self._deny(target, context, reason, "contract or publisher authority is not current")
        exhausted = usage.exhausted_dimensions(self.budget_policy)
        if "budget" in guards and exhausted:
            self._deny(target, context, reason, "delivery budget is exhausted")
        if "no_blocking_finding" in guards and context.finding is not None:
            finding = context.finding
            if finding.credible and finding.blocking:
                if finding.exact_subject_digest != self.subject_digest:
                    self._deny(
                        target,
                        context,
                        reason,
                        "blocking finding subject does not match the lifecycle subject",
                    )
                self._deny(target, context, reason, "a pending blocking finding prohibits staging")
        if "drift" in guards:
            candidate_states = {
                S.DRAFT_PR_OPEN,
                S.IMPLEMENTATION_IN_PROGRESS,
                S.VERIFICATION_FAILED,
                S.REPAIR_IN_PROGRESS,
                S.REVIEW_REQUIRED,
                S.REVIEW_FAILED,
                S.PR_READY,
            }
            admitted_dispositions = (
                {"frozen-unverified-non-admissible", "disposed-unverified-non-admissible"}
                if source in candidate_states
                else {
                    "none",
                    "frozen-unverified-non-admissible",
                    "disposed-unverified-non-admissible",
                }
            )
            if context.rollout.has_resources:
                self._deny(
                    target, context, reason, "repository drift requires zero rollout resources"
                )
            if context.work.worker_leases_active or not context.work.workers_stopped:
                self._deny(target, context, reason, "repository drift workers are not quiescent")
            if context.work.mutation_capability_active:
                self._deny(
                    target,
                    context,
                    reason,
                    "repository drift mutation capability remains active",
                )
            if context.work.partial_output_disposition not in admitted_dispositions:
                self._deny(
                    target,
                    context,
                    reason,
                    "repository drift partial work has no safe disposition",
                )
            work_digest = _digest(asdict(context.work))
            if context.evidence.get(
                "work_disposition_digest"
            ) != work_digest or not self._trusted_work_evidence_valid(context):
                self._deny(
                    target,
                    context,
                    reason,
                    "repository drift work evidence is not bound to the quiesced state",
                )
        if "security_incident_block" in guards:
            artifact_digest = context.evidence.get("affected_artifact_digest", "")
            disposition_status = context.evidence.get("quarantine_disposition_status", "")
            if disposition_status not in {"FAILED", "UNKNOWN"}:
                self._deny(
                    target,
                    context,
                    reason,
                    "quarantine disposition failure must be failed or indeterminate",
                )
            if context.work.worker_leases_active or not context.work.workers_stopped:
                self._deny(target, context, reason, "security-incident workers must be quiescent")
            if context.work.mutation_capability_active:
                self._deny(
                    target,
                    context,
                    reason,
                    "security-incident mutation capability remains active",
                )
            if context.work.partial_output_disposition != "quarantined-unresolved":
                self._deny(
                    target,
                    context,
                    reason,
                    "affected artifact must remain truthfully quarantined and unresolved",
                )
            expected_disposition = _digest(
                {
                    "affected_artifact_digest": artifact_digest,
                    "subject_digest": self.subject_digest,
                    "status": disposition_status,
                }
            )
            expected_exposure = _digest(
                {
                    "affected_artifact_digest": artifact_digest,
                    "subject_digest": self.subject_digest,
                    "rollout": asdict(context.rollout),
                }
            )
            expected_retry_gate = _digest(
                {
                    "affected_artifact_digest": artifact_digest,
                    "gate": "AUTHORITATIVE_DISPOSITION_REQUIRED",
                    "subject_digest": self.subject_digest,
                }
            )
            if (
                context.evidence.get("quarantine_disposition_digest") != expected_disposition
                or context.evidence.get("exposure_digest") != expected_exposure
                or context.evidence.get("retry_gate_digest") != expected_retry_gate
            ):
                self._deny(
                    target,
                    context,
                    reason,
                    "security incident evidence is not bound to its artifact and exposure",
                )
            if not self._trusted_work_evidence_valid(context):
                self._deny(
                    target,
                    context,
                    reason,
                    "security incident requires trusted worker quiescence and revocation evidence",
                )
            admitted_resume_state = S.CONTRACT_RECEIVED
        if "safe_stop" in guards:
            if context.rollout.has_resources:
                self._deny(
                    target,
                    context,
                    reason,
                    "safe stop requires zero rollout-owned resources",
                )
            if context.work.worker_leases_active or not context.work.workers_stopped:
                self._deny(target, context, reason, "safe-stop workers must be quiescent")
            if context.work.mutation_capability_active:
                self._deny(
                    target,
                    context,
                    reason,
                    "safe-stop candidate mutation capability remains active",
                )
            if not self._trusted_work_evidence_valid(context):
                self._deny(
                    target,
                    context,
                    reason,
                    "safe-stop quiescence evidence is missing or inconsistent",
                )
            if target is S.BLOCKED:
                admitted_resume_state = {
                    (S.PR_MERGED, "post_merge_blocking_finding"): S.REPOSITORY_ANALYSED,
                    (S.STAGING_DEPLOYED, "canary_authorization_missing"): S.PR_MERGED,
                    (S.COMPLETED, "completion_evidence_unavailable"): S.PRODUCTION_DEPLOYED,
                }.get((source, reason), source)
        if "product_input" in guards:
            if context.rollout.has_resources:
                self._deny(target, context, reason, "product input requires cleanup or rollback")
            if context.work.worker_leases_active or not context.work.workers_stopped:
                self._deny(target, context, reason, "product input requires stopped workers")
            if context.work.mutation_capability_active:
                self._deny(
                    target,
                    context,
                    reason,
                    "product input requires revoked candidate mutation capability",
                )
            work_digest = _digest(asdict(context.work))
            if context.evidence.get(
                "work_disposition_digest"
            ) != work_digest or not self._trusted_work_evidence_valid(context):
                self._deny(
                    target,
                    context,
                    reason,
                    "product input work evidence is not bound to worker quiescence",
                )
        if "budget_stop" in guards:
            if not exhausted:
                self._deny(target, context, reason, "budget stop requires proven exhaustion")
            if context.work.worker_leases_active or not context.work.workers_stopped:
                self._deny(target, context, reason, "budget-stop workers must be quiescent")
            if context.work.mutation_capability_active:
                self._deny(
                    target,
                    context,
                    reason,
                    "budget-stop mutation capability remains active",
                )
            work_digest = _digest(asdict(context.work))
            if (
                not self._trusted_work_evidence_valid(context)
                or context.evidence.get("work_disposition_digest") != work_digest
            ):
                self._deny(
                    target,
                    context,
                    reason,
                    "budget-stop work evidence is not bound to worker quiescence",
                )
            if source in {
                S.IMPLEMENTATION_IN_PROGRESS,
                S.REPAIR_IN_PROGRESS,
            } and context.work.partial_output_disposition not in {
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
            if safe_resume is None:
                self._deny(
                    target,
                    context,
                    reason,
                    "budget stop has no admitted interrupted safe gate",
                )
            admitted_resume_state = safe_resume
        if "repair" in guards:
            repair_finding = context.finding
            if not _normalized_engineering_finding(
                repair_finding, self.subject_digest, accepted_for_repair=True
            ):
                self._deny(
                    target,
                    context,
                    reason,
                    "repair requires a complete accepted engineering finding",
                )
            assert repair_finding is not None
            if context.evidence.get("finding_digest") != _digest(asdict(repair_finding)):
                self._deny(
                    target,
                    context,
                    reason,
                    "repair finding evidence does not match the normalized finding",
                )
            finding_attempts = usage.repair_attempts_by_finding.get(repair_finding.finding_id, 0)
            stage_attempts = usage.repair_attempts_by_stage.get(source.value, 0)
            if (
                finding_attempts >= self.budget_policy.repair_attempts_per_finding
                or stage_attempts >= self.budget_policy.repair_attempts_per_stage
            ):
                self._deny(target, context, reason, "repair attempt limit is exhausted")
        if "blocking_finding" in guards:
            blocking_finding = context.finding
            if not _normalized_engineering_finding(
                blocking_finding, self.subject_digest, accepted_for_repair=False
            ):
                self._deny(target, context, reason, "no normalized exact-subject blocker")
            assert blocking_finding is not None
            if context.evidence.get("finding_digest") != _digest(asdict(blocking_finding)):
                self._deny(
                    target,
                    context,
                    reason,
                    "blocking finding evidence does not match the normalized finding",
                )
        if "review_clear" in guards:
            matching_review = next(
                (
                    approval
                    for approval in context.approvals
                    if approval.approval_id
                    and approval.actor
                    and approval.kind == "FORMAL_REVIEW"
                    and approval.eligible
                    and approval.active
                    and approval.subject_digest == self.subject_digest
                    and _GIT_SHA.fullmatch(approval.reviewed_commit_sha)
                    and _SHA256.fullmatch(approval.reviewed_candidate_digest)
                    and _SHA256.fullmatch(approval.review_evidence_digest)
                    and context.evidence.get("reviewed_commit_sha") == approval.reviewed_commit_sha
                    and context.evidence.get("prospective_tree_digest")
                    == approval.reviewed_candidate_digest
                    and context.evidence.get("verification_bundle_digest")
                    == approval.review_evidence_digest
                    and context.evidence.get("review_digest") == _digest(asdict(approval))
                    and self.trust_policy.formal_reviewers.get(approval.actor)
                    and self._verify_external_evidence(
                        approval.actor,
                        self.trust_policy.formal_reviewers[approval.actor],
                        _production_approval_payload(approval),
                        approval.authentication_evidence_digest,
                    )
                ),
                None,
            )
            if matching_review is None:
                self._deny(
                    target,
                    context,
                    reason,
                    "eligible formal review bound to the exact candidate is required",
                )
        if "merge_binding" in guards:
            review_binding = self._latest_review_binding()
            merge_attempt = context.mutation
            merge_result = (
                self._mutation_results.get(merge_attempt.idempotency_key)
                if merge_attempt is not None
                else None
            )
            merge_output = {
                name: context.evidence.get(name, "")
                for name in (
                    "head_commit_sha",
                    "merge_commit_sha",
                    "merge_tree_digest",
                    "merge_method_digest",
                    "merge_actor_digest",
                )
            }
            if (
                review_binding is None
                or context.evidence.get("queue_subject_digest") != self.subject_digest
                or context.evidence.get("head_commit_sha")
                != review_binding.evidence_refs.get("reviewed_commit_sha")
                or context.evidence.get("head_digest")
                != _digest(context.evidence.get("head_commit_sha", ""))
                or context.evidence.get("prospective_tree_digest")
                != review_binding.evidence_refs.get("prospective_tree_digest")
                or context.evidence.get("verification_bundle_digest")
                != review_binding.evidence_refs.get("verification_bundle_digest")
                or context.evidence.get("formal_review_digest")
                != review_binding.evidence_refs.get("review_digest")
                or merge_attempt is None
                or context.evidence.get("merge_attempt_digest") != _digest(asdict(merge_attempt))
                or merge_result is None
                or not merge_result.successful
                or context.evidence.get("merge_result_digest") != merge_result.result_digest
                or merge_result.result_digest != _digest(merge_output)
                or context.evidence.get("merge_tree_digest")
                != context.evidence.get("prospective_tree_digest")
            ):
                self._deny(
                    target,
                    context,
                    reason,
                    "native merge does not match the persisted exact-candidate review binding",
                )
        if "integrated_merge" in guards:
            merge_binding = self._latest_merge_binding()
            if merge_binding is None or context.evidence.get(
                "merge_digest"
            ) != merge_binding.evidence_refs.get("merge_result_digest"):
                self._deny(
                    target,
                    context,
                    reason,
                    "staging is not bound to the adapter-attested integrated merge result",
                )
        if "canary_binding" in guards:
            attempt = context.mutation
            attempt_digest = _digest(asdict(attempt)) if attempt is not None else ""
            result = (
                self._mutation_results.get(attempt.idempotency_key) if attempt is not None else None
            )
            expected_status = _digest(
                {
                    "canary_id_digest": context.evidence.get("canary_id_digest", ""),
                    "deployment_attempt_digest": attempt_digest,
                    "deployment_result_digest": (
                        result.result_digest if result is not None else None
                    ),
                    "subject_digest": self.subject_digest,
                    "status": "ACTIVE",
                }
            )
            if (
                context.rollout.canary != "ACTIVE"
                or any(not context.evidence.get(name) for name in _CANARY_ROLLOUT_SUBJECT_FIELDS)
                or context.evidence.get("canary_attempt_digest") != attempt_digest
                or context.evidence.get("canary_status_digest") != expected_status
            ):
                self._deny(
                    target,
                    context,
                    reason,
                    "canary admission requires exact active canary proof",
                )
        if "active_canary" in guards:
            canary_binding = self._latest_canary_binding()
            proof_fields = (
                "subject_digest",
                "canary_id_digest",
                "canary_attempt_digest",
                "canary_status_digest",
            )
            rollout_subject_fields = (
                _CANARY_ROLLOUT_SUBJECT_FIELDS
                if target in {S.PRODUCTION_APPROVAL_REQUIRED, S.PRODUCTION_DEPLOYED}
                else ()
            )
            allowed_observed_status = (
                {"ACTIVE", "UNKNOWN"} if target is S.ROLLBACK_IN_PROGRESS else {"ACTIVE"}
            )
            if (
                canary_binding is None
                or context.rollout.canary not in allowed_observed_status
                or any(
                    context.evidence.get(name) != canary_binding.evidence_refs.get(name)
                    for name in (*proof_fields, *rollout_subject_fields)
                )
            ):
                self._deny(
                    target,
                    context,
                    reason,
                    "transition requires replayable exact-subject canary artifact proof",
                )
        if "production_approval" in guards and not any(
            approval.approval_id
            and approval.actor
            and approval.kind == "PRODUCTION"
            and approval.eligible
            and approval.active
            and approval.subject_digest == self.subject_digest
            and _GIT_SHA.fullmatch(approval.reviewed_commit_sha)
            and _SHA256.fullmatch(approval.reviewed_candidate_digest)
            and _SHA256.fullmatch(approval.review_evidence_digest)
            and approval.reviewed_commit_sha == context.evidence.get("merge_commit_sha")
            and approval.reviewed_candidate_digest == context.evidence.get("artifact_digest")
            and approval.review_evidence_digest
            == _production_approval_scope_digest(context.evidence)
            and context.evidence.get("production_approval_digest") == _digest(asdict(approval))
            and self.trust_policy.production_approvers.get(approval.actor)
            and self._verify_external_evidence(
                approval.actor,
                self.trust_policy.production_approvers[approval.actor],
                _production_approval_payload(approval),
                approval.authentication_evidence_digest,
            )
            for approval in context.approvals
        ):
            self._deny(
                target,
                context,
                reason,
                "a live production approval bound to the exact rollout is required",
            )
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
            if (
                attempt.action in _MUTATION_SUBJECT_FIELDS
                and attempt.step_plan_digest
                != mutation_subject_digest(
                    attempt.action,
                    (
                        {
                            **context.evidence,
                            "subject_digest": context.evidence.get(
                                "subject_digest", self.subject_digest
                            ),
                        }
                        if attempt.action == "rollback"
                        else context.evidence
                    ),
                )
            ):
                self._deny(
                    target,
                    context,
                    reason,
                    "mutation step plan is not bound to the exact external-effect subject",
                )
            try:
                self._require_prejournaled(attempt)
            except TransitionDeniedError as exc:
                self._deny(target, context, reason, str(exc))
            starts_safety_action = target is S.ROLLBACK_IN_PROGRESS
            result = self._mutation_results.get(attempt.idempotency_key)
            if not starts_safety_action and (
                result is None
                or not result.successful
                or attempt.idempotency_key not in self._verified_mutation_result_keys
            ):
                self._deny(
                    target,
                    context,
                    reason,
                    "a successful exact-attempt mutation result is required",
                )
            if result is not None and result.attempt_id != attempt.attempt_id:
                self._deny(target, context, reason, "mutation result attempt does not match")
            result_evidence_name = {
                "enqueue_merge": "merge_result_digest",
                "deploy_staging": "staging_result_digest",
                "deploy_canary": "canary_result_digest",
                "deploy_production": "production_result_digest",
                "cleanup_staging": "cleanup_result_digest",
                "rollback": "rollback_result_digest",
                "teardown_canary": "canary_teardown_digest",
            }.get(attempt.action)
            if (
                not starts_safety_action
                and result is not None
                and result.successful
                and result_evidence_name in rule.required_evidence
                and context.evidence.get(result_evidence_name) != result.result_digest
            ):
                self._deny(
                    target,
                    context,
                    reason,
                    "transition evidence does not match the persisted mutation result",
                )
            attempt_evidence_name = {
                "open_draft_pr": "governance_attempt_digest",
                "enqueue_merge": "merge_attempt_digest",
                "deploy_staging": "staging_attempt_digest",
                "deploy_canary": "canary_attempt_digest",
                "deploy_production": "production_attempt_digest",
                "cleanup_staging": "cleanup_attempt_digest",
                "rollback": "rollback_attempt_digest",
            }.get(attempt.action)
            if attempt_evidence_name in rule.required_evidence and context.evidence.get(
                str(attempt_evidence_name)
            ) != _digest(asdict(attempt)):
                self._deny(
                    target,
                    context,
                    reason,
                    "transition mutation attempt evidence does not match",
                )
        if "safety_block" in guards:
            attempt = context.mutation
            if attempt is None or rule.mutation_action != attempt.action:
                self._deny(target, context, reason, "blocked safety action is not attributable")
            if context.evidence.get("original_attempt_digest") != _digest(asdict(attempt)):
                self._deny(target, context, reason, "blocked safety attempt digest does not match")
            try:
                self._require_prejournaled(attempt)
            except TransitionDeniedError as exc:
                self._deny(target, context, reason, str(exc))
            expected_resume = {
                "rollback": S.ROLLBACK_IN_PROGRESS,
                "cleanup_staging": S.STAGING_FAILED,
            }[attempt.action]
            admitted_resume_state = expected_resume
        if {"safety", "safety_resume"} & guards and not usage.safety_available(self.budget_policy):
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
                self._require_prejournaled(attempt)
            except TransitionDeniedError as exc:
                self._deny(target, context, reason, str(exc))
        if "zero_exposure" in guards:
            attempt = context.mutation
            result = (
                self._mutation_results.get(attempt.idempotency_key) if attempt is not None else None
            )
            if context.rollout.canary not in {"NONE", "REMOVED"} or (
                context.rollout.changed_production not in {"NONE", "REMOVED"}
            ):
                self._deny(
                    target,
                    context,
                    reason,
                    "rollback has unresolved exposure",
                )
            attempt_digest = _digest(asdict(attempt)) if attempt is not None else ""
            result_digest = result.result_digest if result is not None else None
            expected_exposure = _digest(
                {
                    "subject_digest": self.subject_digest,
                    "rollback_attempt_digest": attempt_digest,
                    "rollback_result_digest": result_digest,
                    "canary": context.rollout.canary,
                    "changed_production": context.rollout.changed_production,
                }
            )
            if context.evidence.get("rollback_exposure_digest") != expected_exposure:
                self._deny(
                    target,
                    context,
                    reason,
                    "rollback exposure evidence is not bound to the exact attempt and subject",
                )
        if "completion" in guards and self.completion_claim_active:
            self._deny(target, context, reason, "completion claim is already active")
        if "completion" in guards:
            review_binding = self._latest_review_binding()
            merge_binding = self._latest_merge_binding()
            deployed_release_sha = (
                merge_binding.evidence_refs.get("merge_commit_sha")
                if merge_binding is not None
                else review_binding.evidence_refs.get("reviewed_commit_sha")
                if review_binding is not None
                else None
            )
            invalidating_reasons = {"blocking_finding", "check_stale", "head_changed"}
            invalidated = review_binding is not None and any(
                event.sequence > review_binding.sequence
                and event.outcome == "APPLIED"
                and event.reason in invalidating_reasons
                for event in self.events
            )
            if (
                review_binding is None
                or invalidated
                or context.evidence.get("release_sha") != deployed_release_sha
                or context.evidence.get("reviewed_commit_sha")
                != review_binding.evidence_refs.get("reviewed_commit_sha")
                or context.evidence.get("reviewed_candidate_digest")
                != review_binding.evidence_refs.get("prospective_tree_digest")
                or context.evidence.get("review_evidence_digest")
                != review_binding.evidence_refs.get("verification_bundle_digest")
                or context.evidence.get("evidence_bundle_digest")
                != review_binding.evidence_refs.get("verification_bundle_digest")
                or review_binding.evidence_refs.get("subject_digest") != self.subject_digest
            ):
                self._deny(
                    target,
                    context,
                    reason,
                    "completion is not bound to the exact reviewed candidate and evidence",
                )
        if "revoke_completion" in guards:
            completion_event = next(
                (
                    event
                    for event in reversed(self.events)
                    if event.kind == "COMPLETION_CLAIMED" and event.outcome == "APPLIED"
                ),
                None,
            )
            monitor_identity = _digest(
                {
                    "actor_id": actor.actor_id,
                    "role": actor.role,
                    "subject_digest": actor.subject_digest,
                }
            )
            trigger_digest = context.evidence.get(
                "incident_digest", context.evidence.get("safe_state_digest", "")
            )
            expected_invalidation = _digest(
                {
                    "completion_event_digest": (
                        completion_event.event_digest if completion_event is not None else ""
                    ),
                    "monitor_authentication_evidence_digest": (
                        actor.authentication_evidence_digest
                    ),
                    "monitor_identity_digest": monitor_identity,
                    "subject_digest": self.subject_digest,
                    "trigger_digest": trigger_digest,
                }
            )
            if (
                not self.completion_claim_active
                or completion_event is None
                or "lifecycle.completion.revoke" not in actor.capabilities
                or not context.authority.current_at(context.observed_at)
                or context.evidence.get("completion_event_digest") != completion_event.event_digest
                or context.evidence.get("monitor_identity_digest") != monitor_identity
                or context.evidence.get("monitor_authentication_evidence_digest")
                != actor.authentication_evidence_digest
                or context.evidence.get("invalidation_digest") != expected_invalidation
            ):
                self._deny(
                    target,
                    context,
                    reason,
                    "completion revocation lacks an active claim and attributable monitor evidence",
                )

        if "safe_stop" in guards and source is S.PR_READY and target is S.BLOCKED:
            review_binding = self._latest_review_binding()
            if review_binding is None:
                self._deny(
                    target,
                    context,
                    reason,
                    "PR_READY stop has no persisted review inputs to bind for resume",
                )
            review_inputs = {
                name: review_binding.evidence_refs.get(name, "")
                for name in (
                    "reviewed_commit_sha",
                    "prospective_tree_digest",
                    "verification_bundle_digest",
                    "review_digest",
                )
            }
            event_evidence.update(review_inputs)
            event_evidence["resume_binding_digest"] = _digest(review_inputs)

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
        if {"safety", "safety_resume"} & guards:
            usage = replace(usage, safety_units_used=usage.safety_units_used + 1)
        event = self._append(
            kind=kind,
            outcome="APPLIED",
            source=source,
            target=target,
            reason=reason,
            actor=context.actor.actor_id,
            evidence_refs=event_evidence,
            observed_at=context.observed_at,
            budget_usage=usage,
            resume_state=admitted_resume_state,
        )
        self._state = target
        self._budget_usage = usage
        if kind == "COMPLETION_CLAIMED":
            self._completion_claim_active = True
        elif kind == "COMPLETION_REVOKED":
            self._completion_claim_active = False
        return event

    def prejournal_mutation(self, attempt: MutationAttempt) -> MutationAttempt:
        """Durably bind a complete mutation plan before any adapter may run."""

        if attempt.subject_digest != self.subject_digest:
            raise TransitionDeniedError("mutation attempt subject does not match")
        self._register_mutation(attempt)
        return attempt

    def _require_prejournaled(self, attempt: MutationAttempt) -> None:
        persisted = self._read_mutation_attempts().get(attempt.idempotency_key)
        if persisted is None:
            raise TransitionDeniedError("mutation attempt is not durably pre-journaled")
        if persisted != attempt:
            raise TransitionDeniedError(
                "idempotency key is already bound to a different complete mutation plan"
            )

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
        adapter_evidence: AdapterResultEvidence | None = None,
    ) -> MutationResult:
        """Serialize result sealing so one exact mutation receives one outcome."""

        with self._operation_lock:
            return self._record_mutation_result_locked(
                attempt,
                status=status,
                result_digest=result_digest,
                adapter_evidence=adapter_evidence,
            )

    def _record_mutation_result_locked(
        self,
        attempt: MutationAttempt,
        *,
        status: str,
        result_digest: str | None,
        adapter_evidence: AdapterResultEvidence | None,
    ) -> MutationResult:
        if status not in {"SUCCEEDED", "FAILED", "UNKNOWN"}:
            raise TransitionDeniedError("mutation result status is not admitted")
        if attempt.subject_digest != self.subject_digest:
            raise TransitionDeniedError("mutation attempt subject does not match")
        if status == "SUCCEEDED" and (
            result_digest is None or _SHA256.fullmatch(result_digest) is None
        ):
            raise TransitionDeniedError("successful mutation requires a canonical result digest")
        self._require_prejournaled(attempt)
        prior = self._mutation_results.get(attempt.idempotency_key)
        if prior is not None:
            if prior.attempt_id != attempt.attempt_id:
                raise TransitionDeniedError("mutation result attempt does not match")
            if prior.status != status or prior.result_digest != result_digest:
                raise TransitionDeniedError("mutation result is already sealed")
            return prior
        if (
            adapter_evidence is None
            or not adapter_evidence.adapter_id
            or not adapter_evidence.role
            or not adapter_evidence.authenticated
            or "lifecycle.mutation.result.record" not in adapter_evidence.capabilities
            or adapter_evidence.subject_digest != self.subject_digest
            or adapter_evidence.subject_digest != attempt.subject_digest
            or adapter_evidence.attempt_id != attempt.attempt_id
            or adapter_evidence.idempotency_key != attempt.idempotency_key
            or adapter_evidence.action != attempt.action
            or adapter_evidence.step_plan_digest != attempt.step_plan_digest
            or adapter_evidence.status != status
            or adapter_evidence.result_digest != result_digest
            or self.trust_policy.adapter_authorities.get(adapter_evidence.adapter_id)
            != adapter_evidence.authority_digest
            or not self._verify_external_evidence(
                adapter_evidence.adapter_id,
                adapter_evidence.authority_digest,
                _adapter_result_evidence_payload(adapter_evidence),
                adapter_evidence.authentication_evidence_digest,
            )
        ):
            raise TransitionDeniedError(
                "trusted adapter authority for the authenticated exact attempt is required"
            )
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
            actor=adapter_evidence.adapter_id,
            evidence_refs={
                "attempt_id": attempt.attempt_id,
                "idempotency_key": attempt.idempotency_key,
                "result_digest": result_digest or "UNKNOWN",
                "adapter_id": adapter_evidence.adapter_id,
                "adapter_role": adapter_evidence.role,
                "adapter_capabilities_json": json.dumps(
                    sorted(adapter_evidence.capabilities), separators=(",", ":")
                ),
                "adapter_authority_digest": adapter_evidence.authority_digest,
                "adapter_step_plan_digest": adapter_evidence.step_plan_digest,
                "adapter_authentication_evidence_digest": (
                    adapter_evidence.authentication_evidence_digest
                ),
            },
            observed_at="",
            detail=status,
        )
        self._mutation_results[attempt.idempotency_key] = result
        self._verified_mutation_result_keys.add(attempt.idempotency_key)
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
        with self._operation_lock, self._exclusive_lock():
            if subject_digest != self.subject_digest:
                raise TransitionDeniedError(
                    "observation subject does not match the lifecycle subject"
                )
            if not source or not payload_digest or not signature or not observed_at:
                raise TransitionDeniedError("observation is not digest-bound and attributable")
            current = self.state
            return self._append_locked(
                kind="OBSERVATION",
                outcome="RECORDED",
                source=current,
                target=current,
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
        """Serialize resume admission with every other same-instance transition."""

        with self._operation_lock:
            return self._resume_locked(context)

    def _resume_locked(self, context: TransitionContext) -> LifecycleEvent:
        """Resume only the exact safe gate recorded by a prior stop event."""

        context = replace(
            context,
            evidence=dict(context.evidence),
            budget_usage=BudgetUsage(
                counters=dict(context.budget_usage.counters),
                repair_attempts_by_finding=dict(context.budget_usage.repair_attempts_by_finding),
                repair_attempts_by_stage=dict(context.budget_usage.repair_attempts_by_stage),
                safety_units_used=context.budget_usage.safety_units_used,
            ),
        )
        actor = context.actor
        if (
            not actor.actor_id
            or not actor.role
            or not actor.authenticated
            or "lifecycle.transition" not in actor.capabilities
            or actor.subject_digest != self.subject_digest
            or actor.authority_digest != context.authority.digest
            or not context.authority.digest_valid
            or _SHA256.fullmatch(actor.authority_digest) is None
            or not self._verify_external_evidence(
                actor.actor_id,
                actor.authority_digest,
                _actor_authentication_payload(actor),
                actor.authentication_evidence_digest,
            )
        ):
            self._deny(self.state, context, "resume", "actor authority is invalid for this subject")
        if self.state not in {S.BLOCKED, S.BUDGET_EXCEEDED}:
            self._deny(self.state, context, "resume", "only a stopped lifecycle can resume")
        stopped_event = next(
            (
                event
                for event in reversed(self.events)
                if event.outcome == "APPLIED"
                and event.target is self.state
                and event.resume_state is not None
            ),
            None,
        )
        if stopped_event is None or stopped_event.resume_state is None:
            self._deny(
                self.state,
                context,
                "resume",
                "the stopped lifecycle has no recorded safe state",
            )
        recorded = stopped_event.resume_state
        try:
            rule = PHASE_ZERO_POLICY.rule(self.state, recorded, reason="recorded_safe_resume")
        except TransitionDeniedError as exc:
            self._deny(recorded, context, "resume", str(exc))
            raise AssertionError("unreachable") from exc
        if rule.permission not in actor.capabilities:
            self._deny(recorded, context, "resume", "resume authority lacks required capability")
        missing = [name for name in rule.required_evidence if not context.evidence.get(name)]
        if missing:
            self._deny(
                recorded,
                context,
                "resume",
                "required resume evidence is missing: " + ", ".join(sorted(missing)),
            )
        malformed = _malformed_evidence(context.evidence, rule.required_evidence)
        if malformed:
            self._deny(
                recorded,
                context,
                "resume",
                "resume evidence is not canonical: " + ", ".join(malformed),
            )
        if context.evidence.get("subject_digest") != self.subject_digest:
            self._deny(recorded, context, "resume", "resume subject evidence does not match")
        if recorded is S.PR_READY:
            review_inputs = {
                name: context.evidence.get(name, "")
                for name in (
                    "reviewed_commit_sha",
                    "prospective_tree_digest",
                    "verification_bundle_digest",
                    "review_digest",
                )
            }
            if (
                _GIT_SHA.fullmatch(review_inputs["reviewed_commit_sha"]) is None
                or any(
                    _SHA256.fullmatch(review_inputs[name]) is None
                    for name in (
                        "prospective_tree_digest",
                        "verification_bundle_digest",
                        "review_digest",
                    )
                )
                or _digest(review_inputs)
                != stopped_event.evidence_refs.get("resume_binding_digest")
                or context.evidence.get("unchanged_inputs_digest")
                != stopped_event.evidence_refs.get("resume_binding_digest")
                or not self._trusted_repository_observation_valid(context, review_inputs)
            ):
                self._deny(
                    recorded,
                    context,
                    "resume",
                    "PR_READY resume lacks a fresh trusted repository observation",
                )
        if (
            stopped_event.reason == "post_merge_blocking_finding"
            and _SHA256.fullmatch(context.evidence.get("finding_disposition_digest", "")) is None
        ):
            self._deny(
                recorded,
                context,
                "resume",
                "post-merge finding disposition evidence is required before resume",
            )
        if stopped_event.reason == "quarantine_disposition_indeterminate":
            affected_artifact = stopped_event.evidence_refs.get("affected_artifact_digest", "")
            disposition_authority = context.actor.authentication_evidence_digest
            expected_disposition = _digest(
                {
                    "affected_artifact_digest": affected_artifact,
                    "authority_evidence_digest": disposition_authority,
                    "subject_digest": self.subject_digest,
                    "status": "AUTHORITATIVELY_DISPOSED",
                }
            )
            if (
                "lifecycle.quarantine.disposition" not in context.actor.capabilities
                or context.evidence.get("affected_artifact_digest") != affected_artifact
                or context.evidence.get("quarantine_disposition_status")
                != "AUTHORITATIVELY_DISPOSED"
                or context.evidence.get("quarantine_disposition_authority_digest")
                != disposition_authority
                or context.evidence.get("quarantine_disposition_evidence_digest")
                != expected_disposition
            ):
                self._deny(
                    recorded,
                    context,
                    "resume",
                    "authoritative exact-artifact quarantine disposition evidence is required",
                )
        if context.rollout.has_resources:
            self._deny(
                recorded, context, "resume", "ordinary resume requires zero rollout resources"
            )
        if context.work.worker_leases_active or not context.work.workers_stopped:
            self._deny(recorded, context, "resume", "ordinary resume requires stopped workers")
        if context.work.mutation_capability_active:
            self._deny(
                recorded,
                context,
                "resume",
                "ordinary resume requires revoked candidate mutation capability",
            )
        if not context.authority.current_at(context.observed_at):
            self._deny(recorded, context, "resume", "authority must be current before resume")
        if context.budget_usage.safety_units_used != self.budget_usage.safety_units_used:
            self._deny(
                recorded,
                context,
                "resume",
                "reserved safety usage is controlled only by the lifecycle authority",
            )
        if not self._trusted_budget_usage_valid(context):
            self._deny(
                recorded,
                context,
                "resume",
                "trusted complete budget telemetry is required before resume",
            )
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
            actor=context.actor.actor_id,
            evidence_refs=dict(context.evidence),
            observed_at=context.observed_at,
            budget_usage=usage,
            resume_state=recorded,
        )
        self._state = recorded
        self._budget_usage = usage
        return event
