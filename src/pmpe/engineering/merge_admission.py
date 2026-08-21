"""Native compare-and-swap merge admission and asynchronous race outcomes."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from pmpe.contracts.digest import canonical_digest

_GIT_SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SUPPORTED_CHECK_EVENTS = {"pull_request", "merge_group"}
EnqueueTokenSigner = Callable[[str, str, Mapping[str, object]], str]
EnqueueTokenAuthenticator = Callable[[str, str, Mapping[str, object], str], bool]
FindingAuthenticator = Callable[[str, str, Mapping[str, object], str], bool]
FindingInventoryAuthenticator = Callable[[str, str, Mapping[str, object], str], bool]
FindingResolutionAuthenticator = Callable[[str, str, Mapping[str, object], str], bool]


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
    resolution_actor: str = ""
    resolution_authority_digest: str = ""
    resolution_authentication_evidence_digest: str = ""


@dataclass(frozen=True)
class FindingInventoryAttestation:
    source: str
    subject_sha: str
    finding_digests: tuple[str, ...]
    high_watermark_digest: str
    observed_at: str
    expires_at: str
    source_authority_digest: str
    authentication_evidence_digest: str


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
    finding_inventories: tuple[FindingInventoryAttestation, ...]
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
    expires_at: str
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


def finding_resolution_authentication_payload(finding: BlockingFinding) -> dict[str, object]:
    payload = asdict(finding)
    payload.pop("resolution_authentication_evidence_digest")
    return payload


def finding_authentication_payload(finding: BlockingFinding) -> dict[str, object]:
    return {
        "finding_id": finding.finding_id,
        "source": finding.source,
        "subject_sha": finding.subject_sha,
        "severity": finding.severity,
        "credible": finding.credible,
        "blocking": finding.blocking,
        "normalized_at": finding.normalized_at,
        "source_authority_digest": finding.source_authority_digest,
    }


def finding_inventory_authentication_payload(
    inventory: FindingInventoryAttestation,
) -> dict[str, object]:
    payload = asdict(inventory)
    payload.pop("authentication_evidence_digest")
    return payload


def _finding_authenticated(
    finding: BlockingFinding,
    *,
    trusted_finding_authorities: Mapping[str, str],
    finding_authenticator: FindingAuthenticator | None,
) -> bool:
    trusted_authority = trusted_finding_authorities.get(finding.source, "")
    try:
        return bool(
            finding.source
            and trusted_authority
            and finding.source_authority_digest == trusted_authority
            and _DIGEST.fullmatch(finding.authentication_evidence_digest)
            and finding_authenticator is not None
            and finding_authenticator(
                finding.source,
                trusted_authority,
                finding_authentication_payload(finding),
                finding.authentication_evidence_digest,
            )
        )
    except Exception:
        return False


def _blocking_finding(
    finding: BlockingFinding,
    *,
    trusted_finding_authorities: Mapping[str, str],
    resolution_authenticator: FindingResolutionAuthenticator | None,
) -> bool:
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
    trusted_resolution_authority = trusted_finding_authorities.get(finding.resolution_actor, "")
    try:
        resolved = bool(
            finding.disposition in {"RESOLVED", "REJECTED_WITH_EVIDENCE"}
            and _DIGEST.fullmatch(finding.resolution_digest)
            and finding.resolution_actor
            and trusted_resolution_authority
            and finding.resolution_authority_digest == trusted_resolution_authority
            and _DIGEST.fullmatch(finding.resolution_authentication_evidence_digest)
            and resolution_authenticator is not None
            and resolution_authenticator(
                finding.resolution_actor,
                trusted_resolution_authority,
                finding_resolution_authentication_payload(finding),
                finding.resolution_authentication_evidence_digest,
            )
        )
    except Exception:
        resolved = False
    return normalized_blocker and not resolved


def _validate_snapshot(
    snapshot: MergeSnapshot,
    *,
    governed_policy: GovernedMergePolicy,
    invalidation_boundary: str,
    as_of: str,
    queue_timeout_seconds: int,
    trusted_finding_sources: Mapping[str, str],
    trusted_finding_authorities: Mapping[str, str],
    finding_authenticator: FindingAuthenticator | None,
    finding_inventory_authenticator: FindingInventoryAuthenticator | None,
    resolution_authenticator: FindingResolutionAuthenticator | None,
    enqueue_digest: str = "",
    enqueued_at: str = "",
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
    inventory_by_source = {
        inventory.source: inventory for inventory in snapshot.finding_inventories
    }
    if (
        not trusted_finding_sources
        or len(inventory_by_source) != len(snapshot.finding_inventories)
        or set(inventory_by_source) != set(trusted_finding_sources)
    ):
        reasons.append("finding inventory source coverage is incomplete")
    for source, trusted_authority in trusted_finding_sources.items():
        inventory = inventory_by_source.get(source)
        expected_finding_digests = tuple(
            sorted(
                canonical_digest(finding_authentication_payload(finding))
                for finding in snapshot.findings
                if finding.source == source and finding.subject_sha == snapshot.pr_head_sha
            )
        )
        try:
            inventory_authenticated = bool(
                inventory is not None
                and inventory.subject_sha == snapshot.pr_head_sha
                and inventory.finding_digests == expected_finding_digests
                and inventory.high_watermark_digest == snapshot.finding_high_watermark_digest
                and inventory.source_authority_digest == trusted_authority
                and _DIGEST.fullmatch(inventory.high_watermark_digest)
                and _DIGEST.fullmatch(inventory.authentication_evidence_digest)
                and _time(invalidation_boundary) < _time(inventory.observed_at) <= _time(as_of)
                and _time(inventory.observed_at) <= _time(as_of) <= _time(inventory.expires_at)
                and _time(inventory.expires_at) - _time(inventory.observed_at)
                <= timedelta(minutes=5)
                and finding_inventory_authenticator is not None
                and finding_inventory_authenticator(
                    source,
                    trusted_authority,
                    finding_inventory_authentication_payload(inventory),
                    inventory.authentication_evidence_digest,
                )
            )
        except Exception:
            inventory_authenticated = False
        if not inventory_authenticated:
            reasons.append(
                f"finding inventory for {source} is incomplete, stale, or unauthenticated"
            )
    authenticated_findings = tuple(
        (
            finding,
            _finding_authenticated(
                finding,
                trusted_finding_authorities=trusted_finding_sources,
                finding_authenticator=finding_authenticator,
            ),
        )
        for finding in snapshot.findings
    )
    if any(not authenticated for _, authenticated in authenticated_findings):
        reasons.append("finding source attestation is not independently authenticated")
    if any(
        authenticated
        and finding.subject_sha == snapshot.pr_head_sha
        and _blocking_finding(
            finding,
            trusted_finding_authorities=trusted_finding_authorities,
            resolution_authenticator=resolution_authenticator,
        )
        for finding, authenticated in authenticated_findings
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
        if check.event not in _SUPPORTED_CHECK_EVENTS:
            reasons.append(f"required check {name} has unsupported event {check.event!r}")
            continue
        if check.subject_sha != snapshot.pr_head_sha:
            reasons.append(f"required check {name} is bound to the wrong subject")
        if check.input_digest != snapshot.exact_input_digest:
            reasons.append(f"required check {name} has stale policy/toolchain inputs")
        try:
            observed = _time(check.observed_at)
        except ValueError:
            reasons.append(f"required check {name} has a malformed observation time")
            continue
        if observed > now:
            reasons.append(f"required check {name} is from the future")
        if check.event == "merge_group":
            if linearizing and check.enqueue_digest != enqueue_digest:
                reasons.append(f"merge-group check {name} is from another enqueue")
            if linearizing and observed < _time(enqueued_at):
                reasons.append(f"merge-group check {name} predates its authenticated enqueue")
            allowed_statuses = {"SUCCESS"} if linearizing else {"PENDING", "IN_PROGRESS", "SUCCESS"}
            if check.status not in allowed_statuses:
                reasons.append(f"merge-group check {name} ended as {check.status}")
            if now - observed > timedelta(seconds=queue_timeout_seconds):
                reasons.append(f"merge-group check {name} exceeded its freshness window")
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
    trusted_finding_sources: Mapping[str, str] | None = None,
    trusted_finding_authorities: Mapping[str, str] | None = None,
    finding_authenticator: FindingAuthenticator | None = None,
    finding_inventory_authenticator: FindingInventoryAuthenticator | None = None,
    resolution_authenticator: FindingResolutionAuthenticator | None = None,
) -> EnqueueToken:
    if queue_timeout_seconds <= 0:
        raise ValueError("merge queue timeout must be positive")
    reasons = _validate_snapshot(
        snapshot,
        governed_policy=governed_policy,
        invalidation_boundary=invalidation_boundary,
        as_of=enqueued_at,
        queue_timeout_seconds=queue_timeout_seconds,
        trusted_finding_sources=trusted_finding_sources or {},
        trusted_finding_authorities=trusted_finding_authorities or {},
        finding_authenticator=finding_authenticator,
        finding_inventory_authenticator=finding_inventory_authenticator,
        resolution_authenticator=resolution_authenticator,
    )
    if reasons:
        raise ValueError("; ".join(reasons))
    snapshot_digest = _snapshot_digest(snapshot)
    expires_at = (
        (_time(enqueued_at) + timedelta(seconds=queue_timeout_seconds))
        .isoformat()
        .replace("+00:00", "Z")
    )
    enqueue_digest = canonical_digest(
        {
            "snapshot_digest": snapshot_digest,
            "exact_input_digest": snapshot.exact_input_digest,
            "merge_group_check_names": tuple(
                sorted(check.name for check in snapshot.checks if check.event == "merge_group")
            ),
            "enqueued_at": enqueued_at,
            "expires_at": expires_at,
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
        expires_at=expires_at,
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
    trusted_finding_sources: Mapping[str, str] | None = None,
    trusted_finding_authorities: Mapping[str, str] | None = None,
    finding_authenticator: FindingAuthenticator | None = None,
    finding_inventory_authenticator: FindingInventoryAuthenticator | None = None,
    resolution_authenticator: FindingResolutionAuthenticator | None = None,
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
        authenticated_queue_timeout = int(
            (_time(token.expires_at) - _time(token.enqueued_at)).total_seconds()
        )
        if authenticated_queue_timeout <= 0:
            raise ValueError("enqueue-token expiry must follow enqueue time")
        reasons = list(
            _validate_snapshot(
                current,
                governed_policy=governed_policy,
                invalidation_boundary=token.invalidation_boundary,
                as_of=merged_at,
                queue_timeout_seconds=authenticated_queue_timeout,
                trusted_finding_sources=trusted_finding_sources or {},
                trusted_finding_authorities=trusted_finding_authorities or {},
                finding_authenticator=finding_authenticator,
                finding_inventory_authenticator=finding_inventory_authenticator,
                resolution_authenticator=resolution_authenticator,
                enqueue_digest=token.enqueue_digest,
                enqueued_at=token.enqueued_at,
                linearizing=True,
            )
        )
    except ValueError:
        reasons = ["merge snapshot contains a malformed timestamp"]
    if not token_authenticated:
        reasons.append("enqueue token authentication or trusted state lookup failed")
    try:
        merge_time = _time(merged_at)
        if merge_time < _time(token.enqueued_at):
            reasons.append("merge linearization predates the authenticated enqueue token")
        elif merge_time > _time(token.expires_at):
            reasons.append("authenticated enqueue token exceeded its freshness window")
    except ValueError:
        reasons.append("enqueue token contains a malformed timestamp")
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
