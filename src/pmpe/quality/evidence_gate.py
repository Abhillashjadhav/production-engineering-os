"""Readiness and completion decisions backed only by sealed evidence bundles."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from pmpe.audit.evidence import (
    EnvironmentFingerprint,
    EvidenceAuthenticator,
    EvidenceProducerPolicy,
    EvidenceSubject,
    EvidenceValidation,
    SealedEvidenceBundle,
    verify_bundle,
)


@dataclass(frozen=True)
class EvidenceGateDecision:
    admitted: bool
    outcome: str
    bundle_digest: str
    completeness: float
    reasons: tuple[str, ...]


def verification_recovery_state(
    *, source: str, fresh_intelligence_obtainable: bool, refresh_passed: bool = False
) -> str:
    """Ordinary staleness is recoverable; only unavailable verification blocks."""

    if source not in {"REVIEW_REQUIRED", "PR_READY", "VERIFICATION_FAILED"}:
        raise ValueError("source is not an exact-candidate verification state")
    if not fresh_intelligence_obtainable:
        return "BLOCKED"
    if source == "VERIFICATION_FAILED" and refresh_passed:
        return "REVIEW_REQUIRED"
    return "VERIFICATION_FAILED"


def _decision(
    bundle: SealedEvidenceBundle,
    validation: EvidenceValidation,
    *,
    success: str,
    failure: str,
) -> EvidenceGateDecision:
    return EvidenceGateDecision(
        admitted=validation.valid and validation.completeness == 1.0,
        outcome=success if validation.valid and validation.completeness == 1.0 else failure,
        bundle_digest=bundle.bundle_digest,
        completeness=validation.completeness,
        reasons=validation.reasons,
    )


def assess_readiness(
    bundle: SealedEvidenceBundle,
    *,
    subject: EvidenceSubject,
    policy_digest: str,
    environment: EnvironmentFingerprint,
    as_of: str,
    producer_policies: Mapping[str, EvidenceProducerPolicy],
    authenticator: EvidenceAuthenticator,
) -> EvidenceGateDecision:
    validation = verify_bundle(
        bundle,
        expected_profile="candidate_review",
        expected_subject=subject,
        expected_policy_digest=policy_digest,
        producer_policies=producer_policies,
        authenticator=authenticator,
        expected_environment=environment,
        as_of=as_of,
    )
    return _decision(bundle, validation, success="READY", failure="HOLD")


def assess_merge_admission(
    bundle: SealedEvidenceBundle,
    *,
    subject: EvidenceSubject,
    policy_digest: str,
    environment: EnvironmentFingerprint,
    as_of: str,
    producer_policies: Mapping[str, EvidenceProducerPolicy],
    authenticator: EvidenceAuthenticator,
) -> EvidenceGateDecision:
    validation = verify_bundle(
        bundle,
        expected_profile="merge_admission",
        expected_subject=subject,
        expected_policy_digest=policy_digest,
        producer_policies=producer_policies,
        authenticator=authenticator,
        expected_environment=environment,
        as_of=as_of,
    )
    return _decision(bundle, validation, success="MERGE_ADMITTED", failure="HOLD")


def assess_completion(
    bundle: SealedEvidenceBundle,
    *,
    subject: EvidenceSubject,
    policy_digest: str,
    environment: EnvironmentFingerprint,
    as_of: str,
    producer_policies: Mapping[str, EvidenceProducerPolicy],
    authenticator: EvidenceAuthenticator,
) -> EvidenceGateDecision:
    validation = verify_bundle(
        bundle,
        expected_profile="completion",
        expected_subject=subject,
        expected_policy_digest=policy_digest,
        producer_policies=producer_policies,
        authenticator=authenticator,
        expected_environment=environment,
        as_of=as_of,
    )
    return _decision(bundle, validation, success="COMPLETED", failure="FALSE_DONE_HOLD")
