"""Exact-source packaging after trusted PEOS verification, never deployment.

The caller must authenticate the run evidence. The manifest digest is the
external trust anchor for subsequent byte-integrity verification, not a claim
that arbitrary code or fabricated input evidence is trustworthy.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from pmpe.contracts.canonical import canonical_digest, canonical_json_bytes, strict_loads
from pmpe.quality.generated_python import PROFILE, generation_policy

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_IDENTITY = {"candidate_digest", "contract_digest", "plan_digest", "head_event_digest"}


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _path(relative: str) -> PurePosixPath:
    path = PurePosixPath(relative)
    if (
        not relative
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in relative
        or str(path) != relative
    ):
        raise ValueError("unsafe delivery path")
    return path


def assemble_delivery(
    snapshot: Mapping[str, bytes],
    *,
    quality: Mapping[str, Any],
    identity: Mapping[str, str],
    output: Path,
) -> dict[str, str]:
    """Package sources supplied by an authenticated, verified PEOS run."""
    if output.exists() or output.is_symlink():
        raise ValueError("delivery output already exists")
    for relative in snapshot:
        _path(relative)
    source_manifest = {path: _digest(data) for path, data in snapshot.items()}
    candidate_digest = canonical_digest(source_manifest)
    checks = quality.get("checks")
    if (
        not snapshot
        or set(identity) != _IDENTITY
        or any(not isinstance(v, str) or not _DIGEST.fullmatch(v) for v in identity.values())
        or identity["candidate_digest"] != candidate_digest
        or quality.get("candidate_digest") != candidate_digest
        or quality.get("profile") != PROFILE
        or quality.get("passed") is not True
        or not isinstance(checks, (tuple, list))
        or len(checks) != len(generation_policy()["required_checks"])
        or any(not isinstance(c, Mapping) or c.get("status") != "PASS" for c in checks)
        or {c.get("name") for c in checks} != set(generation_policy()["required_checks"])
    ):
        raise ValueError("delivery requires exact quality-checked source identity")
    files = {f"product/{path}": data for path, data in snapshot.items()}
    files["QUALITY.json"] = canonical_json_bytes(dict(quality))
    files["README.md"] = (
        b"# Verified product sources\n\n"
        b"Deployment: NOT_DEPLOYED. This package is not a hosted customer link.\n\n"
        b"The exact generated sources are in product/. Use Python 3.11 or 3.12. "
        b"The supported profile uses the standard library and local modules only.\n"
        b"Use the public functions and inputs defined by the approved PMOS contract; "
        b"this package does not invent a UI, authentication, or a server.\n\n"
        b"QUALITY.json records the checks performed. Keep the separately returned "
        b"manifest digest to verify this package after transfer. Acceptance and security "
        b"evidence remain in the source PEOS run identified by DELIVERY.json.\n"
    )
    manifest = {
        "schema_version": "peos-source-delivery/v1",
        "status": "VERIFIED_SOURCE_PACKAGE",
        "deployment": "NOT_DEPLOYED",
        "identity": dict(identity),
        "files": {path: _digest(data) for path, data in sorted(files.items())},
    }
    manifest_bytes = canonical_json_bytes(manifest)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".pmpe-delivery-", dir=output.parent))
    try:
        for relative, data in files.items():
            target = temporary / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        (temporary / "DELIVERY.json").write_bytes(manifest_bytes)
        # Never replace an existing file, directory, or symlink.
        output.mkdir()
        for item in temporary.iterdir():
            os.rename(item, output / item.name)
    finally:
        shutil.rmtree(temporary)
    return {
        "status": "VERIFIED_SOURCE_PACKAGE",
        "deployment": "NOT_DEPLOYED",
        "manifest_digest": _digest(manifest_bytes),
        "candidate_digest": candidate_digest,
    }


def verify_delivery(root: Path, *, expected_manifest_digest: str) -> dict[str, str]:
    """Verify bytes against a digest retained outside the possibly changed bundle."""
    if root.is_symlink() or not root.is_dir() or not _DIGEST.fullmatch(expected_manifest_digest):
        raise ValueError("delivery root or expected digest is invalid")
    paths: dict[str, Path] = {}
    for directory, directories, names in os.walk(root, followlinks=False):
        for name in [*directories, *names]:
            path = Path(directory) / name
            if path.is_symlink():
                raise ValueError("delivery contains a symlink")
            if path.is_file():
                paths[path.relative_to(root).as_posix()] = path
            elif not path.is_dir():
                raise ValueError("delivery contains an unsupported entry")
    if "DELIVERY.json" not in paths:
        raise ValueError("delivery manifest is missing")
    manifest_bytes = paths.pop("DELIVERY.json").read_bytes()
    if _digest(manifest_bytes) != expected_manifest_digest:
        raise ValueError("delivery manifest digest mismatch")
    manifest = strict_loads(manifest_bytes, "application/json")
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != "peos-source-delivery/v1"
        or manifest.get("status") != "VERIFIED_SOURCE_PACKAGE"
        or manifest.get("deployment") != "NOT_DEPLOYED"
        or not isinstance(manifest.get("files"), dict)
        or set(paths) != set(manifest["files"])
    ):
        raise ValueError("delivery inventory mismatch")
    for relative, expected in manifest["files"].items():
        _path(relative)
        if _digest(paths[relative].read_bytes()) != expected:
            raise ValueError("delivery file digest mismatch")
    identity = manifest.get("identity")
    if not isinstance(identity, dict) or not isinstance(identity.get("candidate_digest"), str):
        raise ValueError("delivery identity missing")
    return {
        "status": "VERIFIED_SOURCE_PACKAGE",
        "deployment": "NOT_DEPLOYED",
        "manifest_digest": expected_manifest_digest,
        "candidate_digest": identity["candidate_digest"],
    }
