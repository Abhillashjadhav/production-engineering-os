"""Durable intake-to-canonical-compilation orchestration for PMOS contracts."""

from __future__ import annotations

import fcntl
import os
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
from pmpe.contracts.intake import IntakeCoordinator, IntakeOutcome, IntakeRequest


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

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        self._lock_path = self.root / ".evidence.lock"
        self._lock_path.touch(mode=0o600, exist_ok=True)

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
        intake_binding: dict[str, str],
    ) -> None:
        with self._locked():
            target = self._attempt_dir(attempt_id)
            evidence = {**result.evidence, "intake": dict(intake_binding)}
            self._write_once(
                target / "bundle.json",
                result.bundle_bytes + b"\n",
            )
            self._write_once(
                target / "manifest.json",
                result.manifest_bytes + b"\n",
            )
            self._write_once(
                target / "compiler-evidence.json",
                canonical_json_bytes(evidence) + b"\n",
            )

    def write_blocked(
        self,
        attempt_id: str,
        blocked: CompilationBlocked,
        intake_binding: dict[str, str],
    ) -> None:
        with self._locked():
            target = self._attempt_dir(attempt_id)
            evidence = {
                "diagnostics": [diagnostic.as_dict() for diagnostic in blocked.diagnostics],
                "intake": dict(intake_binding),
                "status": "COMPILATION_BLOCKED",
            }
            self._write_once(
                target / "compiler-diagnostics.json",
                canonical_json_bytes(evidence) + b"\n",
            )

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
        expected_intake_binding: dict[str, str],
    ) -> None:
        if evidence.get("intake") != expected_intake_binding:
            raise CompilationEvidenceError(
                "stored compiler evidence does not match the exact intake receipt"
            )

    def load_compilation(
        self,
        attempt_id: str,
        expected_intake_binding: dict[str, str],
    ) -> CompilationResult | None:
        target = self.root / attempt_id
        paths = (
            target / "bundle.json",
            target / "manifest.json",
            target / "compiler-evidence.json",
        )
        present = tuple(path.exists() for path in paths)
        if not any(present):
            return None
        if present in {(True, False, False), (True, True, False)}:
            return None
        if not all(present) or (target / "compiler-diagnostics.json").exists():
            raise CompilationEvidenceError("stored compiler evidence set is inconsistent")
        try:
            bundle = self._load_canonical_object(paths[0])
            manifest = self._load_canonical_object(paths[1])
            evidence = self._load_canonical_object(paths[2])
            self._validate_intake_binding(evidence, expected_intake_binding)
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
        expected_intake_binding: dict[str, str],
    ) -> bool:
        target = self.root / attempt_id
        path = target / "compiler-diagnostics.json"
        if not path.exists():
            return False
        if any(
            (target / name).exists()
            for name in ("bundle.json", "manifest.json", "compiler-evidence.json")
        ):
            raise CompilationEvidenceError("blocked and compiled evidence cannot coexist")
        evidence = self._load_canonical_object(path)
        self._validate_intake_binding(evidence, expected_intake_binding)
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
        binding = {
            "attempt_id": receipt.attempt_id,
            "fingerprint": receipt.fingerprint,
            "key_version": receipt.key_version,
            "lineage_id": receipt.lineage_id,
            "received_at": receipt.received_at,
        }
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
                content_type=request.content_type,
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
            except (OSError, CompilationEvidenceError):
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
        except (OSError, CompilationEvidenceError):
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
