"""Sequence checks for the distinct support-package v1 release producer.

The package reader separately checks its validated package contract, five-field
receipt, fixed candidate surface, and canonical runtime. This producer does not
emit a barebones acceptance plan or a coder/verification attempt.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from pmpe.contracts.canonical import strict_loads
from pmpe.contracts.release_gates import compile_release_gates
from pmpe.evidence.ledger import EvidenceIntegrityError, EvidenceLedger


def validate_package_release(
    ledger: EvidenceLedger,
    events: Sequence[Mapping[str, Any]],
    *,
    expected_head_digest: str | None = None,
) -> None:
    if [event.get("event_type") for event in events] != ["contract_validated", "release_ready"]:
        raise EvidenceIntegrityError("package release gate event sequence is inconsistent")
    if expected_head_digest is not None and (
        re.fullmatch(r"sha256:[0-9a-f]{64}", expected_head_digest) is None
        or events[-1].get("event_digest") != expected_head_digest
    ):
        raise EvidenceIntegrityError("release evidence does not match trusted expected head")
    if events[0].get("state") != "VALIDATED" or events[-1].get("state") != "RELEASE_READY":
        raise EvidenceIntegrityError("package release event state is inconsistent")
    if "release_gate_evidence_digest" in events[-1].get("payload", {}):
        raise EvidenceIntegrityError("package release producer does not emit release gate evidence")
    try:
        contract = strict_loads(ledger.read_blob(events[0]["payload"]["contract_digest"]))
    except (KeyError, ValueError) as exc:
        raise EvidenceIntegrityError("package release contract evidence is malformed") from exc
    if not isinstance(contract, dict):
        raise EvidenceIntegrityError("package release contract evidence is malformed")
    diagnostics: list[str] = []
    gates = compile_release_gates(
        contract,
        criterion_ids=frozenset(),
        diagnostic=lambda code, _subject, _message: diagnostics.append(code),
    )
    if gates or diagnostics:
        raise EvidenceIntegrityError(
            "package release producer cannot carry release gate declarations"
        )
