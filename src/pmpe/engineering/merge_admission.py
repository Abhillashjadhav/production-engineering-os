"""Native compare-and-swap merge admission and asynchronous race outcomes."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from pmpe.contracts.digest import canonical_digest

_GIT_SHA = re.compile(r"^[0-9a-f]{40,64}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
EnqueueTokenSigner = Callable[[str, str, Mapping[str, object]], str]
EnqueueTokenAuthenticator = Callable[[str, str, Mapping[str, object], str], bool]


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
    source_authority_digest: str
    authentication_evidence_digest: str
    disposition: str = "OPEN"
    resolution_digest: str = ""


@dataclass(frozen=True)
class GovernedMergePolicy:
    """Trusted repository-policy input, independent of a candidate snapshot."""

    repository_rules_digest: str
    required_check_names: tuple[str, ...]

    def __post_init__(self) -> None:
        if not _DIGEST.fullmatch(self.repository_rules_digest):
            raise ValueError("governed repository-rules digest is malformed")
        if not self.required_check_names:
            raise ValueError("governed merge policy must name required checks")
        if any(not name.strip() for name in self.required_check_names):
            raise ValueError("governed required-check names cannot be empty")
        if len(set(self.required_check_names)) != len(self.required_check_names):
            raise ValueError("governed required-check names are duplicated")


def load_governed_merge_policy(path: Path) -> GovernedMergePolicy:
    """Load required checks and a content digest from the committed policy file."""
    text = Path(path).read_text()
    names: list[str] = []
    in_required_checks = False
    for line in text.splitlines():
        if line == "required_checks:":
            in_required_checks = True
            continue
        if in_required_checks and line.startswith("  - "):
            names.append(line.removeprefix("  - ").strip())
            continue
        if in_required_checks and line and not line.startswith((" ", "#")):
            break
    return GovernedMergePolicy(canonical_digest({"content": text}), tuple(names))


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
    authority_digest: str
    finding_high_watermark_digest: str
    merge_group_check_names: tuple[str, ...]
    issuer_id: str
    issuer_authority_digest: str
    authentication_evidence_digest: str
    enqueued_at: str
    invalidation_boundary: str
    enqueue_digest: str


def enqueue_token_authentication_payload(token: EnqueueToken) -> dict[str, object]:
    payload = asdict(token)
    payload.pop("authentication_evidence_digest")
    return payload


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
        and bool(_DIGEST.fullmatch(finding.source_authority_digest))
        and bool(_DIGEST.fullmatch(finding.authentication_evidence_digest))
        and severity
        in {
            "CRITICAL",
            "HIGH",
            "MEDIUM",
        }
    )
    resolved = finding.disposition in {"RESOLVED", "REJECTED_WITH_EVIDENCE"} and bool(
        _DIGEST.fullmatch(finding.resolution_digest)
    )
    return normalized_blocker and not resolved


def _validate_snapshot(
    snapshot: MergeSnapshot,
    *,
    governed_policy: GovernedMergePolicy,
    invalidation_boundary: str,
    as_of: str,
    queue_timeout_seconds: int,
    enqueue_digest: str = "",
    linearizing: bool = False,
) -> tuple[str, ...]:
    reasons: list[str] = []
    digest_fields = (
        snapshot.prospective_merge_tree_digest,
        snapshot.repository_rules_digest,
        snapshot.architecture_policy_digest,
        snapshot.toolchain_policy_digest,
        snapshot.environment_profile_digest,
        snapshot.security_policy_digest,
        snapshot.verification_policy_digest,
        snapshot.evidence_policy_digest,
        snapshot.authority_digest,
        snapshot.finding_high_watermark_digest,
    )
    if not _GIT_SHA.fullmatch(snapshot.pr_head_sha) or not _GIT_SHA.fullmatch(
        snapshot.protected_base_sha
    ):
        reasons.append("merge snapshot has a malformed head or protected-base SHA")
    if any(not _DIGEST.fullmatch(value) for value in digest_fields):
        reasons.append("merge snapshot has a malformed content or policy digest")
    if snapshot.repository_rules_digest != governed_policy.repository_rules_digest:
        reasons.append("snapshot repository rules differ from the governed merge policy")
    if snapshot.required_check_names != governed_policy.required_check_names:
        reasons.append("snapshot required checks differ from the governed merge policy")
    if not snapshot.merge_queue_enforced:
        reasons.append("native merge queue or equivalent CAS gate is unavailable")
    if snapshot.bypass_used:
        reasons.append("merge bypass was used")
    if snapshot.pending_unclassified_findings != 0:
        reasons.append("finding normalization is incomplete")
    if any(
        finding.subject_sha == snapshot.pr_head_sha and _blocking_finding(finding)
        for finding in snapshot.findings
    ):
        reasons.append("an exact-subject blocking finding is unresolved")
    if any(
        review.review_id
        and review.actor
        and review.eligible
        and review.subject_sha == snapshot.pr_head_sha
        and review.state == "CHANGES_REQUESTED"
        for review in snapshot.reviews
    ):
        reasons.append("formal changes are requested for the exact head")

    boundary = _time(invalidation_boundary)
    valid_approvals = [
        review
        for review in snapshot.reviews
        if review.review_id
        and review.actor
        and review.eligible
        and review.state == "APPROVED"
        and review.subject_sha == snapshot.pr_head_sha
        and _time(review.submitted_at) > boundary
        and _time(review.submitted_at) <= _time(as_of)
    ]
    if not valid_approvals:
        reasons.append("no fresh eligible formal approval after the invalidation boundary")

    by_name = {check.name: check for check in snapshot.checks}
    if len(by_name) != len(snapshot.checks):
        reasons.append("required check names are duplicated")
    now = _time(as_of)
    for name in governed_policy.required_check_names:
        check = by_name.get(name)
        if check is None:
            reasons.append(f"required check {name} is missing")
            continue
        if check.subject_sha != snapshot.pr_head_sha:
            reasons.append(f"required check {name} is bound to the wrong subject")
        if check.input_digest != snapshot.exact_input_digest:
            reasons.append(f"required check {name} has stale policy/toolchain inputs")
        if check.event == "merge_group":
            if linearizing and check.enqueue_digest != enqueue_digest:
                reasons.append(f"merge-group check {name} is from another enqueue")
            allowed_statuses = {"SUCCESS"} if linearizing else {"PENDING", "IN_PROGRESS", "SUCCESS"}
            if check.status not in allowed_statuses:
                reasons.append(f"merge-group check {name} ended as {check.status}")
            if now - _time(check.observed_at) > timedelta(seconds=queue_timeout_seconds):
                reasons.append(f"merge-group check {name} exceeded its freshness window")
            if _time(check.observed_at) > now:
                reasons.append(f"merge-group check {name} is from the future")
        elif check.status != "SUCCESS":
            reasons.append(f"required check {name} is {check.status}")
    return tuple(reasons)


def enqueue(
    snapshot: MergeSnapshot,
    *,
    governed_policy: GovernedMergePolicy,
    token_issuer: str,
    token_authority_digest: str,
    token_signer: EnqueueTokenSigner,
    enqueued_at: str,
    invalidation_boundary: str,
    queue_timeout_seconds: int = 1800,
) -> EnqueueToken:
    if queue_timeout_seconds <= 0:
        raise ValueError("merge queue timeout must be positive")
    reasons = _validate_snapshot(
        snapshot,
        governed_policy=governed_policy,
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
            "merge_group_check_names": tuple(
                sorted(check.name for check in snapshot.checks if check.event == "merge_group")
            ),
            "enqueued_at": enqueued_at,
            "invalidation_boundary": invalidation_boundary,
        }
    )
    if not token_issuer or not _DIGEST.fullmatch(token_authority_digest):
        raise ValueError("enqueue-token issuer identity or authority is malformed")
    token = EnqueueToken(
        snapshot_digest=snapshot_digest,
        exact_input_digest=snapshot.exact_input_digest,
        authority_digest=snapshot.authority_digest,
        finding_high_watermark_digest=snapshot.finding_high_watermark_digest,
        merge_group_check_names=tuple(
            sorted(check.name for check in snapshot.checks if check.event == "merge_group")
        ),
        issuer_id=token_issuer,
        issuer_authority_digest=token_authority_digest,
        authentication_evidence_digest="",
        enqueued_at=enqueued_at,
        invalidation_boundary=invalidation_boundary,
        enqueue_digest=enqueue_digest,
    )
    proof = token_signer(
        token_issuer, token_authority_digest, enqueue_token_authentication_payload(token)
    )
    if not _DIGEST.fullmatch(proof):
        raise ValueError("enqueue-token authentication evidence is malformed")
    return replace(token, authentication_evidence_digest=proof)


def linearize_merge(
    token: EnqueueToken,
    current: MergeSnapshot,
    *,
    governed_policy: GovernedMergePolicy,
    trusted_token_issuers: Mapping[str, str],
    token_authenticator: EnqueueTokenAuthenticator,
    observed_merge_sha: str,
    observed_merge_tree_digest: str,
    merged_at: str,
    native_gate_authorized: bool = True,
    queue_timeout_seconds: int = 1800,
) -> MergeDecision:
    trusted_token_authority = trusted_token_issuers.get(token.issuer_id, "")
    try:
        token_authenticated = bool(
            trusted_token_authority
            and trusted_token_authority == token.issuer_authority_digest
            and _DIGEST.fullmatch(token.authentication_evidence_digest)
            and token_authenticator(
                token.issuer_id,
                trusted_token_authority,
                enqueue_token_authentication_payload(token),
                token.authentication_evidence_digest,
            )
        )
    except Exception:
        token_authenticated = False
    try:
        reasons = list(
            _validate_snapshot(
                current,
                governed_policy=governed_policy,
                invalidation_boundary=token.invalidation_boundary,
                as_of=merged_at,
                queue_timeout_seconds=queue_timeout_seconds,
                enqueue_digest=token.enqueue_digest,
                linearizing=True,
            )
        )
    except ValueError:
        reasons = ["merge snapshot contains a malformed timestamp"]
    if not token_authenticated:
        reasons.append("enqueue token authentication or trusted state lookup failed")
    if current.exact_input_digest != token.exact_input_digest:
        reasons.append("reviewed head/base/tree or repository policy changed after enqueue")
    if current.authority_digest != token.authority_digest:
        reasons.append("external contract or publisher authority changed after enqueue")
    if current.finding_high_watermark_digest != token.finding_high_watermark_digest:
        reasons.append("finding high-watermark changed after enqueue")
    current_merge_group_checks = tuple(
        sorted(check.name for check in current.checks if check.event == "merge_group")
    )
    if current_merge_group_checks != token.merge_group_check_names:
        reasons.append("merge-group check identity changed after enqueue")
    if not native_gate_authorized:
        reasons.append("native gate integrity or authorization failed")
    if not _GIT_SHA.fullmatch(observed_merge_sha):
        reasons.append("observed merge SHA is absent or malformed")
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
    if dequeue_time is not None and dequeue_time < event_time:
        raise ValueError("dequeue cannot complete before its triggering external event")
    if merge_time is None or (dequeue_time is not None and dequeue_time <= merge_time):
        outcome = "PRODUCT_INPUT_REQUIRED" if kind == "AUTHORITY_REVOKED" else "REVIEW_FAILED"
        return MergeDecision(False, outcome, False, ("native admission was dequeued",))
    outcome = (
        "PR_MERGED_PRODUCT_INPUT_BLOCKED"
        if kind == "AUTHORITY_REVOKED"
        else "PR_MERGED_REMEDIATION_REQUIRED"
    )
    ordering = "before" if event_time <= merge_time else "after"
    return MergeDecision(
        True,
        outcome,
        False,
        (
            f"external event was observed {ordering} native merge; integration is retained, "
            "rollout forbidden",
        ),
    )
