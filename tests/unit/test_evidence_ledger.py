from __future__ import annotations

import json
from pathlib import Path

import pytest

from pmpe.contracts.canonical import canonical_digest
from pmpe.evidence.ledger import EvidenceIntegrityError, EvidenceLedger


def test_ledger_writes_only_the_frozen_two_path_shapes(tmp_path: Path) -> None:
    ledger = EvidenceLedger(tmp_path, "run-001")
    blob = ledger.put_blob(b"verification output")
    event = ledger.append(
        event_type="verification_completed",
        state="VERIFYING",
        subject_digest=canonical_digest({"candidate": 1}),
        blob_digests=(blob,),
        payload={"passed": True},
    )

    assert ledger.events_path == tmp_path / ".pmpe/runs/run-001/events.jsonl"
    assert (tmp_path / ".pmpe/blobs" / blob.removeprefix("sha256:")).is_file()
    assert event["schema_version"] == "1.0.0"
    assert event["run_id"] == "run-001"
    assert tuple(ledger.verify()) == (event,)


def test_resume_continues_the_existing_hash_chain(tmp_path: Path) -> None:
    subject = canonical_digest({"candidate": 1})
    first = EvidenceLedger(tmp_path, "run-001")
    first_event = first.append(event_type="validated", state="VALIDATED", subject_digest=subject)
    resumed = EvidenceLedger(tmp_path, "run-001")
    second_event = resumed.append(event_type="building", state="BUILDING", subject_digest=subject)

    assert second_event["sequence"] == 2
    assert second_event["previous_digest"] == first_event["event_digest"]


def test_event_tampering_is_detected(tmp_path: Path) -> None:
    ledger = EvidenceLedger(tmp_path, "run-001")
    ledger.append(
        event_type="validated",
        state="VALIDATED",
        subject_digest=canonical_digest({"candidate": 1}),
    )
    event = json.loads(ledger.events_path.read_text())
    event["state"] = "RELEASE_READY"
    ledger.events_path.write_text(json.dumps(event, separators=(",", ":")) + "\n")

    with pytest.raises(EvidenceIntegrityError):
        tuple(ledger.verify())


def test_blob_tampering_is_detected(tmp_path: Path) -> None:
    ledger = EvidenceLedger(tmp_path, "run-001")
    blob = ledger.put_blob(b"original")
    ledger.append(
        event_type="verified",
        state="VERIFYING",
        subject_digest=canonical_digest({"candidate": 1}),
        blob_digests=(blob,),
    )
    (ledger.blobs_directory / blob.removeprefix("sha256:")).write_bytes(b"changed")

    with pytest.raises(EvidenceIntegrityError):
        tuple(ledger.verify())
