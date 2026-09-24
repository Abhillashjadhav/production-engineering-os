"""Read-only release-gate binding checks; hash consistency is not authentication."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from pmpe.contracts.canonical import canonical_digest, strict_loads
from pmpe.contracts.release_gates import compile_release_gates
from pmpe.evidence.ledger import EvidenceIntegrityError, EvidenceLedger

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


def _object(ledger: EvidenceLedger, digest: Any) -> dict[str, Any]:
    if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
        raise EvidenceIntegrityError("release gate evidence digest is malformed")
    try:
        value = strict_loads(ledger.read_blob(digest), "application/json")
    except ValueError as exc:
        raise EvidenceIntegrityError("release gate evidence blob is malformed") from exc
    if not isinstance(value, dict):
        raise EvidenceIntegrityError("release gate evidence blob must be an object")
    return value


def _check_results(expected: list[dict[str, Any]], results: Any) -> None:
    if not isinstance(results, list) or len(results) != len(expected):
        raise EvidenceIntegrityError("release gate result inventory is incomplete")
    by_id = {item["gate_id"]: item for item in expected}
    seen: set[str] = set()
    for result in results:
        if not isinstance(result, dict):
            raise EvidenceIntegrityError("release gate result is malformed")
        gate_id = result.get("gate_id")
        if not isinstance(gate_id, str) or gate_id in seen or gate_id not in by_id:
            raise EvidenceIntegrityError("release gate result identity is inconsistent")
        seen.add(gate_id)
        gate = by_id[gate_id]
        if result.get("status") != "PASS":
            raise EvidenceIntegrityError("release gate does not have PASS evidence")
        if "binding" in gate:
            if (
                canonical_digest(result.get("binding")) != canonical_digest(gate["binding"])
                or not isinstance(result.get("evidence"), dict)
                or not result["evidence"]
            ):
                raise EvidenceIntegrityError("release gate process binding is inconsistent")
            continue
        refs = gate["acceptance_criterion_refs"]
        if canonical_digest(result.get("acceptance_criterion_refs")) != canonical_digest(refs):
            raise EvidenceIntegrityError("release gate criterion binding is inconsistent")
        checks = result.get("criterion_results")
        if not isinstance(checks, list) or len(checks) != len(refs):
            raise EvidenceIntegrityError("release gate criterion inventory is incomplete")
        observed = []
        for check in checks:
            if (
                not isinstance(check, dict)
                or check.get("status") != "PASS"
                or check.get("findings") != []
                or not isinstance(check.get("criterion_id"), str)
            ):
                raise EvidenceIntegrityError("release gate criterion lacks explicit PASS evidence")
            observed.append(check["criterion_id"])
        if sorted(observed) != sorted(refs):
            raise EvidenceIntegrityError("release gate criterion inventory is inconsistent")


def validate_release_gate_evidence(
    ledger: EvidenceLedger,
    events: Sequence[Mapping[str, Any]],
    *,
    expected_head_digest: str | None = None,
) -> None:
    """Validate bindings with the reader's existing read limits, without running code.

    A caller-supplied expected head must come from outside this evidence store to
    detect an otherwise self-consistent rewrite. No signature or owner identity
    authentication is inferred from an internally valid chain.
    """

    if not events:
        raise EvidenceIntegrityError("release gate evidence ledger is empty")
    terminal = events[-1]
    if expected_head_digest is not None and (
        not _DIGEST.fullmatch(expected_head_digest)
        or terminal.get("event_digest") != expected_head_digest
    ):
        raise EvidenceIntegrityError("release evidence does not match trusted expected head")
    if terminal.get("event_type") != "release_ready":
        return
    validations = [event for event in events if event.get("event_type") == "contract_validated"]
    if len(validations) != 1:
        raise EvidenceIntegrityError("release gate evidence requires one contract validation")
    validation = validations[0]
    metadata, payload = validation.get("payload"), terminal.get("payload")
    if not isinstance(metadata, dict) or not isinstance(payload, dict):
        raise EvidenceIntegrityError("release gate validation metadata is malformed")
    validation_blobs = validation.get("blob_digests", [])
    contract_blob = metadata.get("contract_digest")
    if contract_blob not in validation_blobs:
        raise EvidenceIntegrityError("release gate contract blob is not bound")
    contract = _object(ledger, contract_blob)
    subject = canonical_digest(contract)
    gate_events = [
        event for event in events if event.get("event_type") == "release_gates_evaluated"
    ]
    diagnostics: list[str] = []
    # Discovery also rejects misplaced/empty declarations. Missing criteria are
    # checked after the retained plan is loaded below.
    raw_criteria = contract.get("acceptance_criteria", {})
    criterion_ids = (
        frozenset(raw_criteria)
        if isinstance(raw_criteria, dict)
        else frozenset(
            item["id"]
            for item in raw_criteria
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        )
        if isinstance(raw_criteria, list)
        else frozenset()
    )
    gates = compile_release_gates(
        contract,
        criterion_ids=criterion_ids,
        diagnostic=lambda code, _subject, _message: diagnostics.append(code),
    )
    if diagnostics:
        raise EvidenceIntegrityError(
            "release gate declaration is invalid: " + ", ".join(diagnostics)
        )
    if not gates:
        if gate_events or "release_gate_evidence_digest" in payload:
            raise EvidenceIntegrityError("release gate evidence has no declared gate")
        return
    if validation.get("subject_digest") != subject or terminal.get("subject_digest") != subject:
        raise EvidenceIntegrityError("release gate contract identity is inconsistent")
    approval = metadata.get("approval", {})
    receipt_blob = approval.get("receipt_blob_digest") if isinstance(approval, dict) else None
    if receipt_blob is not None and not isinstance(receipt_blob, str):
        raise EvidenceIntegrityError("release gate approval reference is malformed")
    plan_blobs = [
        digest for digest in validation_blobs if digest not in {contract_blob, receipt_blob}
    ]
    if len(plan_blobs) != 1:
        raise EvidenceIntegrityError("release gate plan blob is not uniquely bound")
    plan = _object(ledger, plan_blobs[0])
    criteria = plan.get("criteria")
    if not isinstance(criteria, list) or any(
        not isinstance(item, dict) or not isinstance(item.get("criterion_id"), str)
        for item in criteria
    ):
        raise EvidenceIntegrityError("release gate compiled criteria are malformed")
    compiled_ids = frozenset(item["criterion_id"] for item in criteria)
    compile_release_gates(
        contract,
        criterion_ids=compiled_ids,
        diagnostic=lambda code, _subject, _message: diagnostics.append(code),
    )
    if diagnostics:
        raise EvidenceIntegrityError("release gate references an uncompiled criterion")
    plan_digest = metadata.get("plan_digest")
    projection = {key: value for key, value in plan.items() if key != "plan_digest"}
    expected = [gate.as_dict() for gate in gates]
    if (
        plan.get("plan_digest") != plan_digest
        or canonical_digest(projection) != plan_digest
        or plan.get("contract_digest") != subject
        or canonical_digest(plan.get("release_gates")) != canonical_digest(expected)
    ):
        raise EvidenceIntegrityError("release gate plan binding is inconsistent")
    digest = payload.get("release_gate_evidence_digest")
    if digest not in terminal.get("blob_digests", []) or not gate_events:
        raise EvidenceIntegrityError("release gate evidence is missing from release")
    evidence = _object(ledger, digest)
    gate_event = gate_events[-1]
    if (
        digest not in gate_event.get("blob_digests", [])
        or gate_event.get("state") != "VERIFYING"
        or gate_event.get("subject_digest") != subject
        or gate_event.get("payload") != evidence
        or evidence.get("contract_digest") != subject
        or evidence.get("plan_digest") != plan_digest
        or evidence.get("candidate_digest") != payload.get("candidate_digest")
        or evidence.get("candidate_digest") not in gate_event.get("blob_digests", [])
        or type(evidence.get("attempt")) is not int
        or evidence["attempt"] < 1
    ):
        raise EvidenceIntegrityError("release gate evidence does not bind the released candidate")
    _check_results(expected, evidence.get("gates"))
