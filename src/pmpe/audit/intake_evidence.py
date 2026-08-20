"""Safe evidence projection for pre-byte contract intake lineage."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from pmpe.contracts.digest import canonical_digest
from pmpe.contracts.intake import IntakeOutcome

_IMMUTABLE_OBJECT_REF = re.compile(r"^objects/sha256-[0-9a-f]{64}\.json$")


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


def project_intake_evidence(
    outcome: IntakeOutcome,
    *,
    admitted_payload_ref: str = "",
    reconciliation_attestation_digest: str = "",
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
    elif admitted_payload_ref:
        raise ValueError("rejected raw content must never enter immutable evidence")

    deletion = outcome.deletion_attestation
    deletion_digest = canonical_digest(asdict(deletion)) if deletion is not None else ""
    terminal_proof = deletion_digest or reconciliation_attestation_digest
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
