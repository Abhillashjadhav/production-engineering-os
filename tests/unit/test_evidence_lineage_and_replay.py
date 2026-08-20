from __future__ import annotations

import pytest

from pmpe.audit.intake_evidence import project_intake_evidence
from pmpe.audit.replay import ProposalAdmission, proposal_subject, replay_admission
from pmpe.contracts.digest import canonical_digest
from pmpe.contracts.intake import (
    CorrectionReference,
    DeletionAttestation,
    IntakeDisposition,
    IntakeFinding,
    IntakeOutcome,
    IntakeReceipt,
    IntakeReservation,
)

D = "sha256:" + "a" * 64


def _outcome(status: str) -> IntakeOutcome:
    correction = CorrectionReference("LINEAGE-OLD", "ATTEMPT-OLD")
    reservation = IntakeReservation(
        "LINEAGE-ONE",
        "ATTEMPT-ONE",
        "QUARANTINE-ONE",
        "2026-08-20T00:00:00Z",
        "PUBLISHER-ONE",
        "API",
        D,
        "KEY-ONE",
        "2026-08-21T00:00:00Z",
        "application/json",
        correction,
    )
    receipt = IntakeReceipt(
        reservation.lineage_id,
        reservation.attempt_id,
        "2026-08-20T00:00:01Z",
        reservation.publisher,
        reservation.channel,
        "application/json",
        reservation.quarantine_handle,
        "KEY-ONE",
        D,
        correction,
    )
    finding = IntakeFinding("MALFORMED", "diagnostic intentionally not retained")
    disposition = IntakeDisposition(
        reservation.lineage_id,
        reservation.attempt_id,
        status,
        "2026-08-20T00:00:02Z",
        () if status == "ADMITTED" else (finding,),
    )
    deletion = DeletionAttestation(
        reservation.lineage_id,
        reservation.attempt_id,
        reservation.quarantine_handle,
        True,
        "2026-08-20T00:00:03Z",
    )
    return IntakeOutcome(
        status,
        reservation,
        receipt,
        disposition,
        deletion,
        () if status == "ADMITTED" else (finding,),
        b'{"safe": true}' if status == "ADMITTED" else None,
        False,
    )


def test_rejected_intake_keeps_safe_lineage_and_deletion_but_never_raw_bytes() -> None:
    evidence = project_intake_evidence(_outcome("REJECTED"))
    rendered = repr(evidence)
    assert evidence.lineage_id == "LINEAGE-ONE"
    assert evidence.correction_attempt_id == "ATTEMPT-OLD"
    assert evidence.diagnostic_codes == ("MALFORMED",)
    assert evidence.immutable_payload_ref == ""
    assert "diagnostic intentionally not retained" not in rendered
    assert "safe" not in rendered


def test_rejected_intake_cannot_publish_a_raw_payload_reference() -> None:
    with pytest.raises(ValueError, match="rejected raw content"):
        project_intake_evidence(_outcome("REJECTED"), admitted_payload_ref="objects/raw")


def test_admitted_intake_requires_content_addressed_payload_reference() -> None:
    with pytest.raises(ValueError, match="immutable payload reference"):
        project_intake_evidence(_outcome("ADMITTED"))
    evidence = project_intake_evidence(
        _outcome("ADMITTED"), admitted_payload_ref=f"objects/{D}.json"
    )
    assert evidence.immutable_payload_ref.endswith(f"{D}.json")


def test_exact_proposal_replay_is_deterministic_and_regeneration_is_new_subject() -> None:
    proposal = {"change": "bounded"}
    inputs = {"contract": D}
    policy = {"version": "v1"}

    def evaluator(proposal: object, inputs: object, policy: object) -> tuple[str, tuple[str, ...]]:
        del proposal, inputs, policy
        return "ADMITTED", (D,)

    admission = ProposalAdmission(
        proposal_subject(proposal),
        canonical_digest(inputs),
        canonical_digest(policy),
        "ADMITTED",
        (D,),
    )
    assert replay_admission(
        admission, proposal=proposal, inputs=inputs, policy=policy, evaluator=evaluator
    )
    assert not replay_admission(
        admission,
        proposal={"change": "regenerated"},
        inputs=inputs,
        policy=policy,
        evaluator=evaluator,
    )
    assert admission.proposal_digest != proposal_subject({"change": "regenerated"})
