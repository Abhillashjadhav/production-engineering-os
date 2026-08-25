"""Plain-file, content-addressed evidence for the bare-bones core."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from pmpe.contracts.canonical import canonical_digest, canonical_json_bytes

_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_DIGEST = re.compile(r"sha256:([0-9a-f]{64})\Z")
GENESIS_DIGEST = "sha256:" + "0" * 64


class EvidenceIntegrityError(ValueError):
    """The evidence ledger is malformed or its hash chain is broken."""


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
        if not event_type or not state or _DIGEST.fullmatch(subject_digest) is None:
            raise ValueError("event type, state, and subject digest are required")
        if any(_DIGEST.fullmatch(item) is None for item in blob_digests):
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
        with self.events_path.open("ab") as stream:
            stream.write(canonical_json_bytes(event) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        return event

    def verify(self) -> Iterator[Mapping[str, Any]]:
        if not self.events_path.exists():
            return
        previous = GENESIS_DIGEST
        for expected_sequence, raw_line in enumerate(
            self.events_path.read_bytes().splitlines(), start=1
        ):
            try:
                event = json.loads(raw_line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise EvidenceIntegrityError("event is not canonical JSON") from exc
            if not isinstance(event, dict):
                raise EvidenceIntegrityError("event must be an object")
            event_digest = event.pop("event_digest", None)
            if (
                event.get("sequence") != expected_sequence
                or event.get("previous_digest") != previous
                or event_digest != canonical_digest(event)
                or raw_line != canonical_json_bytes({**event, "event_digest": event_digest})
            ):
                raise EvidenceIntegrityError(f"broken evidence chain at event {expected_sequence}")
            for digest in event.get("blob_digests", []):
                if not isinstance(digest, str):
                    raise EvidenceIntegrityError("event references a missing blob")
                try:
                    self.read_blob(digest)
                except EvidenceIntegrityError as exc:
                    raise EvidenceIntegrityError("event references an invalid blob") from exc
            restored = {**event, "event_digest": event_digest}
            previous = str(event_digest)
            yield restored
