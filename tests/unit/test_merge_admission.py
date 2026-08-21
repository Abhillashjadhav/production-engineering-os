from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from pmpe.engineering.merge_admission import (
    BlockingFinding,
    FormalReview,
    GovernedMergePolicy,
    MergeSnapshot,
    RequiredCheck,
    enqueue,
    finding_resolution_authentication_payload,
    linearize_merge,
    load_governed_merge_policy,
    resolve_external_race,
)

D = "sha256:" + "a" * 64
E = "sha256:" + "b" * 64
HEAD = "c" * 40
BASE = "d" * 40
NOW = "2026-08-20T12:00:00Z"
AFTER = "2026-08-20T12:01:00Z"
POLICY = GovernedMergePolicy(D, ("ci",))
TOKEN_ISSUER = "merge-queue"
TOKEN_ISSUERS = {TOKEN_ISSUER: D}
FINDING_AUTHORITIES = {"finding-owner": D}


def _token_proof(identity: str, authority: str, payload: Mapping[str, object]) -> str:
    from pmpe.contracts.digest import canonical_digest

    return canonical_digest(
        {
            "test_trust_root": "outside-the-enqueue-token",
            "identity": identity,
            "authority": authority,
            "payload": payload,
        }
    )


def _sign_token(identity: str, authority: str, payload: Mapping[str, object]) -> str:
    return _token_proof(identity, authority, payload)


def _authenticate_token(
    identity: str, authority: str, payload: Mapping[str, object], proof: str
) -> bool:
    return proof == _token_proof(identity, authority, payload)


def _resolution_proof(identity: str, authority: str, payload: Mapping[str, object]) -> str:
    from pmpe.contracts.digest import canonical_digest

    return canonical_digest(
        {
            "test_trust_root": "outside-the-finding-snapshot",
            "identity": identity,
            "authority": authority,
            "payload": payload,
        }
    )


def _authenticate_resolution(
    identity: str, authority: str, payload: Mapping[str, object], proof: str
) -> bool:
    return proof == _resolution_proof(identity, authority, payload)


def _snapshot() -> MergeSnapshot:
    shell = MergeSnapshot(
        pr_head_sha=HEAD,
        protected_base_sha=BASE,
        prospective_merge_tree_digest=D,
        repository_rules_digest=D,
        architecture_policy_digest=D,
        toolchain_policy_digest=D,
        environment_profile_digest=D,
        security_policy_digest=D,
        verification_policy_digest=D,
        evidence_policy_digest=D,
        authority_digest=D,
        finding_high_watermark_digest=D,
        pending_unclassified_findings=0,
        required_check_names=("ci",),
        checks=(),
        reviews=(FormalReview("r1", "eligible-human", HEAD, "APPROVED", AFTER, True),),
        findings=(),
        merge_queue_enforced=True,
    )
    return replace(
        shell,
        checks=(RequiredCheck("ci", HEAD, shell.exact_input_digest, "SUCCESS", AFTER),),
    )


def test_native_cas_admits_only_unchanged_exact_candidate() -> None:
    snapshot = _snapshot()
    token = enqueue(
        snapshot,
        governed_policy=POLICY,
        token_issuer=TOKEN_ISSUER,
        token_authority_digest=TOKEN_ISSUERS[TOKEN_ISSUER],
        token_signer=_sign_token,
        enqueued_at=AFTER,
        invalidation_boundary=NOW,
    )

    decision = linearize_merge(
        token,
        snapshot,
        governed_policy=POLICY,
        trusted_token_issuers=TOKEN_ISSUERS,
        token_authenticator=_authenticate_token,
        observed_merge_sha="e" * 40,
        observed_merge_tree_digest=D,
        merged_at=AFTER,
    )

    assert decision.admitted
    assert decision.rollout_allowed


def test_signed_enqueue_token_expires_even_without_merge_group_checks() -> None:
    snapshot = _snapshot()
    token = enqueue(
        snapshot,
        governed_policy=POLICY,
        token_issuer=TOKEN_ISSUER,
        token_authority_digest=TOKEN_ISSUERS[TOKEN_ISSUER],
        token_signer=_sign_token,
        enqueued_at=AFTER,
        invalidation_boundary=NOW,
        queue_timeout_seconds=1,
    )

    decision = linearize_merge(
        token,
        snapshot,
        governed_policy=POLICY,
        trusted_token_issuers=TOKEN_ISSUERS,
        token_authenticator=_authenticate_token,
        observed_merge_sha="e" * 40,
        observed_merge_tree_digest=D,
        merged_at="2026-08-20T12:01:02Z",
        queue_timeout_seconds=86_400,
    )

    assert not decision.admitted
    assert any("token exceeded its freshness window" in reason for reason in decision.reasons)


def test_signed_enqueue_token_rejects_tampered_expiry() -> None:
    snapshot = _snapshot()
    token = enqueue(
        snapshot,
        governed_policy=POLICY,
        token_issuer=TOKEN_ISSUER,
        token_authority_digest=TOKEN_ISSUERS[TOKEN_ISSUER],
        token_signer=_sign_token,
        enqueued_at=AFTER,
        invalidation_boundary=NOW,
        queue_timeout_seconds=1,
    )

    decision = linearize_merge(
        replace(token, expires_at="2026-08-21T12:01:00Z"),
        snapshot,
        governed_policy=POLICY,
        trusted_token_issuers=TOKEN_ISSUERS,
        token_authenticator=_authenticate_token,
        observed_merge_sha="e" * 40,
        observed_merge_tree_digest=D,
        merged_at="2026-08-20T12:01:02Z",
    )

    assert not decision.admitted
    assert any("token authentication" in reason for reason in decision.reasons)


def test_unsupported_required_check_event_is_never_pull_request_equivalent() -> None:
    snapshot = _snapshot()
    unsupported = replace(snapshot.checks[0], event="workflow_run")
    with pytest.raises(ValueError, match="unsupported event"):
        enqueue(
            replace(snapshot, checks=(unsupported,)),
            governed_policy=POLICY,
            token_issuer=TOKEN_ISSUER,
            token_authority_digest=TOKEN_ISSUERS[TOKEN_ISSUER],
            token_signer=_sign_token,
            enqueued_at=AFTER,
            invalidation_boundary=NOW,
        )

    token = enqueue(
        snapshot,
        governed_policy=POLICY,
        token_issuer=TOKEN_ISSUER,
        token_authority_digest=TOKEN_ISSUERS[TOKEN_ISSUER],
        token_signer=_sign_token,
        enqueued_at=AFTER,
        invalidation_boundary=NOW,
    )
    decision = linearize_merge(
        token,
        replace(snapshot, checks=(unsupported,)),
        governed_policy=POLICY,
        trusted_token_issuers=TOKEN_ISSUERS,
        token_authenticator=_authenticate_token,
        observed_merge_sha="e" * 40,
        observed_merge_tree_digest=D,
        merged_at=AFTER,
    )

    assert not decision.admitted
    assert any("unsupported event" in reason for reason in decision.reasons)


@pytest.mark.parametrize("observed_at", ["not-a-time", "2099-01-01T00:00:00Z"])
def test_pull_request_check_observation_must_be_valid_and_not_future(
    observed_at: str,
) -> None:
    snapshot = _snapshot()
    invalid_check = replace(snapshot.checks[0], observed_at=observed_at)
    with pytest.raises(ValueError, match="observation time|future"):
        enqueue(
            replace(snapshot, checks=(invalid_check,)),
            governed_policy=POLICY,
            token_issuer=TOKEN_ISSUER,
            token_authority_digest=TOKEN_ISSUERS[TOKEN_ISSUER],
            token_signer=_sign_token,
            enqueued_at=AFTER,
            invalidation_boundary=NOW,
        )

    token = enqueue(
        snapshot,
        governed_policy=POLICY,
        token_issuer=TOKEN_ISSUER,
        token_authority_digest=TOKEN_ISSUERS[TOKEN_ISSUER],
        token_signer=_sign_token,
        enqueued_at=AFTER,
        invalidation_boundary=NOW,
    )
    decision = linearize_merge(
        token,
        replace(snapshot, checks=(invalid_check,)),
        governed_policy=POLICY,
        trusted_token_issuers=TOKEN_ISSUERS,
        token_authenticator=_authenticate_token,
        observed_merge_sha="e" * 40,
        observed_merge_tree_digest=D,
        merged_at=AFTER,
    )

    assert not decision.admitted
    assert any("observation time" in reason or "future" in reason for reason in decision.reasons)


@pytest.mark.parametrize(
    "change",
    [
        "head",
        "base",
        "tree",
        "rules",
        "architecture",
        "toolchain",
        "environment",
        "security",
        "verification",
        "evidence",
    ],
)
def test_native_cas_rejects_ready_state_drift(change: str) -> None:
    snapshot = _snapshot()
    token = enqueue(
        snapshot,
        governed_policy=POLICY,
        token_issuer=TOKEN_ISSUER,
        token_authority_digest=TOKEN_ISSUERS[TOKEN_ISSUER],
        token_signer=_sign_token,
        enqueued_at=AFTER,
        invalidation_boundary=NOW,
    )
    field = {
        "head": "pr_head_sha",
        "base": "protected_base_sha",
        "tree": "prospective_merge_tree_digest",
        "rules": "repository_rules_digest",
        "architecture": "architecture_policy_digest",
        "toolchain": "toolchain_policy_digest",
        "environment": "environment_profile_digest",
        "security": "security_policy_digest",
        "verification": "verification_policy_digest",
        "evidence": "evidence_policy_digest",
    }[change]
    changed_value = "f" * 40 if change in {"head", "base"} else E
    current = replace(snapshot, **{field: changed_value})

    decision = linearize_merge(
        token,
        current,
        governed_policy=POLICY,
        trusted_token_issuers=TOKEN_ISSUERS,
        token_authenticator=_authenticate_token,
        observed_merge_sha="e" * 40,
        observed_merge_tree_digest=current.prospective_merge_tree_digest,
        merged_at=AFTER,
    )

    assert not decision.admitted
    assert decision.incident


def test_ineligible_finding_source_can_block_but_cannot_approve() -> None:
    snapshot = replace(
        _snapshot(),
        reviews=(FormalReview("bot-review", "scanner", HEAD, "APPROVED", AFTER, False),),
        findings=(BlockingFinding("F1", "scanner", HEAD, "HIGH", True, True, AFTER, D, E),),
    )

    with pytest.raises(ValueError) as exc:
        enqueue(
            snapshot,
            governed_policy=POLICY,
            token_issuer=TOKEN_ISSUER,
            token_authority_digest=TOKEN_ISSUERS[TOKEN_ISSUER],
            token_signer=_sign_token,
            enqueued_at=AFTER,
            invalidation_boundary=NOW,
        )

    assert "blocking finding" in str(exc.value)
    assert "no fresh eligible formal approval" in str(exc.value)


def test_changes_requested_blocks_even_with_an_approval() -> None:
    snapshot = _snapshot()
    reviews = (
        *snapshot.reviews,
        FormalReview("r2", "other", HEAD, "CHANGES_REQUESTED", AFTER, True),
    )
    with pytest.raises(ValueError, match="changes are requested"):
        enqueue(
            replace(snapshot, reviews=reviews),
            governed_policy=POLICY,
            token_issuer=TOKEN_ISSUER,
            token_authority_digest=TOKEN_ISSUERS[TOKEN_ISSUER],
            token_signer=_sign_token,
            enqueued_at=AFTER,
            invalidation_boundary=NOW,
        )


def test_blocker_resolution_requires_independent_trusted_authentication() -> None:
    snapshot = _snapshot()
    blocker = BlockingFinding("F1", "scanner", HEAD, "HIGH", True, True, AFTER, D, E)
    self_asserted = replace(
        blocker,
        disposition="RESOLVED",
        resolution_digest=D,
    )
    with pytest.raises(ValueError, match="blocking finding"):
        enqueue(
            replace(snapshot, findings=(self_asserted,)),
            governed_policy=POLICY,
            token_issuer=TOKEN_ISSUER,
            token_authority_digest=TOKEN_ISSUERS[TOKEN_ISSUER],
            token_signer=_sign_token,
            enqueued_at=AFTER,
            invalidation_boundary=NOW,
        )

    authenticated = replace(
        self_asserted,
        resolution_actor="finding-owner",
        resolution_authority_digest=FINDING_AUTHORITIES["finding-owner"],
    )
    authenticated = replace(
        authenticated,
        resolution_authentication_evidence_digest=_resolution_proof(
            authenticated.resolution_actor,
            authenticated.resolution_authority_digest,
            finding_resolution_authentication_payload(authenticated),
        ),
    )
    token = enqueue(
        replace(snapshot, findings=(authenticated,)),
        governed_policy=POLICY,
        token_issuer=TOKEN_ISSUER,
        token_authority_digest=TOKEN_ISSUERS[TOKEN_ISSUER],
        token_signer=_sign_token,
        enqueued_at=AFTER,
        invalidation_boundary=NOW,
        trusted_finding_authorities=FINDING_AUTHORITIES,
        resolution_authenticator=_authenticate_resolution,
    )

    assert token.snapshot_digest
    without_resolution_authority = linearize_merge(
        token,
        replace(snapshot, findings=(authenticated,)),
        governed_policy=POLICY,
        trusted_token_issuers=TOKEN_ISSUERS,
        token_authenticator=_authenticate_token,
        observed_merge_sha="e" * 40,
        observed_merge_tree_digest=D,
        merged_at=AFTER,
    )
    assert not without_resolution_authority.admitted
    assert any("blocking finding" in reason for reason in without_resolution_authority.reasons)

    admitted = linearize_merge(
        token,
        replace(snapshot, findings=(authenticated,)),
        governed_policy=POLICY,
        trusted_token_issuers=TOKEN_ISSUERS,
        token_authenticator=_authenticate_token,
        observed_merge_sha="e" * 40,
        observed_merge_tree_digest=D,
        merged_at=AFTER,
        trusted_finding_authorities=FINDING_AUTHORITIES,
        resolution_authenticator=_authenticate_resolution,
    )
    assert admitted.admitted


def test_merge_group_must_be_exact_fresh_and_from_admitted_enqueue() -> None:
    snapshot = _snapshot()
    enqueued_check = RequiredCheck(
        "ci",
        HEAD,
        snapshot.exact_input_digest,
        "PENDING",
        AFTER,
        event="merge_group",
    )
    enqueued_snapshot = replace(snapshot, checks=(enqueued_check,))
    token = enqueue(
        enqueued_snapshot,
        governed_policy=POLICY,
        token_issuer=TOKEN_ISSUER,
        token_authority_digest=TOKEN_ISSUERS[TOKEN_ISSUER],
        token_signer=_sign_token,
        enqueued_at=AFTER,
        invalidation_boundary=NOW,
    )
    queue_check = replace(
        enqueued_check,
        status="IN_PROGRESS",
        enqueue_digest=token.enqueue_digest,
    )
    current = replace(
        enqueued_snapshot,
        checks=(queue_check,),
    )

    pending = linearize_merge(
        token,
        current,
        governed_policy=POLICY,
        trusted_token_issuers=TOKEN_ISSUERS,
        token_authenticator=_authenticate_token,
        observed_merge_sha="e" * 40,
        observed_merge_tree_digest=D,
        merged_at=AFTER,
    )
    assert not pending.admitted
    assert any("IN_PROGRESS" in reason for reason in pending.reasons)

    succeeded = replace(queue_check, status="SUCCESS")
    assert linearize_merge(
        token,
        replace(current, checks=(succeeded,)),
        governed_policy=POLICY,
        trusted_token_issuers=TOKEN_ISSUERS,
        token_authenticator=_authenticate_token,
        observed_merge_sha="e" * 40,
        observed_merge_tree_digest=D,
        merged_at=AFTER,
    ).admitted

    failed = replace(queue_check, status="CANCELLED")
    held = linearize_merge(
        token,
        replace(current, checks=(failed,)),
        governed_policy=POLICY,
        trusted_token_issuers=TOKEN_ISSUERS,
        token_authenticator=_authenticate_token,
        observed_merge_sha="e" * 40,
        observed_merge_tree_digest=D,
        merged_at=AFTER,
    )
    assert not held.admitted
    assert any("CANCELLED" in reason for reason in held.reasons)

    downgraded = replace(queue_check, event="pull_request", status="SUCCESS", enqueue_digest="")
    held = linearize_merge(
        token,
        replace(current, checks=(downgraded,)),
        governed_policy=POLICY,
        trusted_token_issuers=TOKEN_ISSUERS,
        token_authenticator=_authenticate_token,
        observed_merge_sha="e" * 40,
        observed_merge_tree_digest=D,
        merged_at=AFTER,
    )
    assert not held.admitted
    assert any("identity changed" in reason for reason in held.reasons)

    tampered_token = replace(token, merge_group_check_names=())
    held = linearize_merge(
        tampered_token,
        replace(current, checks=(downgraded,)),
        governed_policy=POLICY,
        trusted_token_issuers=TOKEN_ISSUERS,
        token_authenticator=_authenticate_token,
        observed_merge_sha="e" * 40,
        observed_merge_tree_digest=D,
        merged_at=AFTER,
    )
    assert not held.admitted
    assert any("token authentication" in reason for reason in held.reasons)


def test_merge_group_observation_cannot_predate_authenticated_enqueue() -> None:
    snapshot = _snapshot()
    enqueued_check = replace(
        snapshot.checks[0],
        status="PENDING",
        event="merge_group",
    )
    enqueued_snapshot = replace(snapshot, checks=(enqueued_check,))
    token = enqueue(
        enqueued_snapshot,
        governed_policy=POLICY,
        token_issuer=TOKEN_ISSUER,
        token_authority_digest=TOKEN_ISSUERS[TOKEN_ISSUER],
        token_signer=_sign_token,
        enqueued_at=AFTER,
        invalidation_boundary=NOW,
    )
    pre_enqueue_success = replace(
        enqueued_check,
        status="SUCCESS",
        observed_at="2026-08-20T12:00:59Z",
        enqueue_digest=token.enqueue_digest,
    )

    decision = linearize_merge(
        token,
        replace(enqueued_snapshot, checks=(pre_enqueue_success,)),
        governed_policy=POLICY,
        trusted_token_issuers=TOKEN_ISSUERS,
        token_authenticator=_authenticate_token,
        observed_merge_sha="e" * 40,
        observed_merge_tree_digest=D,
        merged_at="2026-08-20T12:01:01Z",
    )

    assert not decision.admitted
    assert any("predates its authenticated enqueue" in reason for reason in decision.reasons)


@pytest.mark.parametrize("kind", ["AUTHORITY_REVOKED", "BLOCKING_FINDING"])
def test_external_event_dequeue_first_prevents_merge(kind: str) -> None:
    result = resolve_external_race(
        kind=kind,  # type: ignore[arg-type]
        external_event_at=NOW,
        native_merge_at="2026-08-20T12:03:00Z",
        dequeue_completed_at=AFTER,
    )
    assert not result.admitted
    assert not result.rollout_allowed


@pytest.mark.parametrize("kind", ["AUTHORITY_REVOKED", "BLOCKING_FINDING"])
def test_external_event_merge_first_is_integration_only(kind: str) -> None:
    result = resolve_external_race(
        kind=kind,  # type: ignore[arg-type]
        external_event_at=NOW,
        native_merge_at=AFTER,
        dequeue_completed_at="2026-08-20T12:03:00Z",
    )
    assert result.admitted
    assert result.outcome.startswith("PR_MERGED_")
    assert not result.rollout_allowed


def test_bypass_blocks_rollout_even_when_tree_matches() -> None:
    snapshot = _snapshot()
    with pytest.raises(ValueError, match="bypass"):
        enqueue(
            replace(snapshot, bypass_used=True),
            governed_policy=POLICY,
            token_issuer=TOKEN_ISSUER,
            token_authority_digest=TOKEN_ISSUERS[TOKEN_ISSUER],
            token_signer=_sign_token,
            enqueued_at=AFTER,
            invalidation_boundary=NOW,
        )


@pytest.mark.parametrize("field", ["authority_digest", "finding_high_watermark_digest"])
def test_external_fences_are_rechecked_at_merge_linearization(field: str) -> None:
    snapshot = _snapshot()
    token = enqueue(
        snapshot,
        governed_policy=POLICY,
        token_issuer=TOKEN_ISSUER,
        token_authority_digest=TOKEN_ISSUERS[TOKEN_ISSUER],
        token_signer=_sign_token,
        enqueued_at=AFTER,
        invalidation_boundary=NOW,
    )
    changed = replace(snapshot, **{field: E})

    decision = linearize_merge(
        token,
        changed,
        governed_policy=POLICY,
        trusted_token_issuers=TOKEN_ISSUERS,
        token_authenticator=_authenticate_token,
        observed_merge_sha="e" * 40,
        observed_merge_tree_digest=D,
        merged_at=AFTER,
    )

    assert not decision.admitted
    assert not decision.rollout_allowed
    assert any("authority" in reason or "high-watermark" in reason for reason in decision.reasons)


def test_required_checks_come_from_independent_governed_policy() -> None:
    snapshot = replace(_snapshot(), required_check_names=())

    with pytest.raises(ValueError, match="governed merge policy"):
        enqueue(
            snapshot,
            governed_policy=POLICY,
            token_issuer=TOKEN_ISSUER,
            token_authority_digest=TOKEN_ISSUERS[TOKEN_ISSUER],
            token_signer=_sign_token,
            enqueued_at=AFTER,
            invalidation_boundary=NOW,
        )


def test_committed_policy_loader_derives_the_full_required_check_set() -> None:
    root = Path(__file__).resolve().parents[2]
    policy = load_governed_merge_policy(root / ".github/merge-admission-policy.yml")

    assert policy.required_check_names == (
        "format-lint",
        "types",
        "tests (3.11)",
        "tests (3.12)",
        "security",
        "product-backend (3.11)",
        "product-backend (3.12)",
        "product-frontend",
        "product-e2e",
        "product-preview",
    )


@pytest.mark.parametrize("kind", ["AUTHORITY_REVOKED", "BLOCKING_FINDING"])
def test_external_event_observed_after_merge_still_blocks_pre_rollout_fence(kind: str) -> None:
    result = resolve_external_race(
        kind=kind,  # type: ignore[arg-type]
        external_event_at="2026-08-20T12:02:00Z",
        native_merge_at=AFTER,
        dequeue_completed_at=None,
    )

    assert result.admitted
    assert not result.rollout_allowed
    assert result.outcome.startswith("PR_MERGED_")
