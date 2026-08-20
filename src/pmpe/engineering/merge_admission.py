"""Native compare-and-swap merge admission and asynchronous race outcomes."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Literal

from pmpe.contracts.digest import canonical_digest


@dataclass(frozen=True)
class RequiredCheck:
    name: str
    subject_sha: str
    input_digest: str
    status: str
    observed_at: str
    event: str = "pull_request"
    enqueue_digest: str = ""


@dataclass(frozen=True)
class FormalReview:
    review_id: str
    actor: str
    subject_sha: str
    state: str
    submitted_at: str
    eligible: bool


@dataclass(frozen=True)
class BlockingFinding:
    finding_id: str
    source: str
    subject_sha: str
    severity: str
    credible: bool
    blocking: bool
    normalized_at: str
    disposition: str = "OPEN"
    resolution_digest: str = ""


@dataclass(frozen=True)
class MergeSnapshot:
    pr_head_sha: str
    protected_base_sha: str
    prospective_merge_tree_digest: str
    repository_rules_digest: str
    architecture_policy_digest: str
    toolchain_policy_digest: str
    environment_profile_digest: str
    security_policy_digest: str
    verification_policy_digest: str
    evidence_policy_digest: str
    authority_digest: str
    finding_high_watermark_digest: str
    pending_unclassified_findings: int
    required_check_names: tuple[str, ...]
    checks: tuple[RequiredCheck, ...]
    reviews: tuple[FormalReview, ...]
    findings: tuple[BlockingFinding, ...]
    merge_queue_enforced: bool
    bypass_used: bool = False

    @property
    def exact_input_digest(self) -> str:
        return canonical_digest(
            {
                "pr_head_sha": self.pr_head_sha,
                "protected_base_sha": self.protected_base_sha,
                "prospective_merge_tree_digest": self.prospective_merge_tree_digest,
                "repository_rules_digest": self.repository_rules_digest,
                "architecture_policy_digest": self.architecture_policy_digest,
                "toolchain_policy_digest": self.toolchain_policy_digest,
                "environment_profile_digest": self.environment_profile_digest,
                "security_policy_digest": self.security_policy_digest,
                "verification_policy_digest": self.verification_policy_digest,
                "evidence_policy_digest": self.evidence_policy_digest,
            }
        )


@dataclass(frozen=True)
class EnqueueToken:
    snapshot_digest: str
    exact_input_digest: str
    enqueued_at: str
    invalidation_boundary: str
    enqueue_digest: str


@dataclass(frozen=True)
class MergeDecision:
    admitted: bool
    outcome: str
    rollout_allowed: bool
    reasons: tuple[str, ...]
    incident: bool = False


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must carry a timezone")
    return parsed


def _snapshot_digest(snapshot: MergeSnapshot) -> str:
    return canonical_digest(asdict(snapshot))


def _blocking_finding(finding: BlockingFinding) -> bool:
    severity = finding.severity.upper()
    normalized_blocker = (
        finding.credible
        and finding.blocking
        and severity
        in {
            "CRITICAL",
            "HIGH",
            "MEDIUM",
        }
    )
    return normalized_blocker and finding.disposition not in {"RESOLVED", "REJECTED_WITH_EVIDENCE"}


def _validate_snapshot(
    snapshot: MergeSnapshot,
    *,
    invalidation_boundary: str,
    as_of: str,
    queue_timeout_seconds: int,
    enqueue_digest: str = "",
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not snapshot.merge_queue_enforced:
        reasons.append("native merge queue or equivalent CAS gate is unavailable")
    if snapshot.bypass_used:
        reasons.append("merge bypass was used")
    if snapshot.pending_unclassified_findings:
        reasons.append("finding normalization is incomplete")
    if any(_blocking_finding(finding) for finding in snapshot.findings):
        reasons.append("an exact-subject blocking finding is unresolved")
    if any(
        review.subject_sha == snapshot.pr_head_sha and review.state == "CHANGES_REQUESTED"
        for review in snapshot.reviews
    ):
        reasons.append("formal changes are requested for the exact head")

    boundary = _time(invalidation_boundary)
    valid_approvals = [
        review
        for review in snapshot.reviews
        if review.eligible
        and review.state == "APPROVED"
        and review.subject_sha == snapshot.pr_head_sha
        and _time(review.submitted_at) > boundary
    ]
    if not valid_approvals:
        reasons.append("no fresh eligible formal approval after the invalidation boundary")

    by_name = {check.name: check for check in snapshot.checks}
    now = _time(as_of)
    for name in snapshot.required_check_names:
        check = by_name.get(name)
        if check is None:
            reasons.append(f"required check {name} is missing")
            continue
        if check.subject_sha != snapshot.pr_head_sha:
            reasons.append(f"required check {name} is bound to the wrong subject")
        if check.input_digest != snapshot.exact_input_digest:
            reasons.append(f"required check {name} has stale policy/toolchain inputs")
        if check.event == "merge_group":
            if check.enqueue_digest != enqueue_digest:
                reasons.append(f"merge-group check {name} is from another enqueue")
            if check.status not in {"PENDING", "IN_PROGRESS", "SUCCESS"}:
                reasons.append(f"merge-group check {name} ended as {check.status}")
            if now - _time(check.observed_at) > timedelta(seconds=queue_timeout_seconds):
                reasons.append(f"merge-group check {name} exceeded its freshness window")
        elif check.status != "SUCCESS":
            reasons.append(f"required check {name} is {check.status}")
    return tuple(reasons)


def enqueue(
    snapshot: MergeSnapshot,
    *,
    enqueued_at: str,
    invalidation_boundary: str,
    queue_timeout_seconds: int = 1800,
) -> EnqueueToken:
    reasons = _validate_snapshot(
        snapshot,
        invalidation_boundary=invalidation_boundary,
        as_of=enqueued_at,
        queue_timeout_seconds=queue_timeout_seconds,
    )
    if reasons:
        raise ValueError("; ".join(reasons))
    snapshot_digest = _snapshot_digest(snapshot)
    enqueue_digest = canonical_digest(
        {
            "snapshot_digest": snapshot_digest,
            "exact_input_digest": snapshot.exact_input_digest,
            "enqueued_at": enqueued_at,
            "invalidation_boundary": invalidation_boundary,
        }
    )
    return EnqueueToken(
        snapshot_digest,
        snapshot.exact_input_digest,
        enqueued_at,
        invalidation_boundary,
        enqueue_digest,
    )


def linearize_merge(
    token: EnqueueToken,
    current: MergeSnapshot,
    *,
    observed_merge_sha: str,
    observed_merge_tree_digest: str,
    merged_at: str,
    native_gate_authorized: bool = True,
    queue_timeout_seconds: int = 1800,
) -> MergeDecision:
    reasons = list(
        _validate_snapshot(
            current,
            invalidation_boundary=token.invalidation_boundary,
            as_of=merged_at,
            queue_timeout_seconds=queue_timeout_seconds,
            enqueue_digest=token.enqueue_digest,
        )
    )
    if current.exact_input_digest != token.exact_input_digest:
        reasons.append("reviewed head/base/tree or repository policy changed after enqueue")
    if not native_gate_authorized:
        reasons.append("native gate integrity or authorization failed")
    if not observed_merge_sha:
        reasons.append("observed merge SHA is absent")
    if observed_merge_tree_digest != current.prospective_merge_tree_digest:
        reasons.append("observed merge tree differs from the reviewed prospective tree")
    if reasons:
        return MergeDecision(False, "MERGE_INCIDENT", False, tuple(reasons), incident=True)
    return MergeDecision(True, "PR_MERGED", True, ())


ExternalRaceKind = Literal["AUTHORITY_REVOKED", "BLOCKING_FINDING"]


def resolve_external_race(
    *,
    kind: ExternalRaceKind,
    external_event_at: str,
    native_merge_at: str | None,
    dequeue_completed_at: str | None,
) -> MergeDecision:
    event_time = _time(external_event_at)
    merge_time = _time(native_merge_at) if native_merge_at else None
    dequeue_time = _time(dequeue_completed_at) if dequeue_completed_at else None
    if merge_time is None or (dequeue_time is not None and dequeue_time <= merge_time):
        outcome = "PRODUCT_INPUT_REQUIRED" if kind == "AUTHORITY_REVOKED" else "REVIEW_FAILED"
        return MergeDecision(False, outcome, False, ("native admission was dequeued",))
    if merge_time >= event_time:
        outcome = (
            "PR_MERGED_PRODUCT_INPUT_BLOCKED"
            if kind == "AUTHORITY_REVOKED"
            else "PR_MERGED_REMEDIATION_REQUIRED"
        )
        return MergeDecision(
            True,
            outcome,
            False,
            (
                "native merge won the external-event race; integration is retained, "
                "rollout forbidden",
            ),
        )
    return MergeDecision(True, "PR_MERGED", True, ())
