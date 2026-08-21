#!/usr/bin/env python3
"""Evaluate the composed security profile against an exact checked-out candidate."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess  # nosec B404 - fixed git argv authenticates the local checkout
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


def _layer(package: str) -> str:
    for layer, packages in _LAYERS.items():
        if package in packages:
            return layer
    return "core"


def _observed_architecture_edges(root: Path) -> tuple[tuple[str, str], ...]:
    edges: set[tuple[str, str]] = set()
    source_root = root / "src" / "pmpe"
    for path in sorted(source_root.rglob("*.py")):
        relative_parts = path.relative_to(source_root).parts
        source_package = relative_parts[0] if len(relative_parts) > 1 else "root"
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            for module in modules:
                if not module.startswith("pmpe."):
                    continue
                target_package = module.split(".", 2)[1]
                source_layer = _layer(source_package)
                target_layer = _layer(target_package)
                if source_layer != target_layer:
                    edges.add((source_layer, target_layer))
    return tuple(sorted(edges))


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
        metadata_fields = dict(metadata.items())
        license_name = (
            metadata_fields.get("License-Expression")
            or metadata_fields.get("License")
            or license_fallbacks.get(name.lower(), "")
        )
        if not license_name:
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


def _tool(name: str, tool_version: str, ruleset: Path) -> ToolIdentity:
    return ToolIdentity(name=name, version=tool_version, ruleset_digest=_file_digest(ruleset))


def _build_policy(
    root: Path, config: dict[str, Any], profile_authority: str, advisory_authority: str
) -> SecurityGatePolicy:
    secret_allowlist = tuple(
        SecretAllowlistEntry(**item)
        for item in _load_json(root / "security" / "secret-allowlist.json")
    )
    sast_allowlist = tuple(SastAllowlistEntry(**item) for item in config["sast_allowlist"])
    security_module = root / "src" / "pmpe" / "quality" / "security_profiles.py"
    scanner_module = root / "src" / "pmpe" / "quality" / "security_scan.py"
    policy_path = root / "security" / "security-profile-policy.json"
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
        trusted_profile_authorities=dict.fromkeys(
            (
                "architecture_observation",
                "dependency_inventory",
                "privacy_evidence",
                "privacy_intent",
            ),
            profile_authority,
        ),
        allowed_licenses=tuple(config["allowed_licenses"]),
        scan_exclusions=(".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache"),
        secret_allowlist=secret_allowlist,
        sast_allowlist=sast_allowlist,
    )
    payload = shell.as_dict()
    payload.pop("policy_digest")
    return replace(shell, policy_digest=canonical_digest(payload))


def _evaluate(root: Path, candidate_sha: str, audit_path: Path) -> bytes:
    config_path = root / "security" / "security-profile-policy.json"
    config = _load_json(config_path)
    if not isinstance(config, dict) or config.get("version") != "repository-security-profile/v1":
        raise ValueError("repository security profile policy is malformed")
    audit_payload = _load_json(audit_path)
    profile_authority = canonical_digest(
        {"authority": "repository-profile-evidence", "policy_digest": _file_digest(config_path)}
    )
    advisory_authority = canonical_digest(
        {"authority": "pip-audit", "ruleset_digest": _file_digest(root / "requirements.lock")}
    )
    policy = _build_policy(root, config, profile_authority, advisory_authority)
    dependency_inventory = _dependency_inventory(audit_payload, config["license_fallbacks"])

    privacy = config["privacy"]
    intent = PrivacyIntent(
        classification=privacy["classification"],
        retention_days=privacy["retention_days"],
        deletion_required=privacy["deletion_required"],
        residency=privacy["residency"],
        telemetry_allowlist=tuple(privacy["telemetry_allowlist"]),
    )
    evidence_shell = PrivacyEvidence(
        classification=privacy["classification"],
        retention_days=privacy["retention_days"],
        deletion_test_passed=privacy["deletion_test_passed"],
        residency=privacy["residency"],
        emitted_telemetry=tuple(privacy["emitted_telemetry"]),
        evidence_digest="",
    )
    evidence_payload = asdict(evidence_shell)
    evidence_payload.pop("evidence_digest")
    privacy_evidence = replace(evidence_shell, evidence_digest=canonical_digest(evidence_payload))

    allowed_edges = policy.trusted_architecture_allowed_edges
    architecture_shell = ArchitectureBoundaryObservation(
        architecture_pack_digest=_file_digest(root / "docs" / "v3" / "architecture.md"),
        boundary_policy_version="architecture-boundary/v1",
        boundary_policy_digest=policy.trusted_architecture_boundary_digest,
        allowed_edges=allowed_edges,
        observed_edges=_observed_architecture_edges(root),
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
    payloads: tuple[tuple[str, object], ...] = (
        ("dependency_inventory", dependency_inventory),
        ("privacy_intent", intent),
        ("privacy_evidence", privacy_evidence),
        ("architecture_observation", architecture),
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
            _profile_attestation(name, candidate_sha, payload, profile_authority)
            for name, payload in payloads
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
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path.cwd().resolve()
    report = _evaluate(root, args.candidate_sha, args.audit_evidence)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(report + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
