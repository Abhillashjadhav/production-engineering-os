"""Immutable keyed receipts for artifacts admitted by an owning stage."""

from __future__ import annotations

import ctypes
import errno
import hmac
import json
import os
import re
import secrets
import stat
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from fcntl import LOCK_EX, flock
from pathlib import Path
from typing import Any

from pmpe.contracts.canonical import canonical_digest, canonical_json_bytes
from pmpe.contracts.intake import KeyedFingerprintProvider

_SCHEMA_VERSION = "1.0.0"
_FINGERPRINT_DOMAIN = "pmpe.artifact-admission.v1"
_MAX_RECEIPT_BYTES = 64 * 1024
_KIND = re.compile(r"[A-Z][A-Z0-9_]{1,63}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_RENAME_NOREPLACE = 1


class AdmissionReceiptError(ValueError):
    pass


class AdmissionReceiptConflictError(AdmissionReceiptError):
    pass


AdmissionReceiptConflict = AdmissionReceiptConflictError


def _rename_noreplace(
    source: str,
    target: str,
    *,
    source_directory: int,
    target_directory: int,
) -> None:
    try:
        renameat2 = ctypes.CDLL(None, use_errno=True).renameat2
    except AttributeError as exc:
        raise AdmissionReceiptError("atomic no-replace publication is unavailable") from exc
    renameat2.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    renameat2.restype = ctypes.c_int
    result = renameat2(
        source_directory,
        os.fsencode(source),
        target_directory,
        os.fsencode(target),
        _RENAME_NOREPLACE,
    )
    if result == 0:
        return
    error = ctypes.get_errno()
    if error == errno.EEXIST:
        raise FileExistsError(error, os.strerror(error), target)
    if error in {errno.ENOSYS, errno.EINVAL, errno.ENOTSUP}:
        raise AdmissionReceiptError("atomic no-replace publication is unavailable")
    raise OSError(error, os.strerror(error), target)


def _validate_subject(
    artifact_kind: str,
    artifact_digest: str,
    subject_bindings: Mapping[str, str],
) -> dict[str, str]:
    if not _KIND.fullmatch(artifact_kind):
        raise AdmissionReceiptError("artifact kind is not a bounded canonical identifier")
    if not _DIGEST.fullmatch(artifact_digest):
        raise AdmissionReceiptError("artifact digest is not canonical SHA-256")
    if not subject_bindings or any(
        type(key) is not str
        or not key
        or type(value) is not str
        or not value
        or not _is_utf8(key)
        or not _is_utf8(value)
        for key, value in subject_bindings.items()
    ):
        raise AdmissionReceiptError("subject bindings must be non-empty string pairs")
    return dict(sorted(subject_bindings.items()))


def _is_utf8(value: str) -> bool:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


@dataclass(frozen=True)
class AdmissionReceipt:
    schema_version: str
    artifact_kind: str
    artifact_digest: str
    subject_bindings: Mapping[str, str]
    key_version: str
    fingerprint: str
    receipt_digest: str

    def authority_payload(self) -> dict[str, Any]:
        return {
            "artifact_digest": self.artifact_digest,
            "artifact_kind": self.artifact_kind,
            "key_version": self.key_version,
            "schema_version": self.schema_version,
            "subject_bindings": dict(sorted(self.subject_bindings.items())),
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.authority_payload(),
            "fingerprint": self.fingerprint,
            "receipt_digest": self.receipt_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AdmissionReceipt:
        try:
            bindings = value["subject_bindings"]
            if not isinstance(bindings, Mapping):
                raise TypeError
            return cls(
                schema_version=str(value["schema_version"]),
                artifact_kind=str(value["artifact_kind"]),
                artifact_digest=str(value["artifact_digest"]),
                subject_bindings={str(key): str(item) for key, item in bindings.items()},
                key_version=str(value["key_version"]),
                fingerprint=str(value["fingerprint"]),
                receipt_digest=str(value["receipt_digest"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise AdmissionReceiptError("stored admission receipt is malformed") from exc

    def digest_is_valid(self) -> bool:
        payload = self.as_dict()
        claimed = str(payload.pop("receipt_digest", ""))
        try:
            expected = canonical_digest(payload)
        except (TypeError, ValueError):
            return False
        return bool(_DIGEST.fullmatch(claimed)) and hmac.compare_digest(claimed, expected)


def _load_canonical_receipt(payload: bytes) -> AdmissionReceipt:
    try:
        receipt = AdmissionReceipt.from_dict(json.loads(payload))
        if payload != canonical_json_bytes(receipt.as_dict()) + b"\n":
            raise AdmissionReceiptError("stored admission receipt is not canonical")
        return receipt
    except AdmissionReceiptError:
        raise
    except (TypeError, ValueError) as exc:
        raise AdmissionReceiptError("stored admission receipt is malformed") from exc


def _provider_verifies(receipt: AdmissionReceipt, provider: KeyedFingerprintProvider) -> bool:
    payload = canonical_json_bytes(receipt.authority_payload())
    return any(
        candidate.key_version == receipt.key_version
        and hmac.compare_digest(
            candidate.value.encode("utf-8"), receipt.fingerprint.encode("utf-8")
        )
        for candidate in provider.candidate_fingerprints(_FINGERPRINT_DOMAIN, payload)
    )


class _FileReceiptBoundary:
    def __init__(self, root: Path, provider: KeyedFingerprintProvider) -> None:
        self.root = Path(root)
        self.provider = provider

    def _filename(self, artifact_kind: str, artifact_digest: str) -> str:
        _validate_subject(artifact_kind, artifact_digest, {"subject": "path-validation"})
        return artifact_digest.removeprefix("sha256:") + ".json"

    def _open_kind_directory(self, artifact_kind: str, *, create: bool) -> int:
        absolute = Path(os.path.abspath(self.root))
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor: int | None = None
        try:
            descriptor = os.open(absolute.anchor, flags)
            for component in (*absolute.parts[1:], artifact_kind):
                try:
                    child = os.open(component, flags, dir_fd=descriptor)
                except FileNotFoundError:
                    if not create:
                        raise
                    with suppress(FileExistsError):
                        os.mkdir(component, 0o700, dir_fd=descriptor)
                    child = os.open(component, flags, dir_fd=descriptor)
                if create:
                    os.fsync(descriptor)
                os.close(descriptor)
                descriptor = child
            return descriptor
        except OSError as exc:
            if descriptor is not None:
                os.close(descriptor)
            raise AdmissionReceiptError(
                "admission ledger directory cannot be opened without following symlinks"
            ) from exc

    @staticmethod
    def _read(directory_descriptor: int, filename: str, *, sync: bool = False) -> bytes:
        try:
            descriptor = os.open(
                filename,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
                dir_fd=directory_descriptor,
            )
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise AdmissionReceiptError("admission receipt cannot be opened safely") from exc
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or metadata.st_size > _MAX_RECEIPT_BYTES
            ):
                raise AdmissionReceiptError("admission receipt is not a bounded regular file")
            chunks: list[bytes] = []
            remaining = _MAX_RECEIPT_BYTES + 1
            while remaining:
                chunk = os.read(descriptor, min(remaining, 16 * 1024))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            payload = b"".join(chunks)
            if len(payload) > _MAX_RECEIPT_BYTES:
                raise AdmissionReceiptError("admission receipt exceeds its size limit")
            if sync:
                os.fsync(descriptor)
            return payload
        finally:
            os.close(descriptor)


class FileArtifactAdmissionAuthority(_FileReceiptBoundary):
    def _validated_replay(
        self,
        payload: bytes,
        *,
        artifact_kind: str,
        artifact_digest: str,
        bindings: Mapping[str, str],
    ) -> AdmissionReceipt:
        try:
            stored = _load_canonical_receipt(payload)
        except AdmissionReceiptError as exc:
            raise AdmissionReceiptConflict(
                "artifact identity was claimed by unsafe authority evidence"
            ) from exc
        if (
            stored.schema_version != _SCHEMA_VERSION
            or stored.artifact_kind != artifact_kind
            or stored.artifact_digest != artifact_digest
            or dict(stored.subject_bindings) != dict(bindings)
            or not stored.digest_is_valid()
            or not _provider_verifies(stored, self.provider)
        ):
            raise AdmissionReceiptConflict(
                "artifact already has different authority evidence"
            ) from None
        return stored

    def admit(
        self,
        *,
        artifact_kind: str,
        artifact_digest: str,
        subject_bindings: Mapping[str, str],
    ) -> AdmissionReceipt:
        bindings = _validate_subject(artifact_kind, artifact_digest, subject_bindings)
        unsigned = AdmissionReceipt(
            schema_version=_SCHEMA_VERSION,
            artifact_kind=artifact_kind,
            artifact_digest=artifact_digest,
            subject_bindings=bindings,
            key_version=self.provider.key_version,
            fingerprint="",
            receipt_digest="",
        )
        fingerprint = self.provider.fingerprint(
            _FINGERPRINT_DOMAIN,
            canonical_json_bytes(unsigned.authority_payload()),
        )
        receipt = AdmissionReceipt(
            **{**unsigned.authority_payload(), "fingerprint": fingerprint, "receipt_digest": ""}
        )
        payload = receipt.as_dict()
        payload.pop("receipt_digest")
        receipt = AdmissionReceipt(
            **{
                **receipt.authority_payload(),
                "fingerprint": fingerprint,
                "receipt_digest": canonical_digest(payload),
            }
        )
        encoded = canonical_json_bytes(receipt.as_dict()) + b"\n"
        if len(encoded) > _MAX_RECEIPT_BYTES:
            raise AdmissionReceiptError("admission receipt exceeds its size limit")
        target = self._filename(artifact_kind, artifact_digest)
        directory = self._open_kind_directory(artifact_kind, create=True)
        lock_descriptor: int | None = None
        temporary: str | None = None
        descriptor: int | None = None
        try:
            lock_descriptor = os.open(
                f".{target}.lock",
                os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=directory,
            )
            lock_metadata = os.fstat(lock_descriptor)
            if not stat.S_ISREG(lock_metadata.st_mode) or lock_metadata.st_nlink != 1:
                raise AdmissionReceiptError("admission receipt lock is not a safe regular file")
            flock(lock_descriptor, LOCK_EX)
            try:
                existing = self._read(directory, target, sync=True)
            except FileNotFoundError:
                existing = None
            if existing is not None:
                stored = self._validated_replay(
                    existing,
                    artifact_kind=artifact_kind,
                    artifact_digest=artifact_digest,
                    bindings=bindings,
                )
                os.fsync(directory)
                return stored
            temporary = f".{target}.{secrets.token_hex(16)}.tmp"
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=directory,
            )
            written = 0
            while written < len(encoded):
                count = os.write(descriptor, encoded[written:])
                if count <= 0:
                    raise OSError("receipt write made no progress")
                written += count
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            try:
                _rename_noreplace(
                    temporary,
                    target,
                    source_directory=directory,
                    target_directory=directory,
                )
            except FileExistsError:
                try:
                    raced = self._read(directory, target, sync=True)
                except AdmissionReceiptError as exc:
                    raise AdmissionReceiptConflict(
                        "artifact identity was claimed by unsafe authority evidence"
                    ) from exc
                stored = self._validated_replay(
                    raced,
                    artifact_kind=artifact_kind,
                    artifact_digest=artifact_digest,
                    bindings=bindings,
                )
                os.fsync(directory)
                return stored
            temporary = None
            os.fsync(directory)
        except (AdmissionReceiptError, AdmissionReceiptConflict):
            raise
        except OSError as exc:
            raise AdmissionReceiptError("admission receipt could not be persisted safely") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if temporary is not None:
                try:
                    os.unlink(temporary, dir_fd=directory)
                    os.fsync(directory)
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    raise AdmissionReceiptError(
                        "temporary admission receipt cleanup could not be persisted"
                    ) from exc
            if lock_descriptor is not None:
                os.close(lock_descriptor)
            os.close(directory)
        return receipt


class FileArtifactAdmissionVerifier(_FileReceiptBoundary):
    def verify(
        self,
        receipt: AdmissionReceipt,
        *,
        artifact_kind: str,
        artifact_digest: str,
        subject_bindings: Mapping[str, str],
    ) -> bool:
        try:
            bindings = _validate_subject(artifact_kind, artifact_digest, subject_bindings)
            if (
                type(receipt) is not AdmissionReceipt
                or receipt.schema_version != _SCHEMA_VERSION
                or receipt.artifact_kind != artifact_kind
                or receipt.artifact_digest != artifact_digest
                or dict(receipt.subject_bindings) != bindings
                or not receipt.digest_is_valid()
            ):
                return False
            directory = self._open_kind_directory(artifact_kind, create=False)
            try:
                stored_bytes = self._read(directory, self._filename(artifact_kind, artifact_digest))
            finally:
                os.close(directory)
            canonical_bytes = canonical_json_bytes(receipt.as_dict()) + b"\n"
            if stored_bytes != canonical_bytes:
                return False
            stored = _load_canonical_receipt(stored_bytes)
            if stored != receipt:
                return False
            return _provider_verifies(receipt, self.provider)
        except (AttributeError, OSError, TypeError, ValueError):
            return False
