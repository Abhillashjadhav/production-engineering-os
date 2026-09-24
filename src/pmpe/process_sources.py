"""Exact source inventory independent of the contract/receipt that will bind it."""

from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pmpe.contracts.canonical import canonical_digest, strict_loads

if TYPE_CHECKING:
    from pmpe.barebones import Template


def raw_digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def engine_sources() -> dict[str, Path]:
    root = Path(__file__).parent
    return {
        "engine/" + str(path.relative_to(root)): path.resolve()
        for path in sorted(root.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    }


def implementation_identity(implementation: object) -> dict[str, Any]:
    source = inspect.getsourcefile(type(implementation))
    if source is None:
        raise ValueError("process gate implementation has no inspectable source")
    identity: dict[str, Any] = {
        "class": type(implementation).__module__ + "." + type(implementation).__qualname__,
        "source_digest": raw_digest(Path(source).read_bytes()),
    }
    delegate = getattr(implementation, "delegate", None)
    if delegate is not None:
        identity["delegate"] = implementation_identity(delegate)
    return identity


def build_source_manifest(
    template: Template,
    source_paths: Mapping[str, Path],
    profile: bytes,
    *,
    sandbox: object | None = None,
) -> bytes:
    """No contract or receipt: an outer freeze can bind these after actual approval."""
    if "adapter" not in source_paths or any(
        key.startswith(("engine/", "approval/", "protected/")) for key in source_paths
    ):
        raise ValueError(
            "source manifest requires adapter and reserves engine/, approval/ and protected/ names"
        )
    paths = {**engine_sources(), **source_paths}
    value = {
        "schema_version": "1",
        "sandbox_identity": implementation_identity(sandbox) if sandbox is not None else None,
        "artifacts": {name: raw_digest(path.read_bytes()) for name, path in sorted(paths.items())},
        "template_digest": canonical_digest(asdict(template)),
        "execution_profile_sha256": raw_digest(profile),
        "scope": (
            "Immutable engine, adapter, evaluator/template and "
            "profile; approval freeze is separate."
        ),
    }
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def validate_sources(
    manifest_bytes: bytes,
    source_paths: Mapping[str, Path],
    template: Template,
    profile: bytes,
    implementations: tuple[object, ...],
) -> tuple[dict[str, Path], dict[str, str]]:
    manifest = strict_loads(manifest_bytes, "application/json")
    if (
        not isinstance(manifest, dict)
        or set(manifest)
        != {
            "schema_version",
            "sandbox_identity",
            "artifacts",
            "template_digest",
            "execution_profile_sha256",
            "scope",
        }
        or manifest["schema_version"] != "1"
    ):
        raise ValueError("process gate source manifest shape is invalid")
    if "adapter" not in source_paths or any(
        key.startswith(("engine/", "approval/", "protected/")) for key in source_paths
    ):
        raise ValueError(
            "process gate source manifest requires adapter and reserves evidence namespaces"
        )
    paths = {**engine_sources(), **source_paths}
    expected = manifest["artifacts"]
    if not isinstance(expected, dict) or set(expected) != set(paths):
        raise ValueError("process gate source manifest omits or adds inventory entries")
    if manifest["template_digest"] != canonical_digest(asdict(template)) or manifest[
        "execution_profile_sha256"
    ] != raw_digest(profile):
        raise ValueError("process gate template/profile differs from bound manifest")
    if manifest["sandbox_identity"] != implementation_identity(implementations[-1]):
        raise ValueError("process gate sandbox identity is not declared in source manifest")
    expanded = list(implementations)
    for implementation in implementations:
        delegate = getattr(implementation, "delegate", None)
        while delegate is not None:
            expanded.append(delegate)
            delegate = getattr(delegate, "delegate", None)
    for implementation in expanded:
        source = inspect.getsourcefile(type(implementation))
        if source is None or Path(source).resolve() not in {
            path.resolve() for path in paths.values()
        }:
            raise ValueError("process gate manifest omits provider/sandbox implementation")
    if any(expected[name] != raw_digest(path.read_bytes()) for name, path in paths.items()):
        raise ValueError("process gate source manifest digest mismatch")
    return paths, expected
