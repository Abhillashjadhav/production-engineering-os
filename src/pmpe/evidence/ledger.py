"""Plain-file, content-addressed evidence for the bare-bones core."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from pmpe.contracts.canonical import (
    canonical_digest,
    canonical_json_bytes,
    strict_loads,
)

_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_DIGEST = re.compile(r"sha256:([0-9a-f]{64})\Z")
GENESIS_DIGEST = "sha256:" + "0" * 64
_EVENT_FIELDS = frozenset(
    {
        "schema_version",
        "run_id",
        "sequence",
        "previous_digest",
        "event_type",
        "state",
        "subject_digest",
        "blob_digests",
        "payload",
        "event_digest",
    }
)
_FROZEN_STATES = frozenset(
    {"VALIDATED", "BUILDING", "VERIFYING", "RELEASE_READY", "HALTED", "STOPPED"}
)


class EvidenceIntegrityError(ValueError):
    """The evidence ledger is malformed or its hash chain is broken."""


def _is_digest(value: object) -> bool:
    return isinstance(value, str) and _DIGEST.fullmatch(value) is not None


def _validate_event_schema(event: Mapping[str, Any]) -> None:
    """Reject records that could not have been emitted by the v1 ledger writer."""

    if set(event) != _EVENT_FIELDS:
        raise EvidenceIntegrityError("event fields do not match schema version 1.0.0")
    if event["schema_version"] != "1.0.0":
        raise EvidenceIntegrityError("event schema_version is unsupported")
    if not isinstance(event["run_id"], str) or _RUN_ID.fullmatch(event["run_id"]) is None:
        raise EvidenceIntegrityError("event run_id is malformed")
    sequence = event["sequence"]
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
        raise EvidenceIntegrityError("event sequence is malformed")
    if not _is_digest(event["previous_digest"]):
        raise EvidenceIntegrityError("event previous_digest is malformed")
    if not isinstance(event["event_type"], str) or not event["event_type"]:
        raise EvidenceIntegrityError("event event_type is malformed")
    if not isinstance(event["state"], str) or event["state"] not in _FROZEN_STATES:
        raise EvidenceIntegrityError("event state is not a frozen core state")
    if not _is_digest(event["subject_digest"]):
        raise EvidenceIntegrityError("event subject_digest is malformed")
    blob_digests = event["blob_digests"]
    if not isinstance(blob_digests, list):
        raise EvidenceIntegrityError("event blob_digests must be a list")
    if any(not _is_digest(digest) for digest in blob_digests):
        raise EvidenceIntegrityError("event blob_digests contain a malformed digest")
    if blob_digests != sorted(set(blob_digests)):
        raise EvidenceIntegrityError("event blob_digests must be sorted and unique")
    if not isinstance(event["payload"], dict):
        raise EvidenceIntegrityError("event payload must be an object")
    if not _is_digest(event["event_digest"]):
        raise EvidenceIntegrityError("event event_digest is malformed")


class EvidenceLedger:
    """Append-only JSONL events and SHA-256 blobs under one `.pmpe` directory."""

    def __init__(self, repository_root: Path, run_id: str, *, resume: bool = False) -> None:
        if not _RUN_ID.fullmatch(run_id):
            raise ValueError("run_id must be a bounded filesystem-safe identifier")
        self.run_id = run_id
        self.root = repository_root / ".pmpe"
        self.run_directory = self.root / "runs" / run_id
        self.events_path = self.run_directory / "events.jsonl"
        self.blobs_directory = self.root / "blobs"
        self._read_only = False
        self.run_directory.mkdir(parents=True, exist_ok=True)
        self.blobs_directory.mkdir(parents=True, exist_ok=True)
        if resume:
            if not self.events_path.is_file():
                raise EvidenceIntegrityError("cannot resume a run without an evidence ledger")
            events = tuple(self.verify())
            if not events:
                raise EvidenceIntegrityError("cannot resume an empty evidence ledger")
            if events[-1].get("state") in {"RELEASE_READY", "HALTED", "STOPPED"}:
                raise EvidenceIntegrityError("a terminal run cannot be resumed")
        else:
            try:
                descriptor = os.open(
                    self.events_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
            except FileExistsError as exc:
                raise EvidenceIntegrityError(
                    "run_id already has an evidence ledger; use a new run_id"
                ) from exc
            os.close(descriptor)

    @classmethod
    def open_existing(cls, repository_root: Path, run_id: str) -> EvidenceLedger:
        """Open and verify an existing ledger without attempting to resume its run."""

        if not _RUN_ID.fullmatch(run_id):
            raise ValueError("run_id must be a bounded filesystem-safe identifier")
        ledger = cls.__new__(cls)
        ledger.run_id = run_id
        ledger.root = repository_root / ".pmpe"
        ledger.run_directory = ledger.root / "runs" / run_id
        ledger.events_path = ledger.run_directory / "events.jsonl"
        ledger.blobs_directory = ledger.root / "blobs"
        ledger._read_only = True
        if not ledger.events_path.is_file():
            raise EvidenceIntegrityError("evidence ledger does not exist")
        tuple(ledger.verify())
        return ledger

    def put_blob(self, payload: bytes) -> str:
        if self._read_only:
            raise EvidenceIntegrityError("an inspection ledger is read-only")
        digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        destination = self.blobs_directory / digest.removeprefix("sha256:")
        if destination.exists():
            if destination.read_bytes() != payload:
                raise EvidenceIntegrityError("content-addressed blob does not match its name")
            return digest
        descriptor, temporary_name = tempfile.mkstemp(dir=self.blobs_directory)
        try:
            with os.fdopen(descriptor, "wb") as temporary:
                temporary.write(payload)
                temporary.flush()
                os.fsync(temporary.fileno())
            try:
                os.link(temporary_name, destination)
            except FileExistsError:
                if destination.read_bytes() != payload:
                    raise EvidenceIntegrityError("concurrent blob write changed content") from None
        finally:
            Path(temporary_name).unlink(missing_ok=True)
        return digest

    def read_blob(self, digest: str) -> bytes:
        """Return one verified content-addressed blob without mutating the ledger."""

        match = _DIGEST.fullmatch(digest)
        if match is None:
            raise EvidenceIntegrityError("blob digest is malformed")
        blob_path = self.blobs_directory / match.group(1)
        try:
            if not blob_path.is_file():
                raise EvidenceIntegrityError("evidence blob does not exist")
            payload = blob_path.read_bytes()
        except OSError as exc:
            raise EvidenceIntegrityError("evidence blob cannot be read") from exc
        if "sha256:" + hashlib.sha256(payload).hexdigest() != digest:
            raise EvidenceIntegrityError("blob content does not match its digest")
        return payload

    def append(
        self,
        *,
        event_type: str,
        state: str,
        subject_digest: str,
        blob_digests: Sequence[str] = (),
        payload: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        if self._read_only:
            raise EvidenceIntegrityError("an inspection ledger is read-only")
        if (
            not isinstance(event_type, str)
            or not event_type
            or not isinstance(state, str)
            or state not in _FROZEN_STATES
            or not _is_digest(subject_digest)
        ):
            raise ValueError("event type, state, and subject digest are required")
        if any(not _is_digest(item) for item in blob_digests):
            raise ValueError("blob references must be SHA-256 digests")
        events = tuple(self.verify())
        body: dict[str, Any] = {
            "schema_version": "1.0.0",
            "run_id": self.run_id,
            "sequence": len(events) + 1,
            "previous_digest": events[-1]["event_digest"] if events else GENESIS_DIGEST,
            "event_type": event_type,
            "state": state,
            "subject_digest": subject_digest,
            "blob_digests": sorted(set(blob_digests)),
            "payload": dict(payload or {}),
        }
        event = {**body, "event_digest": canonical_digest(body)}
        _validate_event_schema(event)
        with self.events_path.open("ab") as stream:
            stream.write(canonical_json_bytes(event) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        return event

    def verify(self) -> Iterator[Mapping[str, Any]]:
        if not self.events_path.exists():
            return
        try:
            raw_events = self.events_path.read_bytes().splitlines()
        except OSError as exc:
            raise EvidenceIntegrityError("evidence ledger cannot be read") from exc
        previous = GENESIS_DIGEST
        for expected_sequence, raw_line in enumerate(raw_events, start=1):
            try:
                event = strict_loads(raw_line, "application/json")
            except ValueError as exc:
                raise EvidenceIntegrityError("event is not canonical JSON") from exc
            _validate_event_schema(event)
            event_digest = event["event_digest"]
            body = {key: value for key, value in event.items() if key != "event_digest"}
            if (
                event.get("sequence") != expected_sequence
                or event.get("previous_digest") != previous
                or event_digest != canonical_digest(body)
                or raw_line != canonical_json_bytes(event)
            ):
                raise EvidenceIntegrityError(f"broken evidence chain at event {expected_sequence}")
            if event.get("run_id") != self.run_id:
                raise EvidenceIntegrityError(f"event run_id mismatch at event {expected_sequence}")
            blob_digests = event.get("blob_digests")
            if not isinstance(blob_digests, list):
                raise EvidenceIntegrityError("event blob_digests must be a list")
            for digest in blob_digests:
                if not isinstance(digest, str):
                    raise EvidenceIntegrityError("event references a missing blob")
                try:
                    self.read_blob(digest)
                except EvidenceIntegrityError as exc:
                    raise EvidenceIntegrityError("event references an invalid blob") from exc
            previous = str(event_digest)
            yield event
