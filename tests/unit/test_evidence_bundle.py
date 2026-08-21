from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from pmpe.audit.evidence import (
    STAGE_PROFILES,
    EnvironmentFingerprint,
    EvidenceItem,
    EvidenceManifest,
    EvidenceProducer,
    EvidenceSubject,
    EvidenceViolation,
    ImmutableEvidenceStore,
    SealedEvidenceBundle,
    ToolIdentity,
    seal_manifest,
    verify_bundle,
)
from pmpe.contracts.digest import canonical_digest
from pmpe.quality.evidence_gate import (
    assess_completion,
    assess_readiness,
    verification_recovery_state,
)

D = "sha256:" + "a" * 64
E = "sha256:" + "b" * 64
SHA = "c" * 40
BASE = "d" * 40
NOW = "2026-08-20T12:00:00Z"
LATER = "2026-08-20T12:30:00Z"


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
    return EvidenceItem(
        evidence_id=f"{profile}:{evidence_class}",
        evidence_class=evidence_class,
        stage=profile,
        subject_digest=subject.digest,
        result=result,
        producer=EvidenceProducer("ci/github", D, "AUTOMATED"),
        tool=ToolIdentity("pytest", "8.4.1", D, E),
        environment=environment or _environment(),
        invocation=("python", "-m", "pytest", "-q"),
        output_digest=E,
        observed_at=NOW,
        retention_class="release+incident",
        authentication_evidence_digest=D,
        attestation_format="DSSE-v1",
        medium=medium,
        expires_at=expires_at,
        executed_count=executed,
        passed_count=1 if evidence_class == "required_checks" else 0,
        failed_count=1 if evidence_class == "meaningful_red" else 0,
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
    return seal_manifest(manifest, expected_environment=_environment(), as_of=LATER), subject


def test_sealed_bundle_is_content_addressed_and_reconstructible() -> None:
    bundle, subject = _bundle("completion")

    report = verify_bundle(
        bundle,
        expected_profile="completion",
        expected_subject=subject,
        expected_policy_digest=D,
        expected_environment=_environment(),
        as_of=LATER,
    )

    assert report.valid
    assert report.completeness == 1.0
    assert bundle.bundle_digest == canonical_digest(bundle.manifest)


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
    ).admitted

    changed_base = replace(subject, protected_base_sha=BASE)
    held = assess_readiness(
        bundle,
        subject=changed_base,
        policy_digest=D,
        environment=_environment(),
        as_of=LATER,
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
        seal_manifest(duplicate, expected_environment=_environment(), as_of=LATER)


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
    )

    assert not held.admitted
    assert any("skipped" in reason for reason in held.reasons)


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
