#!/usr/bin/env python3
"""Evaluate the composed security profile against an exact checked-out candidate."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import subprocess  # nosec B404 - fixed git argv authenticates the local checkout
from collections.abc import Callable, Sequence
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from importlib.metadata import PackageNotFoundError, distribution, version
from pathlib import Path
from typing import Any

from pmpe.contracts.digest import canonical_digest
from pmpe.quality.security_profiles import (
    AdvisorySnapshot,
    ArchitectureBoundaryObservation,
    NormalizedSecurityFinding,
    PrivacyEvidence,
    PrivacyIntent,
    ProfileEvidenceAttestation,
    SastAllowlistEntry,
    SecretAllowlistEntry,
    SecurityGatePolicy,
    SecurityProfileInput,
    ToolIdentity,
    advisory_authentication_payload,
    evaluate_security_profile,
    profile_authentication_payload,
)

_LAYERS = {
    "interfaces": frozenset({"cli", "demo", "fullstack", "guided", "personal"}),
    "orchestration": frozenset({"agents", "engineering", "evals", "orchestration"}),
    "verification": frozenset(
        {
            "admission",
            "assurance",
            "audit",
            "evidence",
            "quality",
            "review",
            "testing",
            "validation",
        }
    ),
    "core": frozenset({"config", "contracts", "domain", "repository", "telemetry", "workflows"}),
    "delivery": frozenset(
        {
            "architecture",
            "artifacts",
            "deployment",
            "execution",
            "gitops",
            "implementation",
            "ingestion",
            "planning",
            "policies",
            "stacks",
        }
    ),
}


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _file_digest(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _proof(kind: str, identity: str, authority: str, payload: object) -> str:
    return canonical_digest(
        {
            "authority": authority,
            "identity": identity,
            "kind": kind,
            "payload": payload,
            "trust_root": "repository-security-profile-runner/v1",
        }
    )


def _authenticator(kind: str):  # type: ignore[no-untyped-def]
    def verify(identity: str, authority: str, payload: object, evidence: str) -> bool:
        return evidence == _proof(kind, identity, authority, payload)

    return verify


def _git_output(root: Path, *arguments: str) -> str:
    completed = subprocess.run(  # nosec B603 - fixed git argv, shell is never used
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _repository_is_exact(root: Path, candidate_sha: str) -> bool:
    try:
        top_level = Path(_git_output(root, "rev-parse", "--show-toplevel")).resolve()
        head = _git_output(root, "rev-parse", "HEAD")
        dirty_tracked = _git_output(root, "status", "--porcelain=v1", "--untracked-files=no")
    except (OSError, subprocess.CalledProcessError):
        return False
    return top_level == root.resolve() and head == candidate_sha and not dirty_tracked


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text())


_REVIEW_METADATA = frozenset({"approved_by", "expires_at", "justification"})


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _reviewed_record(
    value: object,
    *,
    label: str,
    fields: frozenset[str],
    now: datetime,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields | _REVIEW_METADATA:
        raise ValueError(f"{label} must contain exact reviewed fields")
    approved_by = value.get("approved_by")
    justification = value.get("justification")
    expires_at = value.get("expires_at")
    if not isinstance(approved_by, str) or not approved_by.strip():
        raise ValueError(f"{label} requires an approving owner")
    if not isinstance(justification, str) or not justification.strip():
        raise ValueError(f"{label} requires a justification")
    if not isinstance(expires_at, str):
        raise ValueError(f"{label} requires an expiration")
    try:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} expiration is malformed") from exc
    if expiry.tzinfo is None or expiry <= now:
        raise ValueError(f"{label} review has expired")
    return dict(value)


def _reviewed_records(
    value: object,
    *,
    label: str,
    fields: frozenset[str],
    now: datetime,
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must be a non-empty reviewed list")
    return [_reviewed_record(item, label=label, fields=fields, now=now) for item in value]


def _require_unique(values: Sequence[object], label: str) -> None:
    identities = [canonical_digest(item) for item in values]
    if len(identities) != len(set(identities)):
        raise ValueError(f"{label} contains duplicate grants")


def _reviewed_policy_config(
    value: object,
    *,
    trusted_clock: Callable[[], datetime] = _utc_now,
) -> dict[str, Any]:
    expected_top_level = {
        "allowed_architecture_edges",
        "allowed_licenses",
        "dynamic_import_allowlist",
        "license_fallbacks",
        "privacy",
        "sast_allowlist",
        "version",
    }
    if (
        not isinstance(value, dict)
        or set(value) != expected_top_level
        or value.get("version") != "repository-security-profile/v2"
    ):
        raise ValueError("repository security profile policy is malformed")
    now = trusted_clock()
    if now.tzinfo is None:
        raise ValueError("security policy clock must be timezone-aware")

    edge_records = _reviewed_records(
        value["allowed_architecture_edges"],
        label="architecture edge",
        fields=frozenset({"source", "target"}),
        now=now,
    )
    edges = [[str(item["source"]), str(item["target"])] for item in edge_records]
    _require_unique(edges, "architecture edge allowlist")

    license_records = _reviewed_records(
        value["allowed_licenses"],
        label="license grant",
        fields=frozenset({"license"}),
        now=now,
    )
    licenses = [str(item["license"]) for item in license_records]
    _require_unique(licenses, "license allowlist")

    fallback_records = _reviewed_records(
        value["license_fallbacks"],
        label="license fallback",
        fields=frozenset({"distribution", "license"}),
        now=now,
    )
    fallback_pairs = [
        [str(item["distribution"]), str(item["license"])] for item in fallback_records
    ]
    _require_unique(fallback_pairs, "license fallback list")
    fallbacks = dict(fallback_pairs)
    if len(fallbacks) != len(fallback_pairs):
        raise ValueError("license fallback list contains duplicate distributions")

    privacy = _reviewed_record(
        value["privacy"],
        label="privacy intent",
        fields=frozenset(
            {
                "classification",
                "deletion_required",
                "residency",
                "retention_days",
                "telemetry_allowlist",
            }
        ),
        now=now,
    )
    telemetry_records = _reviewed_records(
        privacy["telemetry_allowlist"],
        label="telemetry field",
        fields=frozenset({"field"}),
        now=now,
    )
    telemetry_fields = [str(item["field"]) for item in telemetry_records]
    _require_unique(telemetry_fields, "telemetry allowlist")

    dynamic_records = _reviewed_records(
        value["dynamic_import_allowlist"],
        label="dynamic import exemption",
        fields=frozenset({"file_digest", "line", "line_fingerprint", "path"}),
        now=now,
    )
    dynamic_identities = [[str(item["path"]), int(item["line"])] for item in dynamic_records]
    _require_unique(dynamic_identities, "dynamic import allowlist")

    normalized_privacy = {
        key: privacy[key]
        for key in (
            "classification",
            "deletion_required",
            "residency",
            "retention_days",
        )
    }
    normalized_privacy["telemetry_allowlist"] = telemetry_fields
    return {
        "allowed_architecture_edges": edges,
        "allowed_licenses": licenses,
        "dynamic_import_allowlist": dynamic_records,
        "license_fallbacks": fallbacks,
        "privacy": normalized_privacy,
        "sast_allowlist": value["sast_allowlist"],
        "version": value["version"],
    }


def _layer(package: str) -> str:
    for layer, packages in _LAYERS.items():
        if package in packages:
            return layer
    return "core"


def _observed_architecture_edges(
    root: Path,
    *,
    dynamic_import_allowlist: tuple[tuple[str, int, str, str], ...] = (),
) -> tuple[tuple[str, str], ...]:
    edges: set[tuple[str, str]] = set()
    product_root = root / "products" / "pm-evals-web" / "backend" / "src"
    product_packages = (
        frozenset(
            {
                path.name
                for path in product_root.iterdir()
                if path.is_dir() and any(source.is_file() for source in path.rglob("*.py"))
            }
            | {path.stem for path in product_root.glob("*.py")}
        )
        if product_root.is_dir()
        else frozenset()
    )
    source_roots = (
        (root / "src" / "pmpe", "os"),
        (product_root, "product"),
    )
    for source_root, plane in source_roots:
        if not source_root.is_dir():
            continue
        for path in sorted(source_root.rglob("*.py")):
            relative_parts = path.relative_to(source_root).parts
            if plane == "os":
                source_package = relative_parts[0] if len(relative_parts) > 1 else "root"
                source_layer = _layer(source_package)
                current_package = ".".join(("pmpe", *relative_parts[:-1]))
            else:
                source_layer = "product"
                current_package = ".".join(relative_parts[:-1])
            _collect_architecture_edges(
                root,
                path,
                current_package=current_package,
                source_layer=source_layer,
                product_packages=product_packages,
                dynamic_import_allowlist=dynamic_import_allowlist,
                edges=edges,
            )
    return tuple(sorted(edges))


def _target_layer(module: str, product_packages: frozenset[str]) -> str | None:
    if module == "pmpe":
        return "core"
    if module.startswith("pmpe."):
        return _layer(module.split(".", 2)[1])
    if module.split(".", 1)[0] in product_packages:
        return "product"
    return None


def _dynamic_import_call(
    node: ast.Call,
    *,
    importlib_aliases: set[str],
    import_module_aliases: set[str],
) -> bool:
    reflective_loader = bool(
        isinstance(node.func, ast.Call)
        and isinstance(node.func.func, ast.Name)
        and node.func.func.id == "getattr"
        and len(node.func.args) >= 2
        and isinstance(node.func.args[0], ast.Name)
        and node.func.args[0].id in importlib_aliases
        and isinstance(node.func.args[1], ast.Constant)
        and node.func.args[1].value == "import_module"
    )
    return bool(
        (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in importlib_aliases
            and node.func.attr == "import_module"
        )
        or (isinstance(node.func, ast.Name) and node.func.id in import_module_aliases)
        or reflective_loader
    )


def _collect_architecture_edges(
    root: Path,
    path: Path,
    *,
    current_package: str,
    source_layer: str,
    product_packages: frozenset[str],
    dynamic_import_allowlist: tuple[tuple[str, int, str, str], ...],
    edges: set[tuple[str, str]],
) -> None:
    source_lines = path.read_text().splitlines()
    tree = ast.parse("\n".join(source_lines) + "\n", filename=str(path))
    importlib_aliases = {"importlib"}
    import_module_aliases = {"import_module", "__import__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "importlib":
                    importlib_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module == "importlib":
            for alias in node.names:
                if alias.name == "import_module":
                    import_module_aliases.add(alias.asname or alias.name)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id in importlib_aliases
            and not (isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str))
        ):
            edges.add((source_layer, "unresolved_dynamic"))
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if isinstance(value, ast.Name) and value.id in importlib_aliases:
                for target in targets:
                    if isinstance(target, ast.Name) and target.id not in importlib_aliases:
                        importlib_aliases.add(target.id)
                        changed = True
            is_loader = bool(
                isinstance(value, ast.Name)
                and value.id in import_module_aliases
                or isinstance(value, ast.Attribute)
                and isinstance(value.value, ast.Name)
                and value.value.id in importlib_aliases
                and value.attr == "import_module"
                or isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id == "getattr"
                and len(value.args) >= 2
                and isinstance(value.args[0], ast.Name)
                and value.args[0].id in importlib_aliases
                and isinstance(value.args[1], ast.Constant)
                and value.args[1].value == "import_module"
            )
            if not is_loader:
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id not in import_module_aliases:
                    import_module_aliases.add(target.id)
                    changed = True
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                relative_name = "." * node.level + (node.module or "")
                resolved = importlib.util.resolve_name(relative_name, current_package)
            else:
                resolved = node.module or ""
            imported_names = [
                f"{resolved}.{alias.name}" for alias in node.names if alias.name != "*"
            ]
            modules = [resolved, *imported_names] if node.module else imported_names
        elif isinstance(node, ast.Call) and _dynamic_import_call(
            node,
            importlib_aliases=importlib_aliases,
            import_module_aliases=import_module_aliases,
        ):
            if (
                node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                dynamic_target = node.args[0].value
                if dynamic_target.startswith("."):
                    package: str | None = None
                    if len(node.args) > 1:
                        package_node = node.args[1]
                        if isinstance(package_node, ast.Name) and package_node.id == "__package__":
                            package = current_package
                        elif isinstance(package_node, ast.Constant) and isinstance(
                            package_node.value, str
                        ):
                            package = package_node.value
                    if package is None:
                        edges.add((source_layer, "unresolved_dynamic"))
                        continue
                    dynamic_target = importlib.util.resolve_name(dynamic_target, package)
                modules = [dynamic_target]
            else:
                relative_path = path.relative_to(root).as_posix()
                source_line = source_lines[node.lineno - 1]
                fingerprint = canonical_digest({"source_line": source_line})
                identity = (
                    relative_path,
                    node.lineno,
                    fingerprint,
                    _file_digest(path),
                )
                if identity not in dynamic_import_allowlist:
                    edges.add((source_layer, "unresolved_dynamic"))
                continue
        for module in modules:
            target_layer = _target_layer(module, product_packages)
            if target_layer is not None and source_layer != target_layer:
                edges.add((source_layer, target_layer))


def _dependency_inventory(
    audit_payload: object, license_fallbacks: dict[str, str]
) -> tuple[tuple[str, str, str], ...]:
    if not isinstance(audit_payload, dict) or not isinstance(
        audit_payload.get("dependencies"), list
    ):
        raise ValueError("pip-audit JSON lacks a dependency inventory")
    inventory: list[tuple[str, str, str]] = []
    for item in audit_payload["dependencies"]:
        if not isinstance(item, dict):
            raise ValueError("pip-audit dependency entry is malformed")
        name = item.get("name")
        package_version = item.get("version")
        vulnerabilities = item.get("vulns")
        if not isinstance(name, str) or not isinstance(package_version, str):
            raise ValueError("pip-audit dependency identity is malformed")
        if not isinstance(vulnerabilities, list):
            raise ValueError("pip-audit vulnerability inventory is malformed")
        try:
            metadata = distribution(name).metadata
        except PackageNotFoundError as exc:
            raise ValueError(f"audited dependency {name} is not installed") from exc
        metadata_fields = metadata.json
        license_value = (
            metadata_fields.get("license_expression")
            or metadata_fields.get("license")
            or license_fallbacks.get(name.lower(), "")
        )
        license_name = (
            " OR ".join(license_value) if isinstance(license_value, list) else license_value
        )
        if not isinstance(license_name, str) or not license_name:
            raise ValueError(f"audited dependency {name} has no governed license identity")
        inventory.append((name, package_version, license_name))
    return tuple(sorted(inventory, key=lambda item: item[0].lower()))


def _advisory_findings(
    audit_payload: object, candidate_sha: str
) -> tuple[NormalizedSecurityFinding, ...]:
    if not isinstance(audit_payload, dict):
        raise ValueError("pip-audit JSON is malformed")
    findings: list[NormalizedSecurityFinding] = []
    for dependency in audit_payload.get("dependencies", []):
        if not isinstance(dependency, dict):
            continue
        for vulnerability in dependency.get("vulns", []):
            if not isinstance(vulnerability, dict):
                continue
            vulnerability_id = str(vulnerability.get("id", "unknown"))
            name = str(dependency.get("name", "unknown"))
            findings.append(
                NormalizedSecurityFinding(
                    finding_id=f"ADVISORY-{name}-{vulnerability_id}",
                    category="ADVISORY",
                    severity="HIGH",
                    rule_id=vulnerability_id,
                    path="requirements.lock",
                    line=1,
                    message=f"Known vulnerability reported for {name} (details redacted).",
                    subject_sha=candidate_sha,
                    evidence_digest=canonical_digest(
                        {
                            "candidate_sha": candidate_sha,
                            "dependency": name,
                            "vulnerability_id": vulnerability_id,
                        }
                    ),
                )
            )
    return tuple(findings)


def _profile_attestation(
    evidence_class: str, candidate_sha: str, payload: object, authority: str
) -> ProfileEvidenceAttestation:
    shell = ProfileEvidenceAttestation(
        evidence_class=evidence_class,
        candidate_sha=candidate_sha,
        payload_digest=canonical_digest(payload),
        authority_digest=authority,
        authentication_evidence_digest="",
    )
    return replace(
        shell,
        authentication_evidence_digest=_proof(
            "profile",
            evidence_class,
            authority,
            profile_authentication_payload(shell),
        ),
    )


def _privacy_evidence_from_artifact(
    artifact_path: Path,
    *,
    candidate_sha: str,
    policy_path: Path,
    verifier_path: Path,
) -> PrivacyEvidence:
    value = _load_json(artifact_path)
    if not isinstance(value, dict):
        raise ValueError("privacy verifier artifact is malformed")
    evidence_digest = value.pop("evidence_digest", None)
    exact = bool(
        isinstance(evidence_digest, str)
        and evidence_digest == canonical_digest(value)
        and value.get("candidate_sha") == candidate_sha
        and value.get("policy_file_digest") == _file_digest(policy_path)
        and value.get("verifier_file_digest") == _file_digest(verifier_path)
        and value.get("retention_test_passed") is True
        and value.get("telemetry_test_passed") is True
        and isinstance(value.get("emitted_telemetry"), list)
    )
    if not exact:
        raise ValueError("privacy verifier artifact is not exact or authenticated")
    shell = PrivacyEvidence(
        classification=str(value["classification"]),
        retention_days=int(value["retention_days"]),
        deletion_test_passed=value.get("deletion_test_passed") is True,
        residency=value.get("residency") if isinstance(value.get("residency"), str) else None,
        emitted_telemetry=tuple(str(item) for item in value["emitted_telemetry"]),
        evidence_digest="",
    )
    payload = asdict(shell)
    payload.pop("evidence_digest")
    return replace(shell, evidence_digest=canonical_digest(payload))


def _tool(name: str, tool_version: str, ruleset: Path) -> ToolIdentity:
    return ToolIdentity(name=name, version=tool_version, ruleset_digest=_file_digest(ruleset))


def _build_policy(
    root: Path,
    config: dict[str, Any],
    policy_path: Path,
    secret_allowlist_path: Path,
    profile_authority: str,
    privacy_authority: str,
    advisory_authority: str,
) -> SecurityGatePolicy:
    secret_allowlist = tuple(
        SecretAllowlistEntry(**item) for item in _load_json(secret_allowlist_path)
    )
    sast_allowlist = tuple(SastAllowlistEntry(**item) for item in config["sast_allowlist"])
    security_module = root / "src" / "pmpe" / "quality" / "security_profiles.py"
    scanner_module = root / "src" / "pmpe" / "quality" / "security_scan.py"
    tools = (
        _tool("secret-scanner", "1.0.0", scanner_module),
        _tool("bandit", version("bandit"), root / "pyproject.toml"),
        _tool("pip-audit", version("pip-audit"), root / "requirements.lock"),
        _tool("license-scanner", "1.0.0", policy_path),
        _tool("sbom-builder", "1.0.0", security_module),
        _tool("privacy-verifier", "1.0.0", policy_path),
        _tool("boundary-verifier", "1.0.0", policy_path),
    )
    allowed_edges = tuple(tuple(edge) for edge in config["allowed_architecture_edges"])
    boundary_digest = canonical_digest(
        {"allowed_architecture_edges": [list(edge) for edge in allowed_edges]}
    )
    shell = SecurityGatePolicy(
        version="security-profile/v1",
        policy_digest="",
        required_profiles=(
            "secret",
            "sast",
            "sca",
            "license_pinning",
            "sbom",
            "privacy",
            "architecture_boundary",
        ),
        tools=tools,
        trusted_advisory_sources={"pypi-advisory-db": advisory_authority},
        advisory_max_age_seconds={"pypi-advisory-db": 3600},
        trusted_waiver_authorities={},
        trusted_architecture_boundary_digest=boundary_digest,
        trusted_architecture_allowed_edges=allowed_edges,
        trusted_profile_authorities={
            **dict.fromkeys(
                (
                    "architecture_observation",
                    "dependency_inventory",
                    "privacy_intent",
                ),
                profile_authority,
            ),
            "privacy_evidence": privacy_authority,
        },
        allowed_licenses=tuple(config["allowed_licenses"]),
        scan_exclusions=(".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache"),
        secret_allowlist=secret_allowlist,
        sast_allowlist=sast_allowlist,
    )
    payload = shell.as_dict()
    payload.pop("policy_digest")
    return replace(shell, policy_digest=canonical_digest(payload))


def _evaluate(
    root: Path,
    candidate_sha: str,
    audit_path: Path,
    privacy_evidence_path: Path,
    policy_path: Path,
    secret_allowlist_path: Path,
) -> bytes:
    privacy_verifier_path = root / "scripts" / "ci" / "verify_privacy_controls.py"
    config = _reviewed_policy_config(_load_json(policy_path))
    audit_payload = _load_json(audit_path)
    profile_authority = canonical_digest(
        {"authority": "repository-profile-evidence", "policy_digest": _file_digest(policy_path)}
    )
    privacy_authority = canonical_digest(
        {
            "authority": "executed-privacy-verifier",
            "verifier_digest": _file_digest(privacy_verifier_path),
        }
    )
    advisory_authority = canonical_digest(
        {"authority": "pip-audit", "ruleset_digest": _file_digest(root / "requirements.lock")}
    )
    policy = _build_policy(
        root,
        config,
        policy_path,
        secret_allowlist_path,
        profile_authority,
        privacy_authority,
        advisory_authority,
    )
    dependency_inventory = _dependency_inventory(audit_payload, config["license_fallbacks"])

    privacy = config["privacy"]
    intent = PrivacyIntent(
        classification=privacy["classification"],
        retention_days=privacy["retention_days"],
        deletion_required=privacy["deletion_required"],
        residency=privacy["residency"],
        telemetry_allowlist=tuple(privacy["telemetry_allowlist"]),
    )
    privacy_evidence = _privacy_evidence_from_artifact(
        privacy_evidence_path,
        candidate_sha=candidate_sha,
        policy_path=policy_path,
        verifier_path=privacy_verifier_path,
    )

    allowed_edges = policy.trusted_architecture_allowed_edges
    dynamic_import_allowlist = tuple(
        (
            str(item["path"]),
            int(item["line"]),
            str(item["line_fingerprint"]),
            str(item["file_digest"]),
        )
        for item in config["dynamic_import_allowlist"]
    )
    architecture_shell = ArchitectureBoundaryObservation(
        architecture_pack_digest=_file_digest(root / "docs" / "v3" / "architecture.md"),
        boundary_policy_version="architecture-boundary/v1",
        boundary_policy_digest=policy.trusted_architecture_boundary_digest,
        allowed_edges=allowed_edges,
        observed_edges=_observed_architecture_edges(
            root,
            dynamic_import_allowlist=dynamic_import_allowlist,
        ),
        evidence_digest="",
    )
    architecture_payload = asdict(architecture_shell)
    architecture_payload.pop("evidence_digest")
    architecture = replace(
        architecture_shell, evidence_digest=canonical_digest(architecture_payload)
    )

    now = datetime.now(UTC)
    snapshot_shell = AdvisorySnapshot(
        source="pypi-advisory-db",
        subject_sha=candidate_sha,
        snapshot_digest=canonical_digest(audit_payload),
        generated_at=now.isoformat(),
        fetched_at=now.isoformat(),
        evaluated_at=now.isoformat(),
        expires_at=(now + timedelta(minutes=15)).isoformat(),
        authority_digest=advisory_authority,
        authentication_evidence_digest="",
        findings=_advisory_findings(audit_payload, candidate_sha),
    )
    snapshot = replace(
        snapshot_shell,
        authentication_evidence_digest=_proof(
            "advisory",
            snapshot_shell.source,
            advisory_authority,
            advisory_authentication_payload(snapshot_shell),
        ),
    )
    payloads: tuple[tuple[str, object, str], ...] = (
        ("dependency_inventory", dependency_inventory, profile_authority),
        ("privacy_intent", intent, profile_authority),
        ("privacy_evidence", privacy_evidence, privacy_authority),
        ("architecture_observation", architecture, profile_authority),
    )
    subject = SecurityProfileInput(
        candidate_sha=candidate_sha,
        repository_root=root,
        dependency_inventory=dependency_inventory,
        advisory_snapshots=(snapshot,),
        privacy_intent=intent,
        privacy_evidence=privacy_evidence,
        architecture=architecture,
        waivers=(),
        profile_attestations=tuple(
            _profile_attestation(name, candidate_sha, payload, authority)
            for name, payload, authority in payloads
        ),
    )
    report = evaluate_security_profile(
        subject,
        policy,
        repository_authenticator=_repository_is_exact,
        advisory_authenticator=_authenticator("advisory"),
        waiver_authenticator=None,
        profile_authenticator=_authenticator("profile"),
    )
    if report.blocked:
        rules = ", ".join(sorted({finding.rule_id for finding in report.findings}))
        raise ValueError(f"composed security profile blocked: {rules}")
    return report.canonical_bytes()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--audit-evidence", type=Path, required=True)
    parser.add_argument("--privacy-evidence", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--secret-allowlist", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path.cwd().resolve()
    report = _evaluate(
        root,
        args.candidate_sha,
        args.audit_evidence,
        args.privacy_evidence,
        args.policy,
        args.secret_allowlist,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(report + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
