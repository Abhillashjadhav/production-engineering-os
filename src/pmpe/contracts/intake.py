"""Fail-closed PMOS contract intake with durable, reconcilable local state.

The file-backed implementations in this module are deterministic reference
implementations. Cryptography, keyed fingerprints, malware scanning, clocks,
and opaque ID generation remain provider boundaries so a deployment can bind
them to its approved services without changing the intake state machine.
"""

from __future__ import annotations

import base64
import fcntl
import hashlib
import hmac
import json
import os
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pmpe.contracts.canonical import CanonicalInputError, strict_loads
from pmpe.security_patterns import PROHIBITED_SECRET_PATTERNS as _SECRET_PATTERNS
from pmpe.security_patterns import contains_prohibited_secret as _contains_prohibited_secret

_SAFE_HANDLE = re.compile(r"^[A-Z][A-Z0-9-]{0,127}$")
_SAFE_METADATA = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_SAFE_CONTENT_TYPE = re.compile(
    r"^[a-z0-9][a-z0-9!#$&^_.+-]{0,63}/[a-z0-9][a-z0-9!#$&^_.+-]{0,63}$"
)
_PRIVACY_PATTERNS = (re.compile(rb"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),)


def contains_prohibited_secret(payload: bytes) -> bool:
    """Backward-compatible canonical prohibited-secret predicate."""
    return _contains_prohibited_secret(payload)


class Clock(Protocol):
    def now(self) -> str: ...


class IdProvider(Protocol):
    def new_id(self, kind: str) -> str: ...


@dataclass(frozen=True)
class KeyedFingerprint:
    key_version: str
    value: str


@runtime_checkable
class KeyedFingerprintProvider(Protocol):
    """Provider boundary for a non-exportable, versioned keyed digest."""

    key_version: str

    def fingerprint(self, domain: str, payload: bytes) -> str: ...

    def candidate_fingerprints(
        self,
        domain: str,
        payload: bytes,
    ) -> tuple[KeyedFingerprint, ...]: ...


@dataclass(frozen=True)
class MalwareScanResult:
    clean: bool
    engine: str
    signature_version: str
    finding_code: str | None = None


@runtime_checkable
class MalwareScanner(Protocol):
    def scan(self, payload: bytes) -> MalwareScanResult: ...


@runtime_checkable
class QuarantineCipher(Protocol):
    """Encryption provider boundary; key custody is intentionally external."""

    key_version: str

    def encrypt(self, payload: bytes) -> bytes: ...

    def decrypt(self, payload: bytes) -> bytes: ...


@runtime_checkable
class QuarantineStore(Protocol):
    def put(self, handle: str, payload: bytes, metadata: dict[str, Any]) -> None: ...

    def read(self, handle: str) -> bytes: ...

    def delete(self, handle: str) -> bool: ...

    def exists(self, handle: str) -> bool: ...


@dataclass(frozen=True)
class CorrectionReference:
    lineage_id: str
    attempt_id: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class IntakeRequest:
    retry_key: str
    payload: bytes
    content_type: str
    publisher: str
    channel: str
    correction_reference: CorrectionReference | None = None


@dataclass(frozen=True)
class IntakeReservation:
    lineage_id: str
    attempt_id: str
    quarantine_handle: str
    reserved_at: str
    publisher: str
    channel: str
    retry_fingerprint: str
    retry_key_version: str
    expires_at: str
    content_type: str | None = None
    correction_reference: CorrectionReference | None = None
    correction_state: str = "NONE"
    possible_duplicate: bool = False
    reconciliation_required: bool = False
    reconciliation_reason: str | None = None
    payload_fingerprint: str | None = None
    fingerprint_key_version: str | None = None
    pending_receipt: dict[str, Any] | None = None
    pending_disposition: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["correction_reference"] = (
            self.correction_reference.as_dict() if self.correction_reference else None
        )
        return value


@dataclass(frozen=True)
class IntakeReceipt:
    lineage_id: str
    attempt_id: str
    received_at: str
    publisher: str
    channel: str
    content_type: str
    quarantine_handle: str
    key_version: str
    fingerprint: str
    correction_reference: CorrectionReference | None = None

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["correction_reference"] = (
            self.correction_reference.as_dict() if self.correction_reference else None
        )
        return value


@dataclass(frozen=True)
class IntakeFinding:
    code: str
    message: str
    blocking: bool = True

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DeletionAttestation:
    lineage_id: str
    attempt_id: str
    quarantine_handle: str
    deleted: bool
    deleted_at: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class IntakeDisposition:
    lineage_id: str
    attempt_id: str
    status: str
    recorded_at: str
    findings: tuple[IntakeFinding, ...] = ()
    terminal: bool = True

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["findings"] = [finding.as_dict() for finding in self.findings]
        return value


@dataclass(frozen=True)
class IntakeOutcome:
    status: str
    reservation: IntakeReservation
    receipt: IntakeReceipt | None
    disposition: IntakeDisposition
    deletion_attestation: DeletionAttestation | None
    findings: tuple[IntakeFinding, ...]
    admitted_payload: bytes | None
    quarantine_retained: bool
    replayed: bool = False


@dataclass(frozen=True)
class ReconciliationReport:
    resolved_attempt_ids: tuple[str, ...]
    blocked_attempt_ids: tuple[str, ...]


class IntakeConflictError(RuntimeError):
    """A retry attempts to change an immutable intake identity."""


def _safe_id(value: str, label: str) -> str:
    if not _SAFE_HANDLE.fullmatch(value):
        raise ValueError(f"{label} must be an opaque uppercase identifier")
    return value


def _safe_metadata(value: str, label: str) -> str:
    encoded = value.encode("utf-8", errors="strict")
    if (
        not _SAFE_METADATA.fullmatch(value)
        or any(pattern.search(encoded) for pattern in _SECRET_PATTERNS)
        or any(pattern.search(encoded) for pattern in _PRIVACY_PATTERNS)
    ):
        raise ValueError(f"{label} must be a bounded safe metadata identifier")
    return value


def _safe_content_type(value: str) -> str:
    if not _SAFE_CONTENT_TYPE.fullmatch(value):
        raise ValueError("content type must be bounded canonical media-type metadata")
    return value


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("clock must return an RFC 3339 UTC instant")
    return parsed.astimezone(UTC)


def _after(value: str, seconds: int) -> str:
    return (
        (_parse_utc(value) + timedelta(seconds=seconds))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _expired(expires_at: str, now: str) -> bool:
    return _parse_utc(now) >= _parse_utc(expires_at)


def _decode_correction(value: Any) -> CorrectionReference | None:
    if value is None:
        return None
    return CorrectionReference(
        lineage_id=str(value["lineage_id"]),
        attempt_id=str(value["attempt_id"]),
    )


def _atomic_write(path: Path, data: bytes, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    _atomic_write(
        path,
        (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(),
    )


class FileQuarantineStore:
    """Access-isolated, bounded encrypted quarantine reference implementation."""

    def __init__(self, root: Path, *, cipher: QuarantineCipher, max_bytes: int) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        self.cipher = cipher
        self.max_bytes = max_bytes

    def _path(self, handle: str) -> Path:
        return self.root / f"{_safe_id(handle, 'quarantine handle')}.sealed"

    def put(self, handle: str, payload: bytes, metadata: dict[str, Any]) -> None:
        if len(payload) > self.max_bytes:
            raise ValueError("quarantine payload exceeds configured bound")
        path = self._path(handle)
        if path.exists():
            raise FileExistsError(f"quarantine object already exists for {handle}")
        ordinary_digest = hashlib.sha256(payload).hexdigest()
        envelope = {
            "cipher_key_version": self.cipher.key_version,
            "metadata": {
                **{key: value for key, value in metadata.items() if key != "ordinary_digest"},
                "ordinary_digest": ordinary_digest,
            },
            "payload": base64.b64encode(payload).decode("ascii"),
        }
        cleartext = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
        _atomic_write(path, self.cipher.encrypt(cleartext))

    def read(self, handle: str) -> bytes:
        cleartext = self.cipher.decrypt(self._path(handle).read_bytes())
        envelope = json.loads(cleartext)
        encoded = envelope.get("payload")
        if not isinstance(encoded, str):
            raise ValueError("quarantine envelope is malformed")
        payload = base64.b64decode(encoded, validate=True)
        ordinary_digest = envelope.get("metadata", {}).get("ordinary_digest")
        if not isinstance(ordinary_digest, str) or not hmac.compare_digest(
            ordinary_digest,
            hashlib.sha256(payload).hexdigest(),
        ):
            raise ValueError("quarantine envelope failed its digest binding")
        return payload

    def delete(self, handle: str) -> bool:
        path = self._path(handle)
        if not path.exists():
            return True
        path.unlink()
        directory_descriptor = os.open(self.root, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
        return not path.exists()

    def exists(self, handle: str) -> bool:
        return self._path(handle).exists()


class FileIntakeLedger:
    """Safe-metadata reservation, receipt, disposition, and deletion ledger."""

    def __init__(
        self,
        root: Path,
        *,
        clock: Clock,
        id_provider: IdProvider,
        fingerprint_provider: KeyedFingerprintProvider,
        reservation_ttl_seconds: int = 300,
    ) -> None:
        if reservation_ttl_seconds <= 0:
            raise ValueError("reservation_ttl_seconds must be positive")
        self.root = Path(root)
        self.clock = clock
        self.id_provider = id_provider
        self.fingerprint_provider = fingerprint_provider
        self.reservation_ttl_seconds = reservation_ttl_seconds
        for name in (
            "reservations",
            "receipts",
            "dispositions",
            "deletions",
            "retry-index",
        ):
            directory = self.root / name
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(directory, 0o700)
        self._lock_path = self.root / ".ledger.lock"
        self._lock_path.touch(mode=0o600, exist_ok=True)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        with self._lock_path.open("rb") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _path(self, collection: str, identifier: str) -> Path:
        return self.root / collection / f"{_safe_id(identifier, collection)}.json"

    def _retry_candidates(
        self,
        retry_key: str,
    ) -> tuple[tuple[KeyedFingerprint, str], ...]:
        candidates = self.fingerprint_provider.candidate_fingerprints(
            "retry-key",
            retry_key.encode("utf-8"),
        )
        if not candidates:
            raise ValueError("fingerprint provider returned no governed key versions")
        values: list[tuple[KeyedFingerprint, str]] = []
        seen_versions: set[str] = set()
        for candidate in candidates:
            if candidate.key_version in seen_versions:
                raise ValueError("fingerprint provider returned a duplicate key version")
            if not _SAFE_METADATA.fullmatch(candidate.key_version) or not re.fullmatch(
                r"[0-9a-fA-F]{32,}", candidate.value
            ):
                raise ValueError("fingerprint provider returned unsafe metadata")
            seen_versions.add(candidate.key_version)
            values.append((candidate, f"RETRY-{candidate.value.upper()}"))
        if self.fingerprint_provider.key_version not in seen_versions:
            raise ValueError("current fingerprint key version is not governed")
        return tuple(values)

    @staticmethod
    def _reservation_from_dict(value: dict[str, Any]) -> IntakeReservation:
        return IntakeReservation(
            lineage_id=value["lineage_id"],
            attempt_id=value["attempt_id"],
            quarantine_handle=value["quarantine_handle"],
            reserved_at=value["reserved_at"],
            publisher=value["publisher"],
            channel=value["channel"],
            retry_fingerprint=value["retry_fingerprint"],
            retry_key_version=value["retry_key_version"],
            expires_at=value["expires_at"],
            content_type=value.get("content_type"),
            correction_reference=_decode_correction(value.get("correction_reference")),
            correction_state=value.get("correction_state", "NONE"),
            possible_duplicate=bool(value.get("possible_duplicate", False)),
            reconciliation_required=bool(value.get("reconciliation_required", False)),
            reconciliation_reason=value.get("reconciliation_reason"),
            payload_fingerprint=value.get("payload_fingerprint"),
            fingerprint_key_version=value.get("fingerprint_key_version"),
            pending_receipt=value.get("pending_receipt"),
            pending_disposition=value.get("pending_disposition"),
        )

    @staticmethod
    def _receipt_from_dict(value: dict[str, Any]) -> IntakeReceipt:
        return IntakeReceipt(
            lineage_id=value["lineage_id"],
            attempt_id=value["attempt_id"],
            received_at=value["received_at"],
            publisher=value["publisher"],
            channel=value["channel"],
            content_type=value["content_type"],
            quarantine_handle=value["quarantine_handle"],
            key_version=value["key_version"],
            fingerprint=value["fingerprint"],
            correction_reference=_decode_correction(value.get("correction_reference")),
        )

    @staticmethod
    def _findings(value: dict[str, Any]) -> tuple[IntakeFinding, ...]:
        return tuple(
            IntakeFinding(
                code=item["code"],
                message=item["message"],
                blocking=bool(item.get("blocking", True)),
            )
            for item in value.get("findings", [])
        )

    @classmethod
    def _disposition_from_dict(cls, value: dict[str, Any]) -> IntakeDisposition:
        return IntakeDisposition(
            lineage_id=value["lineage_id"],
            attempt_id=value["attempt_id"],
            status=value["status"],
            recorded_at=value["recorded_at"],
            findings=cls._findings(value),
            terminal=bool(value.get("terminal", True)),
        )

    @staticmethod
    def _deletion_from_dict(value: dict[str, Any]) -> DeletionAttestation:
        return DeletionAttestation(
            lineage_id=value["lineage_id"],
            attempt_id=value["attempt_id"],
            quarantine_handle=value["quarantine_handle"],
            deleted=bool(value["deleted"]),
            deleted_at=value["deleted_at"],
        )

    def reserve(
        self,
        *,
        retry_key: str,
        publisher: str,
        channel: str,
        correction_reference: CorrectionReference | None,
    ) -> IntakeReservation:
        if not retry_key or len(retry_key.encode("utf-8")) > 512:
            raise ValueError("retry key must be non-empty and bounded")
        publisher = _safe_metadata(publisher, "publisher safe metadata")
        channel = _safe_metadata(channel, "channel safe metadata")
        candidates = self._retry_candidates(retry_key)
        current_candidate, retry_fingerprint = next(
            item
            for item in candidates
            if item[0].key_version == self.fingerprint_provider.key_version
        )
        with self._locked():
            indexed_attempt_ids = {
                json.loads(self._path("retry-index", identifier).read_text())["attempt_id"]
                for _candidate, identifier in candidates
                if self._path("retry-index", identifier).exists()
            }
            if len(indexed_attempt_ids) > 1:
                raise RuntimeError("retry fingerprints resolve to multiple reservations")
            if indexed_attempt_ids:
                existing = self.reservation_by_attempt(indexed_attempt_ids.pop())
                if existing is None:
                    raise RuntimeError("retry index references a missing reservation")
                for _candidate, identifier in candidates:
                    path = self._path("retry-index", identifier)
                    if not path.exists():
                        _atomic_json(path, {"attempt_id": existing.attempt_id})
                return existing
            recovered = [
                reservation
                for reservation in self.reservations()
                if any(
                    reservation.retry_key_version == candidate.key_version
                    and hmac.compare_digest(
                        reservation.retry_fingerprint,
                        identifier,
                    )
                    for candidate, identifier in candidates
                )
            ]
            if len(recovered) > 1:
                raise RuntimeError("retry fingerprint resolves to multiple reservations")
            if recovered:
                for _candidate, identifier in candidates:
                    _atomic_json(
                        self._path("retry-index", identifier),
                        {"attempt_id": recovered[0].attempt_id},
                    )
                return recovered[0]

            lineage_id: str
            correction_state = "NONE"
            possible_duplicate = False
            safe_correction_reference = correction_reference
            if safe_correction_reference is not None:
                try:
                    _safe_id(
                        safe_correction_reference.lineage_id,
                        "correction lineage ID",
                    )
                    _safe_id(
                        safe_correction_reference.attempt_id,
                        "correction attempt ID",
                    )
                except ValueError:
                    safe_correction_reference = None
            if correction_reference is None:
                lineage_id = _safe_id(
                    self.id_provider.new_id("lineage"),
                    "lineage ID",
                )
            else:
                predecessor = (
                    self.reservation_by_attempt(safe_correction_reference.attempt_id)
                    if safe_correction_reference is not None
                    else None
                )
                if (
                    predecessor is None
                    or safe_correction_reference is None
                    or predecessor.lineage_id != safe_correction_reference.lineage_id
                ):
                    lineage_id = _safe_id(
                        self.id_provider.new_id("lineage"),
                        "lineage ID",
                    )
                    correction_state = "INVALID"
                    possible_duplicate = True
                else:
                    lineage_id = predecessor.lineage_id
                    predecessor_disposition = self.disposition(predecessor.attempt_id)
                    predecessor_deletion = self.deletion_attestation(predecessor.attempt_id)
                    if (
                        predecessor_disposition is not None
                        and predecessor_disposition.terminal
                        and predecessor_deletion is not None
                        and predecessor_deletion.deleted
                        and not predecessor.reconciliation_required
                    ):
                        correction_state = "VALID"
                    else:
                        correction_state = "BLOCKED"

            reserved_at = self.clock.now()
            reservation = IntakeReservation(
                lineage_id=lineage_id,
                attempt_id=_safe_id(
                    self.id_provider.new_id("attempt"),
                    "attempt ID",
                ),
                quarantine_handle=_safe_id(
                    self.id_provider.new_id("quarantine"),
                    "quarantine handle",
                ),
                reserved_at=reserved_at,
                publisher=publisher,
                channel=channel,
                retry_fingerprint=retry_fingerprint,
                retry_key_version=current_candidate.key_version,
                expires_at=_after(
                    reserved_at,
                    self.reservation_ttl_seconds,
                ),
                correction_reference=safe_correction_reference,
                correction_state=correction_state,
                possible_duplicate=possible_duplicate,
            )
            reservation_path = self._path("reservations", reservation.attempt_id)
            if reservation_path.exists() or self.reservation_by_handle(
                reservation.quarantine_handle
            ):
                raise RuntimeError("opaque ID provider returned a duplicate identifier")
            _atomic_json(
                reservation_path,
                reservation.as_dict(),
            )
            for _candidate, identifier in candidates:
                _atomic_json(
                    self._path("retry-index", identifier),
                    {"attempt_id": reservation.attempt_id},
                )
            return reservation

    def reservation_for_retry_key(self, retry_key: str) -> IntakeReservation | None:
        for _candidate, identifier in self._retry_candidates(retry_key):
            retry_path = self._path("retry-index", identifier)
            if retry_path.exists():
                value = json.loads(retry_path.read_text())
                return self.reservation_by_attempt(value["attempt_id"])
        return None

    def reservation_by_attempt(self, attempt_id: str) -> IntakeReservation | None:
        path = self._path("reservations", attempt_id)
        if not path.exists():
            return None
        return self._reservation_from_dict(json.loads(path.read_text()))

    def reservation_by_handle(self, handle: str) -> IntakeReservation | None:
        for reservation in self.reservations():
            if reservation.quarantine_handle == handle:
                return reservation
        return None

    def reservations(self) -> tuple[IntakeReservation, ...]:
        values = [
            self._reservation_from_dict(json.loads(path.read_text()))
            for path in sorted((self.root / "reservations").glob("*.json"))
        ]
        return tuple(values)

    def _update_reservation(self, reservation: IntakeReservation) -> None:
        _atomic_json(
            self._path("reservations", reservation.attempt_id),
            reservation.as_dict(),
        )

    def bind_payload(
        self,
        attempt_id: str,
        *,
        fingerprint: str,
        key_version: str,
        content_type: str,
    ) -> IntakeReservation:
        if not re.fullmatch(r"[0-9a-fA-F]{32,}", fingerprint) or not _SAFE_METADATA.fullmatch(
            key_version
        ):
            raise ValueError("payload fingerprint metadata is unsafe")
        content_type = _safe_content_type(content_type)
        with self._locked():
            reservation = self.reservation_by_attempt(attempt_id)
            if reservation is None:
                raise KeyError(attempt_id)
            if reservation.payload_fingerprint is not None:
                if (
                    not hmac.compare_digest(
                        reservation.payload_fingerprint,
                        fingerprint,
                    )
                    or reservation.fingerprint_key_version != key_version
                    or reservation.content_type != content_type
                ):
                    raise IntakeConflictError(
                        "retry key is already bound to a different payload or media type"
                    )
                return reservation
            updated = replace(
                reservation,
                payload_fingerprint=fingerprint,
                fingerprint_key_version=key_version,
                content_type=content_type,
            )
            self._update_reservation(updated)
            return updated

    def prepare_receipt(self, receipt: IntakeReceipt) -> None:
        with self._locked():
            reservation = self.reservation_by_attempt(receipt.attempt_id)
            if reservation is None:
                raise KeyError(receipt.attempt_id)
            self._update_reservation(replace(reservation, pending_receipt=receipt.as_dict()))

    def finalize_receipt(self, receipt: IntakeReceipt) -> None:
        with self._locked():
            path = self._path("receipts", receipt.attempt_id)
            if path.exists():
                existing = self._receipt_from_dict(json.loads(path.read_text()))
                if existing != receipt:
                    raise RuntimeError("attempt already has a different intake receipt")
                reservation = self.reservation_by_attempt(receipt.attempt_id)
                if reservation is not None and reservation.pending_receipt is not None:
                    self._update_reservation(replace(reservation, pending_receipt=None))
                return
            reservation = self.reservation_by_attempt(receipt.attempt_id)
            if reservation is None or reservation.pending_receipt != receipt.as_dict():
                raise RuntimeError("receipt was not prepared under its reservation")
            _atomic_json(path, receipt.as_dict())
            self._update_reservation(replace(reservation, pending_receipt=None))

    def receipt(self, attempt_id: str) -> IntakeReceipt | None:
        path = self._path("receipts", attempt_id)
        if not path.exists():
            return None
        return self._receipt_from_dict(json.loads(path.read_text()))

    def prepare_disposition(self, disposition: IntakeDisposition) -> None:
        with self._locked():
            reservation = self.reservation_by_attempt(disposition.attempt_id)
            if reservation is None:
                raise KeyError(disposition.attempt_id)
            self._update_reservation(
                replace(
                    reservation,
                    pending_disposition=disposition.as_dict(),
                )
            )

    def write_disposition(self, disposition: IntakeDisposition) -> None:
        with self._locked():
            path = self._path("dispositions", disposition.attempt_id)
            if path.exists():
                existing = self._disposition_from_dict(json.loads(path.read_text()))
                if existing != disposition:
                    raise RuntimeError("attempt already has a different terminal disposition")
                reservation = self.reservation_by_attempt(disposition.attempt_id)
                if reservation is not None and reservation.pending_disposition is not None:
                    self._update_reservation(replace(reservation, pending_disposition=None))
                return
            reservation = self.reservation_by_attempt(disposition.attempt_id)
            if reservation is None:
                raise KeyError(disposition.attempt_id)
            if (
                reservation.payload_fingerprint is not None
                and self.receipt(disposition.attempt_id) is None
            ):
                raise RuntimeError("terminal disposition requires a durable intake receipt")
            _atomic_json(path, disposition.as_dict())
            self._update_reservation(replace(reservation, pending_disposition=None))

    def disposition(self, attempt_id: str) -> IntakeDisposition | None:
        path = self._path("dispositions", attempt_id)
        if not path.exists():
            return None
        return self._disposition_from_dict(json.loads(path.read_text()))

    def write_deletion_attestation(self, attestation: DeletionAttestation) -> None:
        with self._locked():
            path = self._path("deletions", attestation.attempt_id)
            if path.exists():
                existing = self._deletion_from_dict(json.loads(path.read_text()))
                if existing != attestation:
                    raise RuntimeError("attempt already has a different deletion attestation")
                return
            _atomic_json(path, attestation.as_dict())

    def deletion_attestation(self, attempt_id: str) -> DeletionAttestation | None:
        path = self._path("deletions", attempt_id)
        if not path.exists():
            return None
        return self._deletion_from_dict(json.loads(path.read_text()))

    def mark_reconciliation(self, attempt_id: str, reason: str) -> IntakeReservation:
        with self._locked():
            reservation = self.reservation_by_attempt(attempt_id)
            if reservation is None:
                raise KeyError(attempt_id)
            updated = replace(
                reservation,
                reconciliation_required=True,
                reconciliation_reason=reason,
            )
            self._update_reservation(updated)
            return updated

    def clear_reconciliation(self, attempt_id: str) -> IntakeReservation:
        with self._locked():
            reservation = self.reservation_by_attempt(attempt_id)
            if reservation is None:
                raise KeyError(attempt_id)
            updated = replace(
                reservation,
                reconciliation_required=False,
                reconciliation_reason=None,
                pending_receipt=None,
                pending_disposition=None,
            )
            self._update_reservation(updated)
            return updated


def _finding(code: str, message: str) -> IntakeFinding:
    return IntakeFinding(code=code, message=message)


def _contains_pattern(value: Any, patterns: tuple[re.Pattern[bytes], ...]) -> bool:
    if isinstance(value, str):
        return any(pattern.search(value.encode("utf-8")) for pattern in patterns)
    if isinstance(value, dict):
        return any(
            _contains_pattern(key, patterns) or _contains_pattern(child, patterns)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_contains_pattern(child, patterns) for child in value)
    return False


class IntakeCoordinator:
    def __init__(
        self,
        *,
        ledger: FileIntakeLedger,
        quarantine: QuarantineStore,
        fingerprint_provider: KeyedFingerprintProvider,
        malware_scanner: MalwareScanner,
        clock: Clock,
        max_bytes: int,
        allowed_content_types: set[str],
    ) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self.ledger = ledger
        self.quarantine = quarantine
        self.fingerprint_provider = fingerprint_provider
        self.malware_scanner = malware_scanner
        self.clock = clock
        self.max_bytes = max_bytes
        self.allowed_content_types = frozenset(allowed_content_types)

    def receive(self, request: IntakeRequest) -> IntakeOutcome:
        reservation = self.ledger.reserve(
            retry_key=request.retry_key,
            publisher=request.publisher,
            channel=request.channel,
            correction_reference=request.correction_reference,
        )
        fingerprint_candidates = self.fingerprint_provider.candidate_fingerprints(
            "payload",
            request.payload,
        )
        by_key_version = {
            candidate.key_version: candidate.value for candidate in fingerprint_candidates
        }
        if reservation.payload_fingerprint is None:
            payload_key_version = self.fingerprint_provider.key_version
            payload_fingerprint = by_key_version[payload_key_version]
        else:
            payload_key_version = reservation.fingerprint_key_version or ""
            candidate_value = by_key_version.get(payload_key_version)
            payload_fingerprint = reservation.payload_fingerprint
            if candidate_value is None or not hmac.compare_digest(
                payload_fingerprint,
                candidate_value,
            ):
                finding = _finding(
                    "RETRY_KEY_PAYLOAD_MISMATCH",
                    "retry key is already bound to different contract bytes",
                )
                return IntakeOutcome(
                    status="SECURITY_BLOCKED",
                    reservation=reservation,
                    receipt=self.ledger.receipt(reservation.attempt_id),
                    disposition=self._disposition(
                        reservation,
                        "SECURITY_BLOCKED",
                        (finding,),
                    ),
                    deletion_attestation=self.ledger.deletion_attestation(reservation.attempt_id),
                    findings=(finding,),
                    admitted_payload=None,
                    quarantine_retained=self.quarantine.exists(reservation.quarantine_handle),
                    replayed=True,
                )
        if reservation.reconciliation_required:
            finding = _finding(
                "INTAKE_RECONCILIATION_REQUIRED",
                "intake cannot resume until reconciliation completes",
            )
            return IntakeOutcome(
                status="SECURITY_BLOCKED",
                reservation=reservation,
                receipt=self.ledger.receipt(reservation.attempt_id),
                disposition=self._disposition(
                    reservation,
                    "SECURITY_BLOCKED",
                    (finding,),
                ),
                deletion_attestation=self.ledger.deletion_attestation(reservation.attempt_id),
                findings=(finding,),
                admitted_payload=None,
                quarantine_retained=self.quarantine.exists(reservation.quarantine_handle),
                replayed=True,
            )
        deletion = self.ledger.deletion_attestation(reservation.attempt_id)
        existing_disposition = self.ledger.disposition(reservation.attempt_id)
        if deletion is not None and existing_disposition is None:
            finding = _finding(
                "TERMINAL_DISPOSITION_MISSING",
                "deletion completed without a durable terminal disposition",
            )
            reservation = self.ledger.mark_reconciliation(
                reservation.attempt_id,
                finding.code,
            )
            return IntakeOutcome(
                status="SECURITY_BLOCKED",
                reservation=reservation,
                receipt=self.ledger.receipt(reservation.attempt_id),
                disposition=self._disposition(
                    reservation,
                    "SECURITY_BLOCKED",
                    (finding,),
                ),
                deletion_attestation=self.ledger.deletion_attestation(reservation.attempt_id),
                findings=(finding,),
                admitted_payload=None,
                quarantine_retained=self.quarantine.exists(reservation.quarantine_handle),
                replayed=True,
            )
        try:
            reservation = self.ledger.bind_payload(
                reservation.attempt_id,
                fingerprint=payload_fingerprint,
                key_version=payload_key_version,
                content_type=request.content_type,
            )
        except IntakeConflictError:
            finding = _finding(
                "RETRY_KEY_PAYLOAD_MISMATCH",
                "retry key is already bound to different contract bytes",
            )
            current = self.ledger.reservation_by_attempt(reservation.attempt_id) or reservation
            return IntakeOutcome(
                status="SECURITY_BLOCKED",
                reservation=current,
                receipt=self.ledger.receipt(current.attempt_id),
                disposition=self._disposition(
                    current,
                    "SECURITY_BLOCKED",
                    (finding,),
                ),
                deletion_attestation=self.ledger.deletion_attestation(current.attempt_id),
                findings=(finding,),
                admitted_payload=None,
                quarantine_retained=self.quarantine.exists(current.quarantine_handle),
                replayed=True,
            )
        except Exception:
            return self._block_before_receipt(
                reservation,
                _finding(
                    "PAYLOAD_BINDING_FAILED",
                    "durable retry-key payload binding failed and requires reconciliation",
                ),
            )
        if existing_disposition is not None and existing_disposition.terminal:
            durable_receipt = self.ledger.receipt(reservation.attempt_id)
            durable_deletion = self.ledger.deletion_attestation(reservation.attempt_id)
            if (
                (reservation.payload_fingerprint is not None and durable_receipt is None)
                or durable_deletion is None
                or not durable_deletion.deleted
            ):
                finding = _finding(
                    "TERMINAL_EVIDENCE_INCOMPLETE",
                    "terminal intake evidence requires reconciliation",
                )
                reservation = self.ledger.mark_reconciliation(
                    reservation.attempt_id,
                    finding.code,
                )
                return IntakeOutcome(
                    status="SECURITY_BLOCKED",
                    reservation=reservation,
                    receipt=durable_receipt,
                    disposition=self._disposition(
                        reservation,
                        "SECURITY_BLOCKED",
                        (finding,),
                    ),
                    deletion_attestation=durable_deletion,
                    findings=(finding,),
                    admitted_payload=None,
                    quarantine_retained=self.quarantine.exists(reservation.quarantine_handle),
                    replayed=True,
                )
            return IntakeOutcome(
                status=existing_disposition.status,
                reservation=reservation,
                receipt=durable_receipt,
                disposition=existing_disposition,
                deletion_attestation=durable_deletion,
                findings=existing_disposition.findings,
                admitted_payload=None,
                quarantine_retained=self.quarantine.exists(reservation.quarantine_handle),
                replayed=True,
            )

        possible_duplicate: list[IntakeFinding] = []
        if reservation.possible_duplicate:
            possible_duplicate.append(
                _finding(
                    "POSSIBLE_DUPLICATE",
                    "correction reference is missing or invalid; a new lineage was reserved",
                )
            )
        if reservation.correction_state == "BLOCKED":
            correction_findings = (
                *possible_duplicate,
                _finding(
                    "CORRECTION_PREDECESSOR_UNRESOLVED",
                    "correction predecessor lacks proven deletion and terminal disposition",
                ),
            )
            receipt = self.ledger.receipt(reservation.attempt_id) or self._receipt(
                reservation,
                payload_fingerprint,
                payload_key_version,
            )
            return self._complete_without_payload(
                reservation,
                receipt,
                "SECURITY_BLOCKED",
                correction_findings,
            )

        stored = False
        if len(request.payload) <= self.max_bytes:
            try:
                self.quarantine.put(
                    reservation.quarantine_handle,
                    request.payload,
                    {"ordinary_digest": hashlib.sha256(request.payload).hexdigest()},
                )
                stored = True
            except FileExistsError:
                stored = self.quarantine.exists(reservation.quarantine_handle)
            except Exception:
                return self._block_before_receipt(
                    reservation,
                    _finding(
                        "QUARANTINE_WRITE_FAILED",
                        "quarantine persistence failed and requires reconciliation",
                    ),
                )

        receipt = self.ledger.receipt(reservation.attempt_id) or self._receipt(
            reservation,
            payload_fingerprint,
            payload_key_version,
        )
        try:
            if self.ledger.receipt(reservation.attempt_id) is None:
                self.ledger.prepare_receipt(receipt)
                self.ledger.finalize_receipt(receipt)
        except Exception:
            blocked = _finding(
                "RECEIPT_FINALIZATION_FAILED",
                "durable intake receipt finalization failed and requires reconciliation",
            )
            reservation = self.ledger.mark_reconciliation(
                reservation.attempt_id,
                blocked.code,
            )
            disposition = self._disposition(
                reservation,
                "SECURITY_BLOCKED",
                (blocked,),
            )
            return IntakeOutcome(
                status="SECURITY_BLOCKED",
                reservation=reservation,
                receipt=receipt,
                disposition=disposition,
                deletion_attestation=None,
                findings=(blocked,),
                admitted_payload=None,
                quarantine_retained=stored,
            )

        findings = possible_duplicate
        if len(request.payload) > self.max_bytes:
            findings.append(
                _finding("PAYLOAD_TOO_LARGE", "payload exceeds the configured intake bound")
            )
        elif request.content_type not in self.allowed_content_types:
            findings.append(
                _finding(
                    "CONTENT_TYPE_REJECTED",
                    "content type is not in the admitted contract format set",
                )
            )
        else:
            try:
                scan = self.malware_scanner.scan(request.payload)
            except Exception:
                findings.append(
                    _finding(
                        "MALWARE_SCAN_FAILED",
                        "malware scanning failed closed",
                    )
                )
            else:
                if not scan.clean:
                    findings.append(
                        _finding(
                            "MALWARE_DETECTED",
                            "malware scanner returned a blocking finding",
                        )
                    )
            if not findings:
                if any(pattern.search(request.payload) for pattern in _SECRET_PATTERNS):
                    findings.append(
                        _finding(
                            "SECRET_DETECTED",
                            "input matched a prohibited secret pattern",
                        )
                    )
                elif any(pattern.search(request.payload) for pattern in _PRIVACY_PATTERNS):
                    findings.append(
                        _finding(
                            "PRIVACY_PATTERN_DETECTED",
                            "input matched a privacy-sensitive pattern",
                        )
                    )
            if not findings:
                try:
                    parsed = strict_loads(request.payload, request.content_type)
                except CanonicalInputError:
                    findings.append(
                        _finding(
                            "MALFORMED_INPUT",
                            "input failed strict structural admission",
                        )
                    )
                else:
                    if _contains_pattern(parsed, _SECRET_PATTERNS):
                        findings.append(
                            _finding(
                                "SECRET_DETECTED",
                                "decoded input matched a prohibited secret pattern",
                            )
                        )
                    elif _contains_pattern(parsed, _PRIVACY_PATTERNS):
                        findings.append(
                            _finding(
                                "PRIVACY_PATTERN_DETECTED",
                                "decoded input matched a privacy-sensitive pattern",
                            )
                        )

        if findings:
            return self._finalize(
                reservation,
                receipt,
                "REJECTED",
                tuple(findings),
                admitted_payload=None,
            )
        pending_disposition = self._disposition(
            reservation,
            "VALIDATED_PENDING_COMPILATION",
            (),
            terminal=False,
        )
        return IntakeOutcome(
            status="VALIDATED_PENDING_COMPILATION",
            reservation=reservation,
            receipt=receipt,
            disposition=pending_disposition,
            deletion_attestation=None,
            findings=(),
            admitted_payload=request.payload,
            quarantine_retained=True,
        )

    def load_validated_payload(self, outcome: IntakeOutcome) -> bytes:
        if (
            outcome.status != "VALIDATED_PENDING_COMPILATION"
            or outcome.receipt is None
            or self.ledger.receipt(outcome.reservation.attempt_id) != outcome.receipt
        ):
            raise RuntimeError("intake outcome is not a durable validated handoff")
        payload = self.quarantine.read(outcome.reservation.quarantine_handle)
        candidates = self.fingerprint_provider.candidate_fingerprints(
            "payload",
            payload,
        )
        candidate = next(
            (item for item in candidates if item.key_version == outcome.receipt.key_version),
            None,
        )
        if candidate is None or not hmac.compare_digest(
            candidate.value,
            outcome.receipt.fingerprint,
        ):
            self.ledger.mark_reconciliation(
                outcome.reservation.attempt_id,
                "QUARANTINE_FINGERPRINT_MISMATCH",
            )
            raise RuntimeError("validated quarantine handoff failed fingerprint binding")
        return payload

    def finalize_admission(self, outcome: IntakeOutcome) -> IntakeOutcome:
        if (
            outcome.status != "VALIDATED_PENDING_COMPILATION"
            or outcome.receipt is None
            or self.ledger.receipt(outcome.reservation.attempt_id) != outcome.receipt
        ):
            raise RuntimeError("only a durable validated handoff can be admitted")
        return self._finalize(
            outcome.reservation,
            outcome.receipt,
            "ADMITTED",
            (),
            admitted_payload=None,
        )

    def verify_admitted_outcome(self, outcome: IntakeOutcome) -> bool:
        """Verify that an admitted handoff is durably terminal and quarantine-free."""

        receipt = outcome.receipt
        deletion = outcome.deletion_attestation
        if receipt is None or deletion is None:
            return False
        try:
            stored_reservation = self.ledger.reservation_by_attempt(receipt.attempt_id)
            stored_receipt = self.ledger.receipt(receipt.attempt_id)
            stored_disposition = self.ledger.disposition(receipt.attempt_id)
            stored_deletion = self.ledger.deletion_attestation(receipt.attempt_id)
            quarantine_exists = self.quarantine.exists(receipt.quarantine_handle)
        except Exception:
            return False
        identity_matches = all(
            (
                receipt.lineage_id == outcome.reservation.lineage_id,
                receipt.attempt_id == outcome.reservation.attempt_id,
                receipt.quarantine_handle == outcome.reservation.quarantine_handle,
                deletion.lineage_id == receipt.lineage_id,
                deletion.attempt_id == receipt.attempt_id,
                deletion.quarantine_handle == receipt.quarantine_handle,
                outcome.disposition.lineage_id == receipt.lineage_id,
                outcome.disposition.attempt_id == receipt.attempt_id,
            )
        )
        return bool(
            outcome.status == "ADMITTED"
            and outcome.disposition.status == "ADMITTED"
            and outcome.disposition.terminal
            and outcome.admitted_payload is None
            and not outcome.quarantine_retained
            and deletion.deleted
            and not quarantine_exists
            and not outcome.reservation.reconciliation_required
            and outcome.reservation.pending_receipt is None
            and outcome.reservation.pending_disposition is None
            and identity_matches
            and stored_reservation == outcome.reservation
            and stored_receipt == receipt
            and stored_disposition == outcome.disposition
            and stored_deletion == deletion
        )

    def _receipt(
        self,
        reservation: IntakeReservation,
        payload_fingerprint: str,
        payload_key_version: str,
    ) -> IntakeReceipt:
        if reservation.content_type is None:
            raise RuntimeError("payload media type is not durably bound")
        return IntakeReceipt(
            lineage_id=reservation.lineage_id,
            attempt_id=reservation.attempt_id,
            received_at=self.clock.now(),
            publisher=reservation.publisher,
            channel=reservation.channel,
            content_type=reservation.content_type,
            correction_reference=reservation.correction_reference,
            quarantine_handle=reservation.quarantine_handle,
            key_version=payload_key_version,
            fingerprint=payload_fingerprint,
        )

    def _disposition(
        self,
        reservation: IntakeReservation,
        status: str,
        findings: tuple[IntakeFinding, ...],
        *,
        terminal: bool = True,
    ) -> IntakeDisposition:
        return IntakeDisposition(
            lineage_id=reservation.lineage_id,
            attempt_id=reservation.attempt_id,
            status=status,
            recorded_at=self.clock.now(),
            findings=findings,
            terminal=terminal,
        )

    def _complete_without_payload(
        self,
        reservation: IntakeReservation,
        receipt: IntakeReceipt,
        status: str,
        findings: tuple[IntakeFinding, ...],
    ) -> IntakeOutcome:
        try:
            if self.ledger.receipt(reservation.attempt_id) is None:
                self.ledger.prepare_receipt(receipt)
                self.ledger.finalize_receipt(receipt)
        except Exception:
            blocked = _finding(
                "RECEIPT_FINALIZATION_FAILED",
                "durable intake receipt finalization failed and requires reconciliation",
            )
            findings = (*findings, blocked)
            reservation = self.ledger.mark_reconciliation(
                reservation.attempt_id,
                blocked.code,
            )
            return IntakeOutcome(
                status="SECURITY_BLOCKED",
                reservation=reservation,
                receipt=receipt,
                disposition=self._disposition(
                    reservation,
                    "SECURITY_BLOCKED",
                    findings,
                    terminal=False,
                ),
                deletion_attestation=None,
                findings=findings,
                admitted_payload=None,
                quarantine_retained=self.quarantine.exists(reservation.quarantine_handle),
            )
        return self._finalize(
            reservation,
            receipt,
            status,
            findings,
            admitted_payload=None,
        )

    def _block_before_receipt(
        self,
        reservation: IntakeReservation,
        finding: IntakeFinding,
    ) -> IntakeOutcome:
        reservation = self.ledger.mark_reconciliation(
            reservation.attempt_id,
            finding.code,
        )
        disposition = self._disposition(
            reservation,
            "SECURITY_BLOCKED",
            (finding,),
        )
        return IntakeOutcome(
            status="SECURITY_BLOCKED",
            reservation=reservation,
            receipt=None,
            disposition=disposition,
            deletion_attestation=None,
            findings=(finding,),
            admitted_payload=None,
            quarantine_retained=self.quarantine.exists(reservation.quarantine_handle),
        )

    def _finalize(
        self,
        reservation: IntakeReservation,
        receipt: IntakeReceipt,
        desired_status: str,
        findings: tuple[IntakeFinding, ...],
        *,
        admitted_payload: bytes | None,
    ) -> IntakeOutcome:
        try:
            deleted = self.quarantine.delete(reservation.quarantine_handle)
            if not deleted:
                raise OSError("quarantine store did not attest deletion")
            attestation = DeletionAttestation(
                lineage_id=reservation.lineage_id,
                attempt_id=reservation.attempt_id,
                quarantine_handle=reservation.quarantine_handle,
                deleted=True,
                deleted_at=self.clock.now(),
            )
            self.ledger.write_deletion_attestation(attestation)
        except Exception:
            blocked_finding = _finding(
                "QUARANTINE_DELETION_FAILED",
                "quarantine deletion is unresolved and requires reconciliation",
            )
            blocked_findings = (*findings, blocked_finding)
            disposition = self._disposition(
                reservation,
                "SECURITY_BLOCKED",
                blocked_findings,
            )
            try:
                self.ledger.prepare_disposition(disposition)
            finally:
                reservation = self.ledger.mark_reconciliation(
                    reservation.attempt_id,
                    blocked_finding.code,
                )
            return IntakeOutcome(
                status="SECURITY_BLOCKED",
                reservation=reservation,
                receipt=receipt,
                disposition=disposition,
                deletion_attestation=None,
                findings=blocked_findings,
                admitted_payload=None,
                quarantine_retained=self.quarantine.exists(reservation.quarantine_handle),
            )

        disposition = self._disposition(reservation, desired_status, findings)
        try:
            self.ledger.prepare_disposition(disposition)
            self.ledger.write_disposition(disposition)
        except Exception:
            blocked_finding = _finding(
                "DISPOSITION_WRITE_FAILED",
                "terminal disposition persistence failed and requires reconciliation",
            )
            blocked_findings = (*findings, blocked_finding)
            blocked_disposition = self._disposition(
                reservation,
                "SECURITY_BLOCKED",
                blocked_findings,
            )
            self.ledger.prepare_disposition(blocked_disposition)
            reservation = self.ledger.mark_reconciliation(
                reservation.attempt_id,
                blocked_finding.code,
            )
            return IntakeOutcome(
                status="SECURITY_BLOCKED",
                reservation=reservation,
                receipt=receipt,
                disposition=blocked_disposition,
                deletion_attestation=attestation,
                findings=blocked_findings,
                admitted_payload=None,
                quarantine_retained=False,
            )

        reservation = self.ledger.reservation_by_attempt(reservation.attempt_id) or reservation
        return IntakeOutcome(
            status=desired_status,
            reservation=reservation,
            receipt=receipt,
            disposition=disposition,
            deletion_attestation=attestation,
            findings=findings,
            admitted_payload=admitted_payload,
            quarantine_retained=False,
        )


class IntakeReconciler:
    """Completes interrupted receipt, deletion, and terminal-disposition writes."""

    def __init__(
        self,
        *,
        ledger: FileIntakeLedger,
        quarantine: QuarantineStore,
        clock: Clock,
    ) -> None:
        self.ledger = ledger
        self.quarantine = quarantine
        self.clock = clock

    def reconcile(self) -> ReconciliationReport:
        resolved: list[str] = []
        blocked: list[str] = []
        for reservation in self.ledger.reservations():
            disposition = self.ledger.disposition(reservation.attempt_id)
            receipt = self.ledger.receipt(reservation.attempt_id)
            deletion = self.ledger.deletion_attestation(reservation.attempt_id)
            invariants_complete = bool(
                disposition is not None
                and disposition.terminal
                and deletion is not None
                and deletion.deleted
                and (reservation.payload_fingerprint is None or receipt is not None)
            )
            if invariants_complete:
                if reservation.reconciliation_required:
                    self.ledger.clear_reconciliation(reservation.attempt_id)
                continue
            unsafe_terminal = disposition is not None and disposition.terminal
            if (
                not reservation.reconciliation_required
                and not unsafe_terminal
                and not _expired(reservation.expires_at, self.clock.now())
            ):
                continue
            try:
                if receipt is None and reservation.pending_receipt is not None:
                    self.ledger.finalize_receipt(
                        self.ledger._receipt_from_dict(reservation.pending_receipt)
                    )
                elif (
                    receipt is None
                    and reservation.payload_fingerprint is not None
                    and reservation.fingerprint_key_version is not None
                ):
                    if reservation.content_type is None:
                        raise RuntimeError("payload media type binding is missing")
                    recovered_receipt = IntakeReceipt(
                        lineage_id=reservation.lineage_id,
                        attempt_id=reservation.attempt_id,
                        received_at=reservation.reserved_at,
                        publisher=reservation.publisher,
                        channel=reservation.channel,
                        content_type=reservation.content_type,
                        quarantine_handle=reservation.quarantine_handle,
                        key_version=reservation.fingerprint_key_version,
                        fingerprint=reservation.payload_fingerprint,
                        correction_reference=reservation.correction_reference,
                    )
                    self.ledger.prepare_receipt(recovered_receipt)
                    self.ledger.finalize_receipt(recovered_receipt)
                deleted = self.quarantine.delete(reservation.quarantine_handle)
                if not deleted:
                    raise OSError("quarantine deletion remains unresolved")
                if deletion is None:
                    self.ledger.write_deletion_attestation(
                        DeletionAttestation(
                            lineage_id=reservation.lineage_id,
                            attempt_id=reservation.attempt_id,
                            quarantine_handle=reservation.quarantine_handle,
                            deleted=True,
                            deleted_at=self.clock.now(),
                        )
                    )
                if disposition is None:
                    pending = reservation.pending_disposition
                    if pending is None:
                        finding = _finding(
                            "INTAKE_RECONCILED_SECURITY_BLOCK",
                            "interrupted intake was reconciled without resuming admission",
                        )
                        terminal = IntakeDisposition(
                            lineage_id=reservation.lineage_id,
                            attempt_id=reservation.attempt_id,
                            status="SECURITY_BLOCKED",
                            recorded_at=self.clock.now(),
                            findings=(finding,),
                        )
                    else:
                        terminal = self.ledger._disposition_from_dict(pending)
                        if terminal.status != "SECURITY_BLOCKED":
                            terminal = replace(
                                terminal,
                                status="SECURITY_BLOCKED",
                            )
                    self.ledger.write_disposition(terminal)
                durable_receipt = self.ledger.receipt(reservation.attempt_id)
                durable_deletion = self.ledger.deletion_attestation(reservation.attempt_id)
                durable_disposition = self.ledger.disposition(reservation.attempt_id)
                if (
                    (reservation.payload_fingerprint is not None and durable_receipt is None)
                    or durable_deletion is None
                    or not durable_deletion.deleted
                    or durable_disposition is None
                    or not durable_disposition.terminal
                ):
                    raise RuntimeError("reconciliation invariants remain incomplete")
                self.ledger.clear_reconciliation(reservation.attempt_id)
                resolved.append(reservation.attempt_id)
            except Exception:
                self.ledger.mark_reconciliation(
                    reservation.attempt_id,
                    "RECONCILIATION_FAILED",
                )
                blocked.append(reservation.attempt_id)
        return ReconciliationReport(tuple(resolved), tuple(blocked))


__all__ = [
    "CorrectionReference",
    "DeletionAttestation",
    "FileIntakeLedger",
    "FileQuarantineStore",
    "IntakeCoordinator",
    "IntakeConflictError",
    "IntakeDisposition",
    "IntakeFinding",
    "IntakeOutcome",
    "IntakeReceipt",
    "IntakeReconciler",
    "IntakeRequest",
    "IntakeReservation",
    "KeyedFingerprint",
    "KeyedFingerprintProvider",
    "MalwareScanResult",
    "MalwareScanner",
    "QuarantineCipher",
    "QuarantineStore",
    "ReconciliationReport",
]
