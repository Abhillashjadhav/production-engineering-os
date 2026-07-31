"""Durable intake-to-canonical-compilation orchestration for PMOS contracts."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pmpe.contracts.canonical import canonical_digest, canonical_json_bytes
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
        target = self._attempt_dir(attempt_id)
        evidence = {**result.evidence, "intake": dict(intake_binding)}
        _atomic_write(target / "bundle.json", result.bundle_bytes + b"\n")
        _atomic_write(target / "manifest.json", result.manifest_bytes + b"\n")
        _atomic_write(
            target / "compiler-evidence.json",
            canonical_json_bytes(evidence) + b"\n",
        )

    def write_blocked(
        self,
        attempt_id: str,
        blocked: CompilationBlocked,
        intake_binding: dict[str, str],
    ) -> None:
        target = self._attempt_dir(attempt_id)
        evidence = {
            "diagnostics": [diagnostic.as_dict() for diagnostic in blocked.diagnostics],
            "intake": dict(intake_binding),
            "status": "COMPILATION_BLOCKED",
        }
        _atomic_write(
            target / "compiler-diagnostics.json",
            canonical_json_bytes(evidence) + b"\n",
        )

    def load_compilation(self, attempt_id: str) -> CompilationResult | None:
        target = self.root / attempt_id
        paths = (
            target / "bundle.json",
            target / "manifest.json",
            target / "compiler-evidence.json",
        )
        if not all(path.exists() for path in paths):
            return None
        bundle: dict[str, Any] = json.loads(paths[0].read_text())
        manifest: dict[str, Any] = json.loads(paths[1].read_text())
        evidence: dict[str, Any] = json.loads(paths[2].read_text())
        bundle_digest = canonical_digest(bundle)
        manifest_projection = dict(manifest)
        manifest_digest = manifest_projection.pop("manifest_digest", None)
        recomputed_manifest_digest = canonical_digest(manifest_projection)
        if (
            evidence.get("bundle_digest") != bundle_digest
            or manifest.get("bundle", {}).get("content_digest") != bundle_digest
            or evidence.get("manifest_digest") != manifest_digest
            or manifest_digest != recomputed_manifest_digest
        ):
            raise CompilationEvidenceError(
                "stored compiler artifacts fail their canonical digest bindings"
            )
        return CompilationResult.from_artifacts(bundle, manifest, evidence)

    def blocked_exists(self, attempt_id: str) -> bool:
        return (self.root / attempt_id / "compiler-diagnostics.json").exists()


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
        if intake_outcome.replayed:
            try:
                compiled = self.evidence_store.load_compilation(receipt.attempt_id)
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
            status = (
                "COMPILATION_BLOCKED"
                if self.evidence_store.blocked_exists(receipt.attempt_id)
                else (
                    "INTAKE_REJECTED"
                    if intake_outcome.status == "REJECTED"
                    else "INTAKE_SECURITY_BLOCKED"
                )
            )
            return PmosCompilationOutcome(
                status=status,
                intake=intake_outcome,
                compilation=None,
                replayed=True,
            )
        if intake_outcome.status == "REJECTED":
            return PmosCompilationOutcome(
                status="INTAKE_REJECTED",
                intake=intake_outcome,
                compilation=None,
            )
        if intake_outcome.status != "ADMITTED" or intake_outcome.admitted_payload is None:
            return PmosCompilationOutcome(
                status="INTAKE_SECURITY_BLOCKED",
                intake=intake_outcome,
                compilation=None,
            )

        binding = {
            "attempt_id": receipt.attempt_id,
            "fingerprint": receipt.fingerprint,
            "key_version": receipt.key_version,
            "lineage_id": receipt.lineage_id,
            "received_at": receipt.received_at,
        }
        try:
            compilation = self.compiler.compile(
                intake_outcome.admitted_payload,
                content_type=request.content_type,
                received_at=receipt.received_at,
                source_name=receipt.attempt_id,
            )
        except CompilationBlocked as blocked:
            self.evidence_store.write_blocked(
                receipt.attempt_id,
                blocked,
                binding,
            )
            return PmosCompilationOutcome(
                status="COMPILATION_BLOCKED",
                intake=intake_outcome,
                compilation=None,
            )

        self.evidence_store.write_compilation(
            receipt.attempt_id,
            compilation,
            binding,
        )
        return PmosCompilationOutcome(
            status="COMPILED_BLOCKED" if compilation.blocked else "COMPILED",
            intake=intake_outcome,
            compilation=compilation,
        )


__all__ = [
    "CompilationEvidenceError",
    "FileCompilationEvidenceStore",
    "PmosCompilationOutcome",
    "PmosCompilationService",
]
