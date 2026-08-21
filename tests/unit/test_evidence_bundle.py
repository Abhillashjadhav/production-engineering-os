from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from pmpe.audit.evidence import (
    STAGE_PROFILES,
    EnvironmentFingerprint,
    EvidenceItem,
    EvidenceManifest,
    EvidenceProducer,
    EvidenceProducerPolicy,
    EvidenceSubject,
    EvidenceViolation,
    ImmutableEvidenceStore,
    SealedEvidenceBundle,
    ToolIdentity,
    evidence_authentication_payload,
    seal_manifest,
    verify_bundle,
)
from pmpe.contracts.digest import canonical_digest
from pmpe.quality.evidence_gate import (
    assess_completion,
    assess_readiness,
    assess_staging,
    verification_recovery_state,
)

D = "sha256:" + "a" * 64
E = "sha256:" + "b" * 64
SHA = "c" * 40
BASE = "d" * 40
NOW = "2026-08-20T12:00:00Z"
LATER = "2026-08-20T12:30:00Z"
PRODUCER_POLICIES = {
    "intake/system": EvidenceProducerPolicy(
        D,
        ("contract_admission",),
        (
            "intake_reservation",
            "intake_disposition",
            "intake_receipt",
            "receipt_finalization_failure",
        ),
        ("AUTOMATED",),
    ),
    "ci/github": EvidenceProducerPolicy(
        D,
        ("pre_code", "candidate_review", "merge_admission", "staging", "completion"),
        (
            "repository_snapshot",
            "architecture",
            "test_plan",
            "meaningful_red",
            "candidate",
            "required_checks",
            "artifact",
            "configuration",
        ),
        ("AUTOMATED",),
    ),
    "review/codex": EvidenceProducerPolicy(
        D,
        ("candidate_review", "merge_admission", "staging", "completion"),
        ("advisory_review", "formal_review", "finding_inventory"),
        ("AUTOMATED",),
    ),
    "merge/github": EvidenceProducerPolicy(
        D,
        ("merge_admission", "staging", "completion"),
        ("merge_gate", "observed_merge"),
        ("AUTOMATED",),
    ),
    "release/orchestrator": EvidenceProducerPolicy(
        D,
        ("completion", "rollback_incident"),
        (
            "deployment",
            "rollback_readiness",
            "final_head_attestation",
            "rollback_execution",
            "restored_state",
            "rto_rpo",
        ),
        ("AUTOMATED",),
    ),
    "live/monitor": EvidenceProducerPolicy(
        D,
        ("completion",),
        ("live_observation",),
        ("AUTOMATED",),
    ),
}


def _producer_proof(identity: str, authority_digest: str, payload: Mapping[str, object]) -> str:
    return canonical_digest(
        {
            "test_trust_root": "outside-the-evidence-bundle",
            "identity": identity,
            "authority_digest": authority_digest,
            "payload": payload,
        }
    )


def _authenticate_producer(
    identity: str,
    authority_digest: str,
    payload: Mapping[str, object],
    proof: str,
) -> bool:
    return proof == _producer_proof(identity, authority_digest, payload)


def _environment(**changes: str) -> EnvironmentFingerprint:
    values = {
        "os": "ubuntu-24.04",
        "architecture": "x86_64",
        "runtime": "cpython-3.12.4",
        "dependency_digest": D,
        "container_digest": E,
        "configuration_digest": D,
        "hardware_class": "standard-2",
    }
    values.update(changes)
    return EnvironmentFingerprint(**values)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("runtime", "", "identity fields"),
        ("architecture", "   ", "identity fields"),
        ("dependency_digest", "", "canonical SHA-256"),
        ("container_digest", "sha256:not-a-digest", "canonical SHA-256"),
    ],
)
def test_environment_fingerprint_rejects_incomplete_identity(
    field: str, value: str, reason: str
) -> None:
    with pytest.raises(EvidenceViolation, match=reason):
        _environment(**{field: value})


def _subject(profile: str) -> EvidenceSubject:
    values: dict[str, str] = {}
    for field in STAGE_PROFILES[profile].required_subject_fields:
        values[field] = SHA if field.endswith("_sha") else D
    return EvidenceSubject(**values)


def _item(
    profile: str,
    evidence_class: str,
    subject: EvidenceSubject,
    *,
    environment: EnvironmentFingerprint | None = None,
    medium: str = "ATTESTATION",
    result: str = "PASS",
    expires_at: str = "2026-08-21T12:00:00Z",
) -> EvidenceItem:
    executed = 1 if evidence_class in {"required_checks", "meaningful_red"} else 0
    producer_id, producer_policy = next(
        (identity, policy)
        for identity, policy in PRODUCER_POLICIES.items()
        if profile in policy.allowed_profiles and evidence_class in policy.allowed_classes
    )
    item = EvidenceItem(
        evidence_id=f"{profile}:{evidence_class}",
        evidence_class=evidence_class,
        stage=profile,
        subject_digest=subject.digest,
        result=result,
        producer=EvidenceProducer(producer_id, producer_policy.authority_digest, "AUTOMATED"),
        tool=ToolIdentity("pytest", "8.4.1", D, E),
        environment=environment or _environment(),
        invocation=("python", "-m", "pytest", "-q"),
        output_digest=E,
        observed_at=NOW,
        retention_class="release+incident",
        authentication_evidence_digest="",
        attestation_format="DSSE-v1",
        medium=medium,
        expires_at=expires_at,
        executed_count=executed,
        passed_count=1 if evidence_class == "required_checks" else 0,
        failed_count=1 if evidence_class == "meaningful_red" else 0,
    )
    return replace(
        item,
        authentication_evidence_digest=_producer_proof(
            item.producer.producer_id,
            item.producer.authority_digest,
            evidence_authentication_payload(item, D),
        ),
    )


def _bundle(profile: str) -> tuple[SealedEvidenceBundle, EvidenceSubject]:
    subject = _subject(profile)
    items = tuple(
        _item(profile, evidence_class, subject)
        for evidence_class in (
            *STAGE_PROFILES[profile].required_classes,
            *(group[0] for group in STAGE_PROFILES[profile].required_any_groups),
        )
    )
    manifest = EvidenceManifest("evidence-bundle/v1", profile, subject, D, NOW, items)
    return (
        seal_manifest(
            manifest,
            producer_policies=PRODUCER_POLICIES,
            authenticator=_authenticate_producer,
            expected_environment=_environment(),
            as_of=LATER,
        ),
        subject,
    )


def test_sealed_bundle_is_content_addressed_and_reconstructible() -> None:
    bundle, subject = _bundle("completion")

    report = verify_bundle(
        bundle,
        expected_profile="completion",
        expected_subject=subject,
        expected_policy_digest=D,
        producer_policies=PRODUCER_POLICIES,
        authenticator=_authenticate_producer,
        expected_environment=_environment(),
        as_of=LATER,
    )

    assert report.valid
    assert report.completeness == 1.0
    assert bundle.bundle_digest == canonical_digest(bundle.manifest)


def test_staging_gate_accepts_only_the_sealed_staging_profile() -> None:
    bundle, subject = _bundle("staging")

    decision = assess_staging(
        bundle,
        subject=subject,
        policy_digest=D,
        environment=_environment(),
        as_of=LATER,
        producer_policies=PRODUCER_POLICIES,
        authenticator=_authenticate_producer,
    )

    assert decision.admitted
    wrong_profile, _ = _bundle("candidate_review")
    assert not assess_staging(
        wrong_profile,
        subject=subject,
        policy_digest=D,
        environment=_environment(),
        as_of=LATER,
        producer_policies=PRODUCER_POLICIES,
        authenticator=_authenticate_producer,
    ).admitted


def test_shape_valid_but_fabricated_producer_proofs_cannot_be_sealed() -> None:
    subject = _subject("candidate_review")
    items = tuple(
        replace(
            _item("candidate_review", evidence_class, subject),
            authentication_evidence_digest=E,
        )
        for evidence_class in STAGE_PROFILES["candidate_review"].required_classes
    )
    manifest = EvidenceManifest("evidence-bundle/v1", "candidate_review", subject, D, NOW, items)

    with pytest.raises(EvidenceViolation, match="producer authentication failed"):
        seal_manifest(
            manifest,
            producer_policies=PRODUCER_POLICIES,
            authenticator=_authenticate_producer,
            expected_environment=_environment(),
            as_of=LATER,
        )


def test_trusted_producer_cannot_sign_outside_its_profile_class_permissions() -> None:
    subject = _subject("completion")
    items = [
        _item("completion", evidence_class, subject)
        for evidence_class in STAGE_PROFILES["completion"].required_classes
    ]
    index = next(i for i, item in enumerate(items) if item.evidence_class == "deployment")
    ci_policy = PRODUCER_POLICIES["ci/github"]
    unauthorized = replace(
        items[index],
        producer=EvidenceProducer("ci/github", ci_policy.authority_digest, "AUTOMATED"),
        authentication_evidence_digest="",
    )
    unauthorized = replace(
        unauthorized,
        authentication_evidence_digest=_producer_proof(
            unauthorized.producer.producer_id,
            unauthorized.producer.authority_digest,
            evidence_authentication_payload(unauthorized, D),
        ),
    )
    items[index] = unauthorized
    manifest = EvidenceManifest("evidence-bundle/v1", "completion", subject, D, NOW, tuple(items))

    with pytest.raises(EvidenceViolation, match="not authorized for profile, class, or mode"):
        seal_manifest(
            manifest,
            producer_policies=PRODUCER_POLICIES,
            authenticator=_authenticate_producer,
            expected_environment=_environment(),
            as_of=LATER,
        )


def test_unknown_evidence_schema_version_fails_closed() -> None:
    bundle, _ = _bundle("candidate_review")
    future = replace(bundle.manifest, schema_version="evidence-bundle/v999")

    with pytest.raises(EvidenceViolation, match="unsupported evidence schema version"):
        seal_manifest(
            future,
            producer_policies=PRODUCER_POLICIES,
            authenticator=_authenticate_producer,
            expected_environment=_environment(),
            as_of=LATER,
        )


def test_producer_proofs_cannot_be_reused_under_another_manifest_policy() -> None:
    bundle, subject = _bundle("candidate_review")
    changed_manifest = replace(bundle.manifest, policy_digest=E)
    planted = SealedEvidenceBundle(changed_manifest, changed_manifest.digest)

    result = verify_bundle(
        planted,
        expected_profile="candidate_review",
        expected_subject=subject,
        expected_policy_digest=E,
        producer_policies=PRODUCER_POLICIES,
        authenticator=_authenticate_producer,
        expected_environment=_environment(),
        as_of=LATER,
    )

    assert not result.valid
    assert any("producer authentication failed" in reason for reason in result.reasons)


def test_promotion_evidence_without_expiry_cannot_remain_valid_indefinitely() -> None:
    bundle, _ = _bundle("candidate_review")
    items = list(bundle.manifest.items)
    unsigned = replace(items[0], expires_at="", authentication_evidence_digest="")
    items[0] = replace(
        unsigned,
        authentication_evidence_digest=_producer_proof(
            unsigned.producer.producer_id,
            unsigned.producer.authority_digest,
            evidence_authentication_payload(unsigned, D),
        ),
    )
    manifest = replace(bundle.manifest, items=tuple(items))

    with pytest.raises(EvidenceViolation, match="promotion evidence expiry is absent"):
        seal_manifest(
            manifest,
            producer_policies=PRODUCER_POLICIES,
            authenticator=_authenticate_producer,
            expected_environment=_environment(),
            as_of="2036-08-20T12:30:00Z",
        )


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("missing", "missing required evidence class"),
        ("wrong_subject", "wrong subject digest"),
        ("skipped", "result is HOLD"),
        ("mutable_comment", "only a pointer"),
        ("stale", "evidence is stale"),
        ("tool_drift", "executable digest is malformed"),
        ("environment_drift", "execution environment is inapplicable"),
    ],
)
def test_planted_false_done_evidence_fails_closed(mutation: str, reason: str) -> None:
    bundle, subject = _bundle("completion")
    items = list(bundle.manifest.items)
    if mutation == "missing":
        items = items[:-1]
    elif mutation == "wrong_subject":
        items[0] = replace(items[0], subject_digest=E)
    elif mutation == "skipped":
        items[0] = replace(items[0], result="HOLD")
    elif mutation == "mutable_comment":
        items[0] = replace(items[0], medium="PR_COMMENT")
    elif mutation == "stale":
        items[0] = replace(items[0], expires_at=NOW)
    elif mutation == "tool_drift":
        items[0] = replace(items[0], tool=replace(items[0].tool, executable_digest="latest"))
    else:
        sensitive_index = next(
            index
            for index, item in enumerate(items)
            if item.evidence_class in STAGE_PROFILES["completion"].environment_sensitive_classes
        )
        items[sensitive_index] = replace(
            items[sensitive_index], environment=_environment(runtime="cpython-3.13.0")
        )
    manifest = replace(bundle.manifest, items=tuple(items))
    planted = SealedEvidenceBundle(manifest, manifest.digest)

    decision = assess_completion(
        planted,
        subject=subject,
        policy_digest=D,
        environment=_environment(),
        as_of=LATER,
        producer_policies=PRODUCER_POLICIES,
        authenticator=_authenticate_producer,
    )

    assert not decision.admitted
    assert decision.outcome == "FALSE_DONE_HOLD"
    assert any(reason in item for item in decision.reasons)


def test_tampering_after_seal_is_detected() -> None:
    bundle, subject = _bundle("completion")
    tampered = replace(bundle, manifest=replace(bundle.manifest, created_at=LATER))

    result = verify_bundle(
        tampered,
        expected_profile="completion",
        expected_subject=subject,
        expected_policy_digest=D,
        producer_policies=PRODUCER_POLICIES,
        authenticator=_authenticate_producer,
        expected_environment=_environment(),
        as_of=LATER,
    )

    assert not result.valid
    assert result.reasons[0] == "sealed bundle digest mismatch"


def test_readiness_binds_frozen_base_head_and_prospective_tree() -> None:
    bundle, subject = _bundle("candidate_review")
    assert assess_readiness(
        bundle,
        subject=subject,
        policy_digest=D,
        environment=_environment(),
        as_of=LATER,
        producer_policies=PRODUCER_POLICIES,
        authenticator=_authenticate_producer,
    ).admitted

    changed_base = replace(subject, protected_base_sha=BASE)
    held = assess_readiness(
        bundle,
        subject=changed_base,
        policy_digest=D,
        environment=_environment(),
        as_of=LATER,
        producer_policies=PRODUCER_POLICIES,
        authenticator=_authenticate_producer,
    )

    assert not held.admitted
    assert "wrong exact subject" in held.reasons


def test_immutable_store_retries_are_idempotent_and_conflicts_fail(tmp_path: Path) -> None:
    bundle, _ = _bundle("completion")
    store = ImmutableEvidenceStore(tmp_path)

    assert store.append(bundle, event_id="complete:1") == bundle.bundle_digest
    assert store.append(bundle, event_id="complete:1") == bundle.bundle_digest
    assert len(store.read_events()) == 1

    other, _ = _bundle("candidate_review")
    with pytest.raises(EvidenceViolation, match="reused"):
        store.append(other, event_id="complete:1")


def test_idempotent_retry_recreates_a_missing_object_but_rejects_corruption(
    tmp_path: Path,
) -> None:
    bundle, _ = _bundle("completion")
    store = ImmutableEvidenceStore(tmp_path)
    store.append(bundle, event_id="complete:1")
    object_path = store.objects / f"{bundle.bundle_digest.replace(':', '-')}.json"
    object_path.unlink()

    assert store.append(bundle, event_id="complete:1") == bundle.bundle_digest
    assert object_path.exists()
    object_path.write_text("{}")
    with pytest.raises(EvidenceViolation, match="different bytes"):
        store.append(bundle, event_id="complete:1")


def test_immutable_store_keyed_retry_repairs_only_an_incomplete_final_tail(
    tmp_path: Path,
) -> None:
    bundle, _ = _bundle("completion")
    store = ImmutableEvidenceStore(tmp_path)
    store.append(bundle, event_id="complete:1")
    with store.events.open("ab") as stream:
        stream.write(b'{"event_id":"complete:2"')

    with pytest.raises(EvidenceViolation, match="invalid JSON event"):
        store.read_events()

    assert store.append(bundle, event_id="complete:2") == bundle.bundle_digest
    assert [event["event_id"] for event in store.read_events()] == ["complete:1", "complete:2"]

    with store.events.open("ab") as stream:
        stream.write(b"not-json\n")
    with pytest.raises(EvidenceViolation, match="invalid JSON event"):
        store.append(bundle, event_id="complete:3")


def test_duplicate_evidence_identity_is_rejected() -> None:
    bundle, _ = _bundle("candidate_review")
    duplicate = replace(bundle.manifest, items=(*bundle.manifest.items, bundle.manifest.items[0]))

    with pytest.raises(EvidenceViolation, match="duplicate evidence id"):
        seal_manifest(
            duplicate,
            producer_policies=PRODUCER_POLICIES,
            authenticator=_authenticate_producer,
            expected_environment=_environment(),
            as_of=LATER,
        )


def test_green_summary_with_skipped_required_test_cannot_satisfy_readiness() -> None:
    bundle, subject = _bundle("candidate_review")
    items = list(bundle.manifest.items)
    index = next(
        index for index, item in enumerate(items) if item.evidence_class == "required_checks"
    )
    items[index] = replace(
        items[index],
        result="PASS",
        executed_count=2,
        passed_count=1,
        skipped_count=1,
    )
    manifest = replace(bundle.manifest, items=tuple(items))
    planted = SealedEvidenceBundle(manifest, manifest.digest)

    held = assess_readiness(
        planted,
        subject=subject,
        policy_digest=D,
        environment=_environment(),
        as_of=LATER,
        producer_policies=PRODUCER_POLICIES,
        authenticator=_authenticate_producer,
    )

    assert not held.admitted
    assert any("skipped" in reason for reason in held.reasons)


@pytest.mark.parametrize(
    ("passed", "failed"),
    [
        (0, 2),
        (100, 1),
    ],
)
def test_meaningful_red_requires_reconciled_execution_totals(passed: int, failed: int) -> None:
    bundle, _ = _bundle("pre_code")
    items = list(bundle.manifest.items)
    index = next(
        index for index, item in enumerate(items) if item.evidence_class == "meaningful_red"
    )
    malformed = replace(
        items[index],
        executed_count=1,
        passed_count=passed,
        failed_count=failed,
        authentication_evidence_digest="",
    )
    malformed = replace(
        malformed,
        authentication_evidence_digest=_producer_proof(
            malformed.producer.producer_id,
            malformed.producer.authority_digest,
            evidence_authentication_payload(malformed, D),
        ),
    )
    items[index] = malformed
    manifest = replace(bundle.manifest, items=tuple(items))

    with pytest.raises(EvidenceViolation, match="red counts are inconsistent"):
        seal_manifest(
            manifest,
            producer_policies=PRODUCER_POLICIES,
            authenticator=_authenticate_producer,
            expected_environment=_environment(),
            as_of=LATER,
        )


@pytest.mark.parametrize("source", ["REVIEW_REQUIRED", "PR_READY"])
def test_stale_advisory_evidence_has_exact_candidate_reverification_path(source: str) -> None:
    assert (
        verification_recovery_state(source=source, fresh_intelligence_obtainable=True)
        == "VERIFICATION_FAILED"
    )
    assert (
        verification_recovery_state(
            source="VERIFICATION_FAILED",
            fresh_intelligence_obtainable=True,
            refresh_passed=True,
        )
        == "REVIEW_REQUIRED"
    )
    assert (
        verification_recovery_state(source=source, fresh_intelligence_obtainable=False) == "BLOCKED"
    )
