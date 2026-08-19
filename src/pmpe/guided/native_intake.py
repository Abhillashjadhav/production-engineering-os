"""Native canonical bundle + manifest admission for the guided local surface."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from pmpe.config import packaged_schema_dir
from pmpe.contracts.canonical import (
    CanonicalInputError,
    canonical_digest,
    canonical_json_bytes,
    strict_loads,
)
from pmpe.domain.errors import ContractViolation


@dataclass(frozen=True)
class IntakeDiagnostic:
    code: str
    path: str
    message: str
    blocking: bool = True

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _pointer(parts: Any) -> str:
    values = [str(part).replace("~", "~0").replace("/", "~1") for part in parts]
    return "/" + "/".join(values) if values else "/"


def _schema_diagnostics(
    value: dict[str, Any], schema_name: str, role: str
) -> list[IntakeDiagnostic]:
    schema = json.loads((packaged_schema_dir() / schema_name).read_text())
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda item: (tuple(str(part) for part in item.absolute_path), item.message),
    )
    return [
        IntakeDiagnostic(
            code=f"{role.upper()}_SCHEMA_INVALID",
            path=_pointer(error.absolute_path),
            message=f"{role} violates canonical schema rule {error.validator}",
        )
        for error in errors[:50]
    ]


class LocalCanonicalIntake:
    """Fail-closed, connector-free intake with access-isolated local quarantine.

    Quarantine is intentionally local and file-permission isolated. It is a
    developer quickstart boundary, not a replacement for the encrypted provider
    boundary used by production intake.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.validated = self.root / "validated"
        self.quarantine = self.root / "quarantine"
        for directory in (self.root, self.validated, self.quarantine):
            if directory.is_symlink():
                raise ContractViolation("canonical intake directories must not be symbolic links")
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(directory, 0o700)

    @staticmethod
    def _parse(payload: bytes, role: str) -> tuple[dict[str, Any] | None, list[IntakeDiagnostic]]:
        try:
            return strict_loads(payload, "application/json"), []
        except CanonicalInputError as exc:
            return None, [IntakeDiagnostic(exc.code, "/", f"{role}: {exc}")]

    def admit(self, bundle_payload: bytes, manifest_payload: bytes) -> dict[str, Any]:
        bundle, diagnostics = self._parse(bundle_payload, "bundle")
        manifest, manifest_diagnostics = self._parse(manifest_payload, "manifest")
        diagnostics.extend(manifest_diagnostics)
        if bundle is not None:
            diagnostics.extend(
                _schema_diagnostics(bundle, "pmos_contract_bundle.schema.json", "bundle")
            )
        if manifest is not None:
            diagnostics.extend(
                _schema_diagnostics(manifest, "pmos_contract_manifest.schema.json", "manifest")
            )
        if bundle is not None and manifest is not None and not diagnostics:
            diagnostics.extend(self._binding_diagnostics(bundle, manifest))
        if diagnostics:
            handle = self._quarantine(bundle_payload, manifest_payload, diagnostics)
            return {
                "diagnostics": [item.as_dict() for item in diagnostics],
                "quarantine_handle": handle,
                "status": "QUARANTINED",
            }
        if bundle is None or manifest is None:
            raise RuntimeError("canonical intake reached admission without both artifacts")
        bundle_digest = canonical_digest(bundle)
        target = self.validated / bundle_digest.removeprefix("sha256:")
        target.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._write(target / "bundle.json", canonical_json_bytes(bundle) + b"\n")
        self._write(target / "manifest.json", canonical_json_bytes(manifest) + b"\n")
        return {
            "bundle_digest": bundle_digest,
            "bundle_id": bundle["bundle_id"],
            "diagnostics": [],
            "manifest_digest": manifest["manifest_digest"],
            "status": "VALIDATED_PENDING_GOVERNED_ADMISSION",
        }

    @staticmethod
    def _binding_diagnostics(
        bundle: dict[str, Any], manifest: dict[str, Any]
    ) -> list[IntakeDiagnostic]:
        diagnostics: list[IntakeDiagnostic] = []
        bundle_digest = canonical_digest(bundle)
        manifest_projection = dict(manifest)
        supplied_manifest_digest = manifest_projection.pop("manifest_digest", None)
        expected_manifest_digest = canonical_digest(manifest_projection)
        manifest_bundle = manifest.get("bundle", {})
        checks = (
            (
                manifest_bundle.get("content_digest") == bundle_digest,
                "BUNDLE_DIGEST_MISMATCH",
                "/bundle/content_digest",
                "Manifest content digest does not bind the exact canonical bundle.",
            ),
            (
                manifest_bundle.get("bundle_id") == bundle.get("bundle_id"),
                "BUNDLE_ID_MISMATCH",
                "/bundle/bundle_id",
                "Manifest and bundle identities differ.",
            ),
            (
                manifest_bundle.get("bundle_version") == bundle.get("bundle_version"),
                "BUNDLE_VERSION_MISMATCH",
                "/bundle/bundle_version",
                "Manifest and bundle versions differ.",
            ),
            (
                manifest.get("approval_digest") == canonical_digest(bundle.get("approvals", {})),
                "APPROVAL_DIGEST_MISMATCH",
                "/approval_digest",
                "Manifest approval digest does not bind the bundle approval registry.",
            ),
            (
                supplied_manifest_digest == expected_manifest_digest,
                "MANIFEST_DIGEST_MISMATCH",
                "/manifest_digest",
                "Manifest digest does not bind the exact manifest projection.",
            ),
            (
                manifest.get("provenance") == bundle.get("provenance"),
                "PROVENANCE_MISMATCH",
                "/provenance",
                "Manifest and bundle provenance differ.",
            ),
            (
                not manifest.get("members"),
                "UNRESOLVED_MANIFEST_MEMBERS",
                "/members",
                (
                    "Additional manifest members were declared but not supplied; "
                    "admitting them would be lossy."
                ),
            ),
        )
        for passed, code, path, message in checks:
            if not passed:
                diagnostics.append(IntakeDiagnostic(code, path, message))
        return diagnostics

    def _quarantine(
        self,
        bundle_payload: bytes,
        manifest_payload: bytes,
        diagnostics: list[IntakeDiagnostic],
    ) -> str:
        digest = hashlib.sha256(bundle_payload + b"\0" + manifest_payload).hexdigest()
        handle = f"QUARANTINE-{digest[:20].upper()}"
        target = self.quarantine / handle
        target.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._write(target / "bundle.upload", bundle_payload)
        self._write(target / "manifest.upload", manifest_payload)
        self._write(
            target / "diagnostics.json",
            canonical_json_bytes(
                {
                    "diagnostics": [item.as_dict() for item in diagnostics],
                    "profile": "PMOS-GUIDED-LOCAL-QUARANTINE-1",
                    "quarantine_handle": handle,
                }
            )
            + b"\n",
        )
        return handle

    @staticmethod
    def _write(path: Path, payload: bytes) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags, 0o600)
        except FileExistsError as exc:
            if path.is_symlink() or path.read_bytes() != payload:
                raise ContractViolation(
                    f"refusing to overwrite existing intake artifact: {path}"
                ) from exc
            return
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
