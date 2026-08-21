"""Safe evidence projection for pre-byte contract intake lineage."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from hashlib import sha256

from pmpe.contracts.digest import canonical_digest
from pmpe.contracts.intake import IntakeOutcome

_IMMUTABLE_OBJECT_REF = re.compile(r"^objects/sha256-[0-9a-f]{64}\.json$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
ReconciliationAuthenticator = Callable[[str, str, Mapping[str, object], str], bool]


@dataclass(frozen=True)
class IntakeLineageEvidence:
    lineage_id: str
    attempt_id: str
    reservation_digest: str
    quarantine_handle: str
    quarantine_expires_at: str
    receipt_digest: str
    envelope_digest: str
    correction_lineage_id: str
    correction_attempt_id: str
    admission_status: str
    diagnostic_codes: tuple[str, ...]
    disposition_digest: str
    deletion_or_reconciliation_digest: str
    immutable_payload_ref: str

    @property
    def digest(self) -> str:
        return canonical_digest(asdict(self))


def reconciliation_authentication_payload(
    outcome: IntakeOutcome, reconciliation_attestation_digest: str
) -> dict[str, object]:
    return {
        "lineage_id": outcome.reservation.lineage_id,
        "attempt_id": outcome.reservation.attempt_id,
        "quarantine_handle": outcome.reservation.quarantine_handle,
        "admission_status": outcome.status,
        "disposition_digest": canonical_digest(outcome.disposition.as_dict()),
        "reconciliation_attestation_digest": reconciliation_attestation_digest,
    }


def project_intake_evidence(
    outcome: IntakeOutcome,
    *,
    admitted_payload_ref: str = "",
    reconciliation_attestation_digest: str = "",
    reconciliation_authority_id: str = "",
    reconciliation_authority_digest: str = "",
    reconciliation_authentication_evidence_digest: str = "",
    trusted_reconciliation_authorities: Mapping[str, str] | None = None,
    reconciliation_authenticator: ReconciliationAuthenticator | None = None,
) -> IntakeLineageEvidence:
    reservation = outcome.reservation
    receipt = outcome.receipt
    correction = reservation.correction_reference
    if outcome.status == "ADMITTED":
        if (
            not _IMMUTABLE_OBJECT_REF.fullmatch(admitted_payload_ref)
            or outcome.admitted_payload is None
        ):
            raise ValueError("admitted content requires an immutable payload reference")
        expected_payload_ref = f"objects/sha256-{sha256(outcome.admitted_payload).hexdigest()}.json"
        if admitted_payload_ref != expected_payload_ref:
            raise ValueError("immutable payload reference does not match admitted bytes")
    elif admitted_payload_ref:
        raise ValueError("rejected raw content must never enter immutable evidence")

    deletion = outcome.deletion_attestation
    deletion_digest = (
        canonical_digest(asdict(deletion)) if deletion is not None and deletion.deleted else ""
    )
    authenticated_reconciliation = False
    if reconciliation_attestation_digest:
        trusted_authority = (trusted_reconciliation_authorities or {}).get(
            reconciliation_authority_id, ""
        )
        payload = reconciliation_authentication_payload(outcome, reconciliation_attestation_digest)
        try:
            authenticated_reconciliation = bool(
                _DIGEST.fullmatch(reconciliation_attestation_digest)
                and trusted_authority
                and trusted_authority == reconciliation_authority_digest
                and reconciliation_authenticator is not None
                and reconciliation_authenticator(
                    reconciliation_authority_id,
                    trusted_authority,
                    payload,
                    reconciliation_authentication_evidence_digest,
                )
            )
        except Exception:
            authenticated_reconciliation = False
        if not authenticated_reconciliation and not deletion_digest:
            raise ValueError("reconciliation evidence is not independently authenticated")
    terminal_proof = deletion_digest or (
        reconciliation_attestation_digest if authenticated_reconciliation else ""
    )
    if outcome.status != "ADMITTED" and not terminal_proof:
        raise ValueError("rejected intake requires deletion or reconciliation evidence")
    return IntakeLineageEvidence(
        lineage_id=reservation.lineage_id,
        attempt_id=reservation.attempt_id,
        reservation_digest=canonical_digest(reservation.as_dict()),
        quarantine_handle=reservation.quarantine_handle,
        quarantine_expires_at=reservation.expires_at,
        receipt_digest=canonical_digest(receipt.as_dict()) if receipt is not None else "",
        envelope_digest=receipt.fingerprint if receipt is not None else "",
        correction_lineage_id=correction.lineage_id if correction else "",
        correction_attempt_id=correction.attempt_id if correction else "",
        admission_status=outcome.status,
        diagnostic_codes=tuple(sorted(finding.code for finding in outcome.findings)),
        disposition_digest=canonical_digest(outcome.disposition.as_dict()),
        deletion_or_reconciliation_digest=terminal_proof,
        immutable_payload_ref=admitted_payload_ref,
    )
