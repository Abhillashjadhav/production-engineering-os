"""Durable intake-to-canonical-compilation orchestration for PMOS contracts."""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import os
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pmpe.contracts.canonical import (
    CanonicalInputError,
    canonical_digest,
    canonical_json_bytes,
    strict_loads,
)
from pmpe.contracts.compiler import (
    CanonicalCompiler,
    CompilationBlocked,
    CompilationResult,
)
from pmpe.contracts.intake import (
    IntakeCoordinator,
    IntakeOutcome,
    IntakeRequest,
    KeyedFingerprintProvider,
)


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
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


@dataclass(frozen=True)
class PmosCompilationOutcome:
    status: str
    intake: IntakeOutcome
    compilation: CompilationResult | None
    replayed: bool = False


class CompilationEvidenceError(ValueError):
    """Stored compiler evidence does not match its exact canonical artifacts."""


class FileCompilationEvidenceStore:
    """Content-addressed compiler evidence bound to one admitted intake attempt."""

    def __init__(
        self,
        root: Path,
        *,
        fingerprint_provider: KeyedFingerprintProvider,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        self._lock_path = self.root / ".evidence.lock"
        self._lock_path.touch(mode=0o600, exist_ok=True)
        self.fingerprint_provider = fingerprint_provider

    @contextmanager
    def _locked(self) -> Iterator[None]:
        with self._lock_path.open("rb") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _write_once(path: Path, payload: bytes) -> None:
        if path.exists():
            if path.read_bytes() != payload:
                raise CompilationEvidenceError(
                    "attempt already contains different compiler evidence"
                )
            return
        _atomic_write(path, payload)

    def _attempt_dir(self, attempt_id: str) -> Path:
        if not attempt_id or "/" in attempt_id or "\\" in attempt_id or attempt_id in {".", ".."}:
            raise ValueError("attempt ID is unsafe for evidence materialization")
        path = self.root / attempt_id
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path, 0o700)
        return path

    def write_compilation(
        self,
        attempt_id: str,
        result: CompilationResult,
        intake_binding: dict[str, Any],
    ) -> None:
        with self._locked():
            target = self._attempt_dir(attempt_id)
            if (target / "compiler-diagnostics.json").exists():
                raise CompilationEvidenceError("blocked and compiled evidence cannot coexist")
            evidence = {**result.evidence, "intake": dict(intake_binding)}
            artifact_payloads = {
                "bundle.json": result.bundle_bytes + b"\n",
                "manifest.json": result.manifest_bytes + b"\n",
                "compiler-evidence.json": canonical_json_bytes(evidence) + b"\n",
            }
            self._write_once(
                target / "bundle.json",
                artifact_payloads["bundle.json"],
            )
            self._write_once(
                target / "manifest.json",
                artifact_payloads["manifest.json"],
            )
            self._write_once(
                target / "compiler-evidence.json",
                artifact_payloads["compiler-evidence.json"],
            )
            self._write_attestation(
                target,
                "COMPILATION",
                artifact_payloads,
                intake_binding,
            )

    def write_blocked(
        self,
        attempt_id: str,
        blocked: CompilationBlocked,
        intake_binding: dict[str, Any],
    ) -> None:
        with self._locked():
            target = self._attempt_dir(attempt_id)
            if any(
                (target / name).exists()
                for name in ("bundle.json", "manifest.json", "compiler-evidence.json")
            ):
                raise CompilationEvidenceError("blocked and compiled evidence cannot coexist")
            evidence = {
                "diagnostics": [diagnostic.as_dict() for diagnostic in blocked.diagnostics],
                "intake": dict(intake_binding),
                "status": "COMPILATION_BLOCKED",
            }
            artifact_payloads = {
                "compiler-diagnostics.json": canonical_json_bytes(evidence) + b"\n"
            }
            self._write_once(
                target / "compiler-diagnostics.json",
                artifact_payloads["compiler-diagnostics.json"],
            )
            self._write_attestation(
                target,
                "COMPILATION_BLOCKED",
                artifact_payloads,
                intake_binding,
            )

    @staticmethod
    def _attestation_payload(
        kind: str,
        artifact_payloads: dict[str, bytes],
        intake_binding: dict[str, Any],
    ) -> bytes:
        return canonical_json_bytes(
            {
                "artifact_digests": {
                    name: "sha256:" + hashlib.sha256(payload).hexdigest()
                    for name, payload in sorted(artifact_payloads.items())
                },
                "intake": intake_binding,
                "kind": kind,
                "profile": "PMPE-COMPILER-EVIDENCE-1",
            }
        )

    def _write_attestation(
        self,
        target: Path,
        kind: str,
        artifact_payloads: dict[str, bytes],
        intake_binding: dict[str, Any],
    ) -> None:
        payload = self._attestation_payload(
            kind,
            artifact_payloads,
            intake_binding,
        )
        fingerprint = self.fingerprint_provider.fingerprint(
            "compiler-evidence",
            payload,
        )
        key_version = self.fingerprint_provider.key_version
        if not re.fullmatch(r"[0-9a-fA-F]{32,}", fingerprint):
            raise CompilationEvidenceError(
                "fingerprint provider returned an unsafe evidence attestation"
            )
        self._write_once(
            target / "evidence-attestation.json",
            canonical_json_bytes(
                {
                    "domain": "compiler-evidence",
                    "fingerprint": fingerprint,
                    "key_version": key_version,
                    "profile": "PMPE-COMPILER-EVIDENCE-1",
                }
            )
            + b"\n",
        )

    def _verify_attestation(
        self,
        target: Path,
        kind: str,
        artifact_payloads: dict[str, bytes],
        intake_binding: dict[str, Any],
    ) -> None:
        attestation = self._load_canonical_object(target / "evidence-attestation.json")
        if (
            set(attestation) != {"domain", "fingerprint", "key_version", "profile"}
            or attestation.get("domain") != "compiler-evidence"
            or attestation.get("profile") != "PMPE-COMPILER-EVIDENCE-1"
            or not isinstance(attestation.get("key_version"), str)
            or not isinstance(attestation.get("fingerprint"), str)
        ):
            raise CompilationEvidenceError("stored compiler evidence attestation is malformed")
        payload = self._attestation_payload(
            kind,
            artifact_payloads,
            intake_binding,
        )
        candidate = next(
            (
                item
                for item in self.fingerprint_provider.candidate_fingerprints(
                    "compiler-evidence",
                    payload,
                )
                if item.key_version == attestation["key_version"]
            ),
            None,
        )
        if candidate is None or not hmac.compare_digest(
            candidate.value,
            attestation["fingerprint"],
        ):
            raise CompilationEvidenceError("stored compiler evidence fails its keyed attestation")

    @staticmethod
    def _load_canonical_object(path: Path) -> dict[str, Any]:
        try:
            payload = path.read_bytes()
            value = strict_loads(payload, "application/json")
            if payload != canonical_json_bytes(value) + b"\n":
                raise CompilationEvidenceError("stored compiler evidence is not byte-canonical")
            return value
        except CompilationEvidenceError:
            raise
        except (CanonicalInputError, OSError, ValueError) as exc:
            raise CompilationEvidenceError("stored compiler evidence is malformed") from exc

    @staticmethod
    def _validate_intake_binding(
        evidence: dict[str, Any],
        expected_intake_binding: dict[str, Any],
    ) -> None:
        if evidence.get("intake") != expected_intake_binding:
            raise CompilationEvidenceError(
                "stored compiler evidence does not match the exact intake receipt"
            )

    def load_compilation(
        self,
        attempt_id: str,
        expected_intake_binding: dict[str, Any],
    ) -> CompilationResult | None:
        target = self.root / attempt_id
        paths = (
            target / "bundle.json",
            target / "manifest.json",
            target / "compiler-evidence.json",
            target / "evidence-attestation.json",
        )
        present = tuple(path.exists() for path in paths)
        if not any(present[:3]):
            return None
        if present in {
            (True, False, False, False),
            (True, True, False, False),
            (True, True, True, False),
        }:
            return None
        if not all(present) or (target / "compiler-diagnostics.json").exists():
            raise CompilationEvidenceError("stored compiler evidence set is inconsistent")
        try:
            bundle = self._load_canonical_object(paths[0])
            manifest = self._load_canonical_object(paths[1])
            evidence = self._load_canonical_object(paths[2])
            self._validate_intake_binding(evidence, expected_intake_binding)
            self._verify_attestation(
                target,
                "COMPILATION",
                {
                    "bundle.json": paths[0].read_bytes(),
                    "manifest.json": paths[1].read_bytes(),
                    "compiler-evidence.json": paths[2].read_bytes(),
                },
                expected_intake_binding,
            )
            bundle_digest = canonical_digest(bundle)
            manifest_projection = dict(manifest)
            manifest_digest = manifest_projection.pop("manifest_digest", None)
            recomputed_manifest_digest = canonical_digest(manifest_projection)
            bundle_provenance = bundle.get("provenance")
            manifest_provenance = manifest.get("provenance")
            compiler_provenance = (
                bundle_provenance.get("compiler_provenance")
                if isinstance(bundle_provenance, dict)
                else None
            )
            manifest_bundle = manifest.get("bundle")
            if (
                evidence.get("bundle_digest") != bundle_digest
                or not isinstance(manifest_bundle, dict)
                or manifest_bundle.get("content_digest") != bundle_digest
                or manifest_bundle.get("bundle_id") != bundle.get("bundle_id")
                or manifest_bundle.get("bundle_version") != bundle.get("bundle_version")
                or evidence.get("manifest_digest") != manifest_digest
                or manifest_digest != recomputed_manifest_digest
                or not isinstance(bundle_provenance, dict)
                or manifest_provenance != bundle_provenance
                or evidence.get("source_digest") != bundle_provenance.get("source_digest")
                or evidence.get("source_version_value") != bundle_provenance.get("source_version")
                or not isinstance(compiler_provenance, dict)
                or evidence.get("compiler_id") != compiler_provenance.get("compiler_id")
                or evidence.get("compiler_version") != compiler_provenance.get("compiler_version")
                or not isinstance(evidence.get("diagnostics"), list)
            ):
                raise CompilationEvidenceError(
                    "stored compiler artifacts fail their provenance bindings"
                )
            return CompilationResult.from_artifacts(bundle, manifest, evidence)
        except CompilationEvidenceError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise CompilationEvidenceError(
                "stored compiler evidence is structurally invalid"
            ) from exc

    def load_blocked(
        self,
        attempt_id: str,
        expected_intake_binding: dict[str, Any],
    ) -> bool:
        target = self.root / attempt_id
        path = target / "compiler-diagnostics.json"
        attestation_path = target / "evidence-attestation.json"
        if not path.exists() and not attestation_path.exists():
            return False
        if path.exists() and not attestation_path.exists():
            return False
        if not path.exists():
            if any(
                (target / name).exists()
                for name in ("bundle.json", "manifest.json", "compiler-evidence.json")
            ):
                return False
            raise CompilationEvidenceError(
                "compiler evidence attestation has no diagnostic artifact"
            )
        if any(
            (target / name).exists()
            for name in ("bundle.json", "manifest.json", "compiler-evidence.json")
        ):
            raise CompilationEvidenceError("blocked and compiled evidence cannot coexist")
        evidence = self._load_canonical_object(path)
        self._validate_intake_binding(evidence, expected_intake_binding)
        self._verify_attestation(
            target,
            "COMPILATION_BLOCKED",
            {"compiler-diagnostics.json": path.read_bytes()},
            expected_intake_binding,
        )
        diagnostics = evidence.get("diagnostics")
        expected_fields = {
            "blocking",
            "code",
            "message",
            "source_path",
            "target_path",
        }
        if (
            set(evidence) != {"diagnostics", "intake", "status"}
            or evidence.get("status") != "COMPILATION_BLOCKED"
            or not isinstance(diagnostics, list)
            or not diagnostics
            or any(
                not isinstance(item, dict)
                or set(item) != expected_fields
                or item.get("blocking") is not True
                or any(
                    not isinstance(item.get(field), str)
                    for field in ("code", "message", "source_path", "target_path")
                )
                for item in diagnostics
            )
        ):
            raise CompilationEvidenceError("stored compiler diagnostics are structurally invalid")
        return True

    def verify_compilation(
        self,
        attempt_id: str,
        expected: CompilationResult,
        intake_binding: dict[str, Any],
    ) -> CompilationResult:
        stored = self.load_compilation(attempt_id, intake_binding)
        expected_evidence = {**expected.evidence, "intake": intake_binding}
        if (
            stored is None
            or stored.bundle_bytes != expected.bundle_bytes
            or stored.manifest_bytes != expected.manifest_bytes
            or stored.evidence != expected_evidence
        ):
            raise CompilationEvidenceError(
                "stored compiler evidence differs from deterministic recompilation"
            )
        return stored

    def verify_blocked(
        self,
        attempt_id: str,
        expected: CompilationBlocked,
        intake_binding: dict[str, Any],
    ) -> None:
        if not self.load_blocked(attempt_id, intake_binding):
            raise CompilationEvidenceError("stored blocking evidence is incomplete")
        actual = self._load_canonical_object(self.root / attempt_id / "compiler-diagnostics.json")
        expected_evidence = {
            "diagnostics": [diagnostic.as_dict() for diagnostic in expected.diagnostics],
            "intake": intake_binding,
            "status": "COMPILATION_BLOCKED",
        }
        if actual != expected_evidence:
            raise CompilationEvidenceError(
                "stored diagnostics differ from deterministic recompilation"
            )


class PmosCompilationService:
    def __init__(
        self,
        *,
        intake: IntakeCoordinator,
        compiler: CanonicalCompiler,
        evidence_store: FileCompilationEvidenceStore,
    ) -> None:
        self.intake = intake
        self.compiler = compiler
        self.evidence_store = evidence_store

    def process(self, request: IntakeRequest) -> PmosCompilationOutcome:
        intake_outcome = self.intake.receive(request)
        receipt = intake_outcome.receipt
        if receipt is None:
            return PmosCompilationOutcome(
                status="INTAKE_SECURITY_BLOCKED",
                intake=intake_outcome,
                compilation=None,
                replayed=intake_outcome.replayed,
            )
        if intake_outcome.status == "REJECTED":
            return PmosCompilationOutcome(
                status="INTAKE_REJECTED",
                intake=intake_outcome,
                compilation=None,
                replayed=intake_outcome.replayed,
            )
        binding = receipt.as_dict()
        if intake_outcome.status == "ADMITTED":
            try:
                compiled = self.evidence_store.load_compilation(
                    receipt.attempt_id,
                    binding,
                )
                blocked_evidence = self.evidence_store.load_blocked(
                    receipt.attempt_id,
                    binding,
                )
            except CompilationEvidenceError:
                return PmosCompilationOutcome(
                    status="EVIDENCE_SECURITY_BLOCKED",
                    intake=intake_outcome,
                    compilation=None,
                    replayed=True,
                )
            if compiled is not None:
                return PmosCompilationOutcome(
                    status="COMPILED_BLOCKED" if compiled.blocked else "COMPILED",
                    intake=intake_outcome,
                    compilation=compiled,
                    replayed=True,
                )
            status = "COMPILATION_BLOCKED" if blocked_evidence else "EVIDENCE_SECURITY_BLOCKED"
            return PmosCompilationOutcome(
                status=status,
                intake=intake_outcome,
                compilation=None,
                replayed=True,
            )
        if intake_outcome.status != "VALIDATED_PENDING_COMPILATION":
            return PmosCompilationOutcome(
                status="INTAKE_SECURITY_BLOCKED",
                intake=intake_outcome,
                compilation=None,
            )

        try:
            existing = self.evidence_store.load_compilation(
                receipt.attempt_id,
                binding,
            )
            blocked_evidence = self.evidence_store.load_blocked(
                receipt.attempt_id,
                binding,
            )
        except CompilationEvidenceError:
            return PmosCompilationOutcome(
                status="EVIDENCE_SECURITY_BLOCKED",
                intake=intake_outcome,
                compilation=None,
                replayed=True,
            )
        if existing is not None or blocked_evidence:
            try:
                source_payload = self.intake.load_validated_payload(intake_outcome)
                try:
                    expected_compilation = self.compiler.compile(
                        source_payload,
                        content_type=receipt.content_type,
                        received_at=receipt.received_at,
                        source_name=receipt.attempt_id,
                    )
                except CompilationBlocked as expected_blocked:
                    if existing is not None or not blocked_evidence:
                        raise CompilationEvidenceError(
                            "stored compiler evidence type differs from recompilation"
                        ) from expected_blocked
                    self.evidence_store.verify_blocked(
                        receipt.attempt_id,
                        expected_blocked,
                        binding,
                    )
                else:
                    if existing is None or blocked_evidence:
                        raise CompilationEvidenceError(
                            "stored compiler evidence type differs from recompilation"
                        )
                    existing = self.evidence_store.verify_compilation(
                        receipt.attempt_id,
                        expected_compilation,
                        binding,
                    )
            except CompilationEvidenceError:
                return PmosCompilationOutcome(
                    status="EVIDENCE_SECURITY_BLOCKED",
                    intake=intake_outcome,
                    compilation=None,
                    replayed=True,
                )
            except Exception:
                return PmosCompilationOutcome(
                    status="COMPILATION_SECURITY_BLOCKED",
                    intake=intake_outcome,
                    compilation=None,
                    replayed=True,
                )
            finalized = self._finalize_intake(intake_outcome)
            if finalized.status != "ADMITTED":
                return PmosCompilationOutcome(
                    status="INTAKE_SECURITY_BLOCKED",
                    intake=finalized,
                    compilation=existing,
                    replayed=True,
                )
            return PmosCompilationOutcome(
                status=(
                    "COMPILED_BLOCKED"
                    if existing is not None and existing.blocked
                    else ("COMPILED" if existing is not None else "COMPILATION_BLOCKED")
                ),
                intake=finalized,
                compilation=existing,
                replayed=True,
            )

        try:
            source_payload = self.intake.load_validated_payload(intake_outcome)
            compilation = self.compiler.compile(
                source_payload,
                content_type=receipt.content_type,
                received_at=receipt.received_at,
                source_name=receipt.attempt_id,
            )
        except CompilationBlocked as blocked:
            try:
                self.evidence_store.write_blocked(
                    receipt.attempt_id,
                    blocked,
                    binding,
                )
                self.evidence_store.verify_blocked(
                    receipt.attempt_id,
                    blocked,
                    binding,
                )
            except Exception:
                return PmosCompilationOutcome(
                    status="COMPILATION_SECURITY_BLOCKED",
                    intake=intake_outcome,
                    compilation=None,
                )
            finalized = self._finalize_intake(intake_outcome)
            return PmosCompilationOutcome(
                status=(
                    "COMPILATION_BLOCKED"
                    if finalized.status == "ADMITTED"
                    else "INTAKE_SECURITY_BLOCKED"
                ),
                intake=finalized,
                compilation=None,
            )
        except Exception:
            return PmosCompilationOutcome(
                status="COMPILATION_SECURITY_BLOCKED",
                intake=intake_outcome,
                compilation=None,
            )

        try:
            self.evidence_store.write_compilation(
                receipt.attempt_id,
                compilation,
                binding,
            )
            compilation = self.evidence_store.verify_compilation(
                receipt.attempt_id,
                compilation,
                binding,
            )
        except Exception:
            return PmosCompilationOutcome(
                status="COMPILATION_SECURITY_BLOCKED",
                intake=intake_outcome,
                compilation=None,
            )
        finalized = self._finalize_intake(intake_outcome)
        return PmosCompilationOutcome(
            status=(
                "COMPILED_BLOCKED"
                if compilation.blocked and finalized.status == "ADMITTED"
                else ("COMPILED" if finalized.status == "ADMITTED" else "INTAKE_SECURITY_BLOCKED")
            ),
            intake=finalized,
            compilation=compilation,
        )

    def _finalize_intake(self, intake_outcome: IntakeOutcome) -> IntakeOutcome:
        try:
            return self.intake.finalize_admission(intake_outcome)
        except Exception:
            return intake_outcome


__all__ = [
    "CompilationEvidenceError",
    "FileCompilationEvidenceStore",
    "PmosCompilationOutcome",
    "PmosCompilationService",
]
