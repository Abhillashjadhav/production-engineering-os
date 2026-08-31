from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

import pmpe.evidence.ledger as evidence_ledger
from pmpe.contracts.canonical import canonical_digest, canonical_json_bytes
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


def test_commit_guard_keeps_event_private_until_it_passes(tmp_path: Path) -> None:
    ledger = EvidenceLedger(tmp_path, "guarded")
    subject = canonical_digest({"candidate": 1})
    guard_calls = 0

    def approve_commit() -> None:
        nonlocal guard_calls
        guard_calls += 1

    event = ledger.append(
        event_type="released",
        state="RELEASE_READY",
        subject_digest=subject,
        commit_guard=approve_commit,
    )

    assert guard_calls == 2
    assert tuple(ledger.verify()) == (event,)


def test_failed_commit_guard_leaves_no_event_or_staging_file(tmp_path: Path) -> None:
    ledger = EvidenceLedger(tmp_path, "guarded")

    def reject_commit() -> None:
        raise RuntimeError("deadline exceeded")

    with pytest.raises(RuntimeError, match="deadline exceeded"):
        ledger.append(
            event_type="released",
            state="RELEASE_READY",
            subject_digest=canonical_digest({"candidate": 1}),
            commit_guard=reject_commit,
        )

    assert tuple(ledger.verify()) == ()
    assert tuple(ledger.run_directory.iterdir()) == (ledger.events_path,)


def test_guarded_commit_fsyncs_the_run_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = EvidenceLedger(tmp_path, "guarded")
    original_fsync = evidence_ledger.os.fsync
    directory_syncs = 0

    def track_fsync(descriptor: int) -> None:
        nonlocal directory_syncs
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            directory_syncs += 1
        original_fsync(descriptor)

    monkeypatch.setattr(evidence_ledger.os, "fsync", track_fsync)
    ledger.append(
        event_type="released",
        state="RELEASE_READY",
        subject_digest=canonical_digest({"candidate": 1}),
        commit_guard=lambda: None,
    )

    assert directory_syncs == 1


def test_resume_continues_the_existing_hash_chain(tmp_path: Path) -> None:
    subject = canonical_digest({"candidate": 1})
    first = EvidenceLedger(tmp_path, "run-001")
    first_event = first.append(event_type="validated", state="VALIDATED", subject_digest=subject)
    resumed = EvidenceLedger(tmp_path, "run-001", resume=True)
    second_event = resumed.append(event_type="building", state="BUILDING", subject_digest=subject)

    assert second_event["sequence"] == 2
    assert second_event["previous_digest"] == first_event["event_digest"]


def test_completed_run_id_cannot_be_reused_or_resumed(tmp_path: Path) -> None:
    subject = canonical_digest({"candidate": 1})
    ledger = EvidenceLedger(tmp_path, "run-001")
    ledger.append(event_type="released", state="RELEASE_READY", subject_digest=subject)

    with pytest.raises(EvidenceIntegrityError, match="already has"):
        EvidenceLedger(tmp_path, "run-001")
    with pytest.raises(EvidenceIntegrityError, match="terminal"):
        EvidenceLedger(tmp_path, "run-001", resume=True)

    inspection = EvidenceLedger.open_existing(tmp_path, "run-001")
    with pytest.raises(EvidenceIntegrityError, match="read-only"):
        inspection.append(event_type="changed", state="BUILDING", subject_digest=subject)
    with pytest.raises(EvidenceIntegrityError, match="read-only"):
        inspection.put_blob(b"changed")


def test_open_existing_rejects_oversized_blob_before_materializing_it(tmp_path: Path) -> None:
    ledger = EvidenceLedger(tmp_path, "bounded")
    digest = ledger.put_blob(b"x" * 1_025)
    ledger.append(
        event_type="validated",
        state="VALIDATED",
        subject_digest=canonical_digest({"candidate": 1}),
        blob_digests=(digest,),
    )

    with pytest.raises(EvidenceIntegrityError, match="event references an invalid blob") as exc:
        EvidenceLedger.open_existing(tmp_path, "bounded", max_read_bytes=1_024)
    assert exc.value.__cause__ is not None
    assert "blob exceeds size limit" in str(exc.value.__cause__)


def test_open_existing_enforces_aggregate_blob_budget(tmp_path: Path) -> None:
    ledger = EvidenceLedger(tmp_path, "aggregate")
    digests = tuple(ledger.put_blob(bytes([index]) * 600) for index in range(2))
    ledger.append(
        event_type="validated",
        state="VALIDATED",
        subject_digest=canonical_digest({"candidate": 1}),
        blob_digests=digests,
    )

    with pytest.raises(EvidenceIntegrityError, match="aggregate size limit"):
        EvidenceLedger.open_existing(
            tmp_path,
            "aggregate",
            max_read_bytes=1_024,
            max_total_read_bytes=1_500,
        )


def test_verify_reads_a_repeated_blob_digest_only_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = EvidenceLedger(tmp_path, "repeated")
    digest = ledger.put_blob(b"shared")
    subject = canonical_digest({"candidate": 1})
    ledger.append(
        event_type="validated",
        state="VALIDATED",
        subject_digest=subject,
        blob_digests=(digest,),
    )
    ledger.append(
        event_type="building",
        state="BUILDING",
        subject_digest=subject,
        blob_digests=(digest,),
    )
    original_read_blob = EvidenceLedger.read_blob
    reads = 0

    def count_read(self: EvidenceLedger, value: str) -> bytes:
        nonlocal reads
        reads += 1
        return original_read_blob(self, value)

    monkeypatch.setattr(EvidenceLedger, "read_blob", count_read)
    tuple(ledger.verify())
    assert reads == 1


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

    with pytest.raises(EvidenceIntegrityError):
        EvidenceLedger.open_existing(tmp_path, "run-001")


def test_open_existing_rejects_an_event_chain_copied_from_another_run(
    tmp_path: Path,
) -> None:
    source = EvidenceLedger(tmp_path, "source")
    source.append(
        event_type="validated",
        state="VALIDATED",
        subject_digest=canonical_digest({"candidate": 1}),
    )
    target_events = tmp_path / ".pmpe" / "runs" / "target" / "events.jsonl"
    target_events.parent.mkdir(parents=True)
    target_events.write_bytes(source.events_path.read_bytes())

    with pytest.raises(EvidenceIntegrityError, match="run_id mismatch"):
        EvidenceLedger.open_existing(tmp_path, "target")


def test_verify_rejects_a_hash_consistent_non_list_blob_container(tmp_path: Path) -> None:
    ledger = EvidenceLedger(tmp_path, "run-001")
    ledger.append(
        event_type="validated",
        state="VALIDATED",
        subject_digest=canonical_digest({"candidate": 1}),
    )
    event = json.loads(ledger.events_path.read_text())
    event.pop("event_digest")
    event["blob_digests"] = None
    event["event_digest"] = canonical_digest(event)
    ledger.events_path.write_bytes(canonical_json_bytes(event) + b"\n")

    with pytest.raises(EvidenceIntegrityError, match="blob_digests must be a list"):
        tuple(ledger.verify())


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("schema_version", "2.0.0", "schema_version is unsupported"),
        ("sequence", True, "sequence is malformed"),
        ("event_type", None, "event_type is malformed"),
        ("state", "UNKNOWN", "state is not a frozen core state"),
        ("subject_digest", None, "subject_digest is malformed"),
        ("payload", [], "payload must be an object"),
    ),
)
def test_verify_rejects_hash_consistent_events_with_invalid_required_fields(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    ledger = EvidenceLedger(tmp_path, "run-001")
    ledger.append(
        event_type="validated",
        state="VALIDATED",
        subject_digest=canonical_digest({"candidate": 1}),
    )
    event = json.loads(ledger.events_path.read_text())
    event.pop("event_digest")
    event[field] = value
    event["event_digest"] = canonical_digest(event)
    ledger.events_path.write_bytes(canonical_json_bytes(event) + b"\n")

    with pytest.raises(EvidenceIntegrityError, match=message):
        tuple(ledger.verify())


@pytest.mark.parametrize("field", ("event_type", "state", "subject_digest", "payload"))
def test_verify_rejects_hash_consistent_events_missing_required_fields(
    tmp_path: Path, field: str
) -> None:
    ledger = EvidenceLedger(tmp_path, "run-001")
    ledger.append(
        event_type="validated",
        state="VALIDATED",
        subject_digest=canonical_digest({"candidate": 1}),
    )
    event = json.loads(ledger.events_path.read_text())
    event.pop("event_digest")
    event.pop(field)
    event["event_digest"] = canonical_digest(event)
    ledger.events_path.write_bytes(canonical_json_bytes(event) + b"\n")

    with pytest.raises(EvidenceIntegrityError, match="fields do not match schema"):
        tuple(ledger.verify())


def test_verify_translates_event_log_read_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = EvidenceLedger(tmp_path, "run-001")
    ledger.append(
        event_type="validated",
        state="VALIDATED",
        subject_digest=canonical_digest({"candidate": 1}),
    )
    original_read_bytes = Path.read_bytes

    def guarded_read_bytes(path: Path) -> bytes:
        if path == ledger.events_path:
            raise PermissionError("denied")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)

    with pytest.raises(EvidenceIntegrityError, match="ledger cannot be read"):
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


def test_read_blob_verifies_content_address_before_returning_bytes(tmp_path: Path) -> None:
    ledger = EvidenceLedger(tmp_path, "run-001")
    blob = ledger.put_blob(b"sealed candidate file")

    assert ledger.read_blob(blob) == b"sealed candidate file"

    (ledger.blobs_directory / blob.removeprefix("sha256:")).write_bytes(b"changed")
    with pytest.raises(EvidenceIntegrityError, match="does not match"):
        ledger.read_blob(blob)
