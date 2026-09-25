"""Load one approved bundle into the engine's exact inputs; add no product policy.

A bundle is a directory with ``bundle.json`` naming every file the run needs:
the outer approval packet, bindings, execution profile, source inventory,
negative-control snapshots and the generation/sandbox disclosures. Everything is
verified before any provider call or workspace creation. The expected freeze
digest is supplied by the operator from outside the bundle; it is an anchor,
not a signature.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from pmpe.barebones import Template, _safe_path
from pmpe.contracts.canonical import canonical_digest, strict_loads
from pmpe.process_gate_inputs import ProcessGateInputs
from pmpe.process_sources import engine_sources, raw_digest

_FIELDS = {
    "schema_version",
    "approval",
    "approval_freeze",
    "bindings",
    "execution_profile",
    "source_paths",
    "negative_controls",
    "generation",
    "real_sandbox_leg",
}
_TARGET = re.compile(r"([A-Za-z_][A-Za-z0-9_.]*):([A-Za-z_][A-Za-z0-9_]*)")


class BundleError(ValueError):
    """The bundle cannot be admitted; nothing has been executed."""


def _materializable(relative: str, what: str) -> None:
    """The candidate runtime writes only names matching its own path grammar."""
    try:
        _safe_path(Path("/"), relative)
    except ValueError as exc:
        raise BundleError(f"bundle {what} path is not materializable: {relative}") from exc


@dataclass(frozen=True)
class ApprovedBundle:
    contract: dict[str, Any]
    receipt: dict[str, Any]
    receipt_bytes: bytes
    template: Template
    inputs: ProcessGateInputs


def _relative(value: object, what: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise BundleError(f"bundle {what} path must be a relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise BundleError(f"bundle {what} path escapes its root: {value}")
    return path


def _file(root: Path, value: object, what: str) -> Path:
    """A regular file under ``root`` reached without any symlink component."""
    current = root
    for part in _relative(value, what).parts:
        current = current / part
        if current.is_symlink():
            raise BundleError(f"bundle {what} path contains a symlink: {value}")
    if not current.is_file():
        raise BundleError(f"bundle {what} file is missing: {value}")
    return current


def _directory(root: Path, value: object, what: str) -> Path:
    """A directory under ``root`` reached without any symlink component."""
    current = root
    for part in _relative(value, what).parts:
        current = current / part
        if current.is_symlink():
            raise BundleError(f"bundle {what} path contains a symlink: {value}")
    if not current.is_dir():
        raise BundleError(f"bundle {what} must be a directory: {value}")
    return current


def _bind_to_source_manifest(
    manifest_bytes: bytes, template: Template, profile: bytes, source_paths: Mapping[str, Path]
) -> None:
    """Tie bundle-supplied bindings, profile and sources to the approved source manifest.

    bundle.json names these outside the approval freeze, so the loader checks them
    itself instead of relying on the contract declaring a digest-boundary gate.
    """
    manifest = _json(manifest_bytes, "source manifest")
    if not isinstance(manifest, dict) or not isinstance(manifest.get("artifacts"), dict):
        raise BundleError("bundle source manifest has no artifact inventory")
    if manifest.get("template_digest") != canonical_digest(asdict(template)):
        raise BundleError("bundle bindings differ from the approved source manifest")
    if manifest.get("execution_profile_sha256") != raw_digest(profile):
        raise BundleError("bundle execution profile differs from the approved source manifest")
    paths = {**engine_sources(), **source_paths}
    artifacts = manifest["artifacts"]
    if set(artifacts) != set(paths) or any(
        artifacts[name] != raw_digest(path.read_bytes()) for name, path in paths.items()
    ):
        raise BundleError("bundle sources differ from the approved source manifest")


def _snapshot(directory: Path) -> dict[str, bytes]:
    if directory.is_symlink() or not directory.is_dir():
        raise BundleError("bundle negative control must be a directory")
    snapshot: dict[str, bytes] = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise BundleError("bundle negative control contains a symlink")
        if path.is_file():
            relative = path.relative_to(directory).as_posix()
            _materializable(relative, "negative control")
            snapshot[relative] = path.read_bytes()
    if not snapshot:
        raise BundleError("bundle negative control snapshot is empty")
    return snapshot


def _json(payload: bytes, what: str) -> Any:
    try:
        return strict_loads(payload, "application/json")
    except ValueError as exc:
        raise BundleError(f"bundle {what} is not strict JSON") from exc


def _template(payload: bytes) -> Template:
    """Admit only explicit files and frozen tests/ targets; never import them here."""
    data = _json(payload, "bindings")
    if not isinstance(data, dict) or set(data) - {
        "version",
        "files",
        "actions",
        "measures",
        "context",
    }:
        raise BundleError("bundle bindings contain unsupported fields")
    for field in ("files", "actions", "context", "measures"):
        if field in data and not isinstance(data[field], dict):
            raise BundleError(f"bundle bindings {field} must be an object")
    try:
        template = Template(**data)
    except TypeError as exc:
        raise BundleError("bundle bindings require version, files, actions and context") from exc
    if not isinstance(template.version, str) or not template.version:
        raise BundleError("bundle bindings require a version")
    for relative, content in template.files.items():
        _relative(relative, "template file")
        _materializable(relative, "template file")
        if not isinstance(content, str):
            raise BundleError("bundle template file contents must be text")
    bindings = [(target, False) for target in template.actions.values()]
    bindings += [(target, True) for target in template.measures.values()]
    for target, evaluator in bindings:
        match = _TARGET.fullmatch(target) if isinstance(target, str) else None
        if match is None:
            raise BundleError("bundle binding target must be module:function")
        relative = match[1].replace(".", "/") + ".py"
        if relative not in template.files:
            raise BundleError("bundle binding target must be an explicit template file")
        # Actions call product code as the engine's default template does; measures
        # judge it, so they must live in frozen tests/ files the coder cannot change.
        if evaluator and not relative.startswith("tests/"):
            raise BundleError("bundle evaluator must be a frozen tests/ file")
        for parent in PurePosixPath(relative).parents:
            if str(parent) != "." and str(parent / "__init__.py") not in template.files:
                raise BundleError("bundle binding needs an explicit package initializer")
    return template


def _string_map(value: object, keys: set[str], what: str) -> dict[str, str]:
    if (
        not isinstance(value, dict)
        or set(value) != keys
        or not all(isinstance(item, str) and item.strip() for item in value.values())
    ):
        raise BundleError(f"bundle {what} must state exactly {sorted(keys)}")
    return dict(value)


def load_approved_bundle(
    directory: Path, *, freeze_digest: str, roots: Mapping[str, Path]
) -> ApprovedBundle:
    """Verify the whole bundle and build the engine inputs; raise BundleError otherwise."""
    directory = Path(directory).resolve()
    manifest = _json(_file(directory, "bundle.json", "manifest").read_bytes(), "manifest")
    if not isinstance(manifest, dict) or set(manifest) != _FIELDS:
        raise BundleError("bundle manifest must contain exactly " + ", ".join(sorted(_FIELDS)))
    if manifest["schema_version"] != "1":
        raise BundleError("bundle schema_version must be 1")
    named_roots = {name: Path(path).resolve() for name, path in roots.items()}
    if "bundle" in named_roots:
        raise BundleError("bundle root name is reserved")
    named_roots["bundle"] = directory

    freeze = _file(directory, manifest["approval_freeze"], "approval freeze").read_bytes()
    if raw_digest(freeze) != freeze_digest:
        raise BundleError("bundle approval freeze differs from the externally supplied digest")
    frozen = _json(freeze, "approval freeze")
    approval = manifest["approval"]
    if (
        not isinstance(frozen, dict)
        or not isinstance(frozen.get("artifacts"), dict)
        or not isinstance(approval, dict)
        or set(approval) != set(frozen["artifacts"])
    ):
        raise BundleError("bundle approval inventory differs from the approval freeze")
    approval_paths: dict[str, Path] = {}
    payloads: dict[str, bytes] = {}
    for key, relative in approval.items():
        path = _file(directory, relative, "approval")
        payloads[key] = path.read_bytes()
        if raw_digest(payloads[key]) != frozen["artifacts"][key]:
            raise BundleError("bundle approval artifact digest mismatch: " + key)
        approval_paths[key] = path
    for key in ("contract", "receipt", "source_manifest"):
        if key not in payloads:
            raise BundleError("bundle approval packet omits " + key)
    contract = _json(payloads["contract"], "contract")
    receipt = _json(payloads["receipt"], "receipt")
    if not isinstance(contract, dict) or not isinstance(receipt, dict):
        raise BundleError("bundle contract and receipt must be JSON objects")

    source_paths: dict[str, Path] = {}
    if not isinstance(manifest["source_paths"], dict) or not manifest["source_paths"]:
        raise BundleError("bundle source_paths must name the manifested sources")
    for name, entry in manifest["source_paths"].items():
        if not isinstance(entry, dict) or set(entry) != {"root", "path"}:
            raise BundleError("bundle source path entries need exactly root and path")
        if entry["root"] not in named_roots:
            raise BundleError("bundle source root is not supplied: " + str(entry["root"]))
        source_paths[name] = _file(named_roots[entry["root"]], entry["path"], "source")

    controls = manifest["negative_controls"]
    if not isinstance(controls, dict):
        raise BundleError("bundle negative_controls must map identifiers to directories")
    negative_controls = {
        identifier: _snapshot(_directory(directory, relative, "negative control"))
        for identifier, relative in controls.items()
    }
    generation = manifest["generation"]
    if not isinstance(generation, dict) or set(generation) != {"mode", "provider_attestation"}:
        raise BundleError("bundle generation must state mode and provider_attestation")
    attestation = _string_map(
        generation["provider_attestation"], {"kind", "statement"}, "provider attestation"
    )
    if not isinstance(generation["mode"], str):
        raise BundleError("bundle generation mode must be a string")

    inputs = ProcessGateInputs(
        approval_freeze=freeze,
        approval_freeze_expected_digest=freeze_digest,
        approval_paths=approval_paths,
        generation_mode=generation["mode"],
        provider_attestation=attestation,
        source_manifest=payloads["source_manifest"],
        source_paths=source_paths,
        execution_profile=_file(
            directory, manifest["execution_profile"], "execution profile"
        ).read_bytes(),
        negative_controls=negative_controls,
        real_sandbox_leg=_string_map(
            manifest["real_sandbox_leg"], {"status", "reason"}, "real sandbox leg"
        ),
    )
    template = _template(_file(directory, manifest["bindings"], "bindings").read_bytes())
    _bind_to_source_manifest(
        payloads["source_manifest"], template, inputs.execution_profile, source_paths
    )
    return ApprovedBundle(
        contract=contract,
        receipt=receipt,
        receipt_bytes=payloads["receipt"],
        template=template,
        inputs=inputs,
    )
