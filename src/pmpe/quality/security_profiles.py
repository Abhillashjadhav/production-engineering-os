"""Verification-first security, privacy, supply-chain, and boundary profiles.

The module is deliberately provider-neutral. External scanners and advisory feeds
produce normalized immutable inputs; this control plane authenticates, binds, and
evaluates those inputs without treating tool prose as completion evidence.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from pmpe.audit.evidence import (
    EnvironmentFingerprint,
    EvidenceItem,
    EvidenceProducer,
)
from pmpe.audit.evidence import (
    ToolIdentity as EvidenceToolIdentity,
)
from pmpe.contracts.canonical import canonical_json_bytes
from pmpe.contracts.digest import canonical_digest
from pmpe.quality.security_scan import scan_tree

_SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_EXACT_VERSION = re.compile(r"^[0-9]+(?:\.[0-9A-Za-z][0-9A-Za-z.-]*)+$")
_REQUIRED_PROFILES = (
    "secret",
    "sast",
    "sca",
    "license_pinning",
    "sbom",
    "privacy",
    "architecture_boundary",
)
_PROFILE_TO_TOOL = {
    "secret": "secret-scanner",
    "sast": "bandit",
    "sca": "pip-audit",
    "license_pinning": "license-scanner",
    "sbom": "sbom-builder",
    "privacy": "privacy-verifier",
    "architecture_boundary": "boundary-verifier",
}
_PERMITTED_EXCLUSIONS = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache"}
_LOCKFILE_NAMES = {
    "requirements.lock",
    "package-lock.json",
    "poetry.lock",
    "uv.lock",
    "pdm.lock",
    "Pipfile.lock",
}
_SECRET_PATTERNS = (
    re.compile(r"(?<![A-Za-z0-9])ghp_[A-Za-z0-9]{36,}"),
    re.compile(r"(?<![A-Za-z0-9])github_pat_[A-Za-z0-9_]{22,}"),
    re.compile(r"(?<![A-Za-z0-9])AKIA[A-Z0-9]{16}"),
    re.compile(
        r"(?i)\b(?:api[_-]?key|access[_-]?token|service[_-]?token|password|secret)\b"
        r"\s*[:=]\s*[\"']?([A-Za-z0-9_./+=-]{12,})"
    ),
)
AdvisoryAuthenticator = Callable[[str, str, object, str], bool]
WaiverAuthenticator = Callable[[str, str, object, str], bool]
TrustedClock = Callable[[], datetime]


class GateDisposition(StrEnum):
    PASS = "PASS"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class ToolIdentity:
    name: str
    version: str
    ruleset_digest: str


@dataclass(frozen=True)
class SecretAllowlistEntry:
    path: str
    line: int
    fingerprint: str
    justification: str
    approved_by: str
    expires_at: str


@dataclass(frozen=True)
class SecurityGatePolicy:
    version: str
    policy_digest: str
    required_profiles: tuple[str, ...]
    tools: tuple[ToolIdentity, ...]
    trusted_advisory_sources: Mapping[str, str]
    advisory_max_age_seconds: Mapping[str, int]
    trusted_waiver_authorities: Mapping[str, str]
    scan_exclusions: tuple[str, ...]
    secret_allowlist: tuple[SecretAllowlistEntry, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "advisory_max_age_seconds": dict(sorted(self.advisory_max_age_seconds.items())),
            "policy_digest": self.policy_digest,
            "required_profiles": list(self.required_profiles),
            "scan_exclusions": list(self.scan_exclusions),
            "secret_allowlist": [
                asdict(item)
                for item in sorted(
                    self.secret_allowlist,
                    key=lambda value: (value.path, value.line, value.fingerprint),
                )
            ],
            "tools": [asdict(item) for item in sorted(self.tools, key=lambda value: value.name)],
            "trusted_advisory_sources": dict(sorted(self.trusted_advisory_sources.items())),
            "trusted_waiver_authorities": dict(sorted(self.trusted_waiver_authorities.items())),
            "version": self.version,
        }


@dataclass(frozen=True)
class NormalizedSecurityFinding:
    finding_id: str
    category: str
    severity: str
    rule_id: str
    path: str
    line: int
    message: str
    subject_sha: str
    evidence_digest: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def digest(self) -> str:
        return canonical_digest(self.as_dict())


@dataclass(frozen=True)
class AdvisorySnapshot:
    source: str
    subject_sha: str
    snapshot_digest: str
    generated_at: str
    fetched_at: str
    evaluated_at: str
    expires_at: str
    authority_digest: str
    authentication_evidence_digest: str
    findings: tuple[NormalizedSecurityFinding, ...]


def advisory_authentication_payload(snapshot: AdvisorySnapshot) -> dict[str, Any]:
    payload = asdict(snapshot)
    payload.pop("authentication_evidence_digest")
    return payload


@dataclass(frozen=True)
class PrivacyIntent:
    classification: str
    retention_days: int
    deletion_required: bool
    residency: str
    telemetry_allowlist: tuple[str, ...]


@dataclass(frozen=True)
class PrivacyEvidence:
    classification: str
    retention_days: int
    deletion_test_passed: bool
    residency: str
    emitted_telemetry: tuple[str, ...]
    evidence_digest: str


@dataclass(frozen=True)
class ArchitectureBoundaryObservation:
    architecture_pack_digest: str
    boundary_policy_version: str
    boundary_policy_digest: str
    allowed_edges: tuple[tuple[str, str], ...]
    observed_edges: tuple[tuple[str, str], ...]
    evidence_digest: str


@dataclass(frozen=True)
class WaiverRecord:
    finding_digest: str
    severity: str
    candidate_sha: str
    policy_digest: str
    scope_digest: str
    approved_by: str
    expires_at: str
    authority_digest: str
    authentication_evidence_digest: str


def waiver_authentication_payload(waiver: WaiverRecord) -> dict[str, Any]:
    payload = asdict(waiver)
    payload.pop("authentication_evidence_digest")
    return payload


@dataclass(frozen=True)
class SecurityProfileInput:
    candidate_sha: str
    repository_root: Path
    dependency_inventory: tuple[tuple[str, str, str], ...]
    allowed_licenses: tuple[str, ...]
    advisory_snapshots: tuple[AdvisorySnapshot, ...]
    privacy_intent: PrivacyIntent | None
    privacy_evidence: PrivacyEvidence | None
    architecture: ArchitectureBoundaryObservation | None
    waivers: tuple[WaiverRecord, ...]


@dataclass(frozen=True)
class SecurityProfileReport:
    candidate_sha: str
    policy_digest: str
    disposition: GateDisposition
    executed_profiles: tuple[str, ...]
    blocked_profiles: tuple[str, ...]
    findings: tuple[NormalizedSecurityFinding, ...]
    blocking_finding_digests: tuple[str, ...]
    tool_identities: tuple[ToolIdentity, ...]
    advisory_snapshot_digests: tuple[str, ...]
    sbom: Mapping[str, Any]
    report_digest: str

    @property
    def passed(self) -> bool:
        return self.disposition is GateDisposition.PASS

    @property
    def blocked(self) -> bool:
        return self.disposition is GateDisposition.BLOCKED

    def without_digest(self) -> dict[str, Any]:
        return {
            "advisory_snapshot_digests": list(self.advisory_snapshot_digests),
            "blocked_profiles": list(self.blocked_profiles),
            "blocking_finding_digests": list(self.blocking_finding_digests),
            "candidate_sha": self.candidate_sha,
            "disposition": self.disposition.value,
            "executed_profiles": list(self.executed_profiles),
            "findings": [item.as_dict() for item in self.findings],
            "policy_digest": self.policy_digest,
            "sbom": dict(self.sbom),
            "tool_identities": [asdict(item) for item in self.tool_identities],
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes({**self.without_digest(), "report_digest": self.report_digest})


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must carry a timezone")
    return parsed


def _utc_now() -> datetime:
    return datetime.now(UTC)


def secret_fingerprint(value: str) -> str:
    return canonical_digest({"secret_value": value})


def _validate_scan_controls(
    exclusions: Sequence[str], allowlist: Sequence[SecretAllowlistEntry]
) -> None:
    for exclusion in exclusions:
        if Path(exclusion).name in _LOCKFILE_NAMES:
            raise ValueError("tracked lockfiles can never be excluded")
        if exclusion not in _PERMITTED_EXCLUSIONS:
            raise ValueError("broad scan exclusion is forbidden")
    for entry in allowlist:
        candidate = Path(entry.path)
        if (
            not entry.path
            or candidate.is_absolute()
            or ".." in candidate.parts
            or any(character in entry.path for character in "*?[]")
            or not candidate.suffix
        ):
            raise ValueError("secret allowlist must identify one exact file")
        if candidate.name in _LOCKFILE_NAMES:
            raise ValueError("tracked lockfiles cannot be allowlisted")
        if entry.line <= 0 or not _DIGEST.fullmatch(entry.fingerprint):
            raise ValueError("secret allowlist line or fingerprint is malformed")
        if not entry.justification.strip() or not entry.approved_by.strip():
            raise ValueError("secret allowlist requires reviewed justification")
        _time(entry.expires_at)


def validate_gate_policy(policy: SecurityGatePolicy) -> None:
    if policy.version != "security-profile/v1":
        raise ValueError("security profile version is unsupported")
    if len(policy.required_profiles) != len(set(policy.required_profiles)) or set(
        policy.required_profiles
    ) != set(_REQUIRED_PROFILES):
        raise ValueError("required profile inventory is incomplete or duplicated")
    tool_by_name = {item.name: item for item in policy.tools}
    if len(tool_by_name) != len(policy.tools):
        raise ValueError("tool identities are duplicated")
    for identity in policy.tools:
        if not identity.name or not _EXACT_VERSION.fullmatch(identity.version):
            raise ValueError(f"{identity.name or 'tool'} lacks an exact tool version")
        if not _DIGEST.fullmatch(identity.ruleset_digest):
            raise ValueError(f"{identity.name} ruleset digest is malformed")
    for profile, tool_name in _PROFILE_TO_TOOL.items():
        profile_tool = tool_by_name.get(tool_name)
        if profile in policy.required_profiles and profile_tool is None:
            raise ValueError(f"required profile {profile} lacks its tool identity")
    if not policy.trusted_advisory_sources:
        raise ValueError("at least one trusted advisory source is required")
    if set(policy.trusted_advisory_sources) != set(policy.advisory_max_age_seconds):
        raise ValueError("advisory source freshness policy is incomplete")
    if any(
        not source
        or not _DIGEST.fullmatch(authority)
        or policy.advisory_max_age_seconds.get(source, 0) <= 0
        for source, authority in policy.trusted_advisory_sources.items()
    ):
        raise ValueError("advisory source authority or maximum age is invalid")
    if any(
        not actor or not _DIGEST.fullmatch(digest)
        for actor, digest in policy.trusted_waiver_authorities.items()
    ):
        raise ValueError("waiver authority is malformed")
    _validate_scan_controls(policy.scan_exclusions, policy.secret_allowlist)
    payload = policy.as_dict()
    claimed = payload.pop("policy_digest")
    if not _DIGEST.fullmatch(claimed) or claimed != canonical_digest(payload):
        raise ValueError("security gate policy digest is invalid")


def _finding(
    *,
    finding_id: str,
    category: str,
    severity: str,
    rule_id: str,
    path: str,
    line: int,
    message: str,
    subject_sha: str,
    evidence: object,
) -> NormalizedSecurityFinding:
    return NormalizedSecurityFinding(
        finding_id=finding_id,
        category=category,
        severity=severity,
        rule_id=rule_id,
        path=path,
        line=line,
        message=message,
        subject_sha=subject_sha,
        evidence_digest=canonical_digest(evidence),
    )


def _secret_allowlisted(
    *,
    path: str,
    line: int,
    fingerprint: str,
    allowlist: Sequence[SecretAllowlistEntry],
    now: datetime,
) -> bool:
    return any(
        entry.path == path
        and entry.line == line
        and entry.fingerprint == fingerprint
        and now <= _time(entry.expires_at)
        for entry in allowlist
    )


def _scan_secrets(
    root: Path,
    *,
    subject_sha: str,
    exclusions: Sequence[str],
    allowlist: Sequence[SecretAllowlistEntry],
    now: datetime,
) -> tuple[NormalizedSecurityFinding, ...]:
    findings: list[NormalizedSecurityFinding] = []
    observed: set[tuple[str, int, str]] = set()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            try:
                text = os.readlink(path)
            except OSError:
                continue
        elif path.is_file():
            try:
                text = path.read_text(errors="strict")
            except (OSError, UnicodeError):
                continue
        else:
            continue
        relative = path.relative_to(root)
        if any(part in exclusions for part in relative.parts):
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for pattern in _SECRET_PATTERNS:
                for match in pattern.finditer(line):
                    value = match.group(1) if match.lastindex else match.group(0)
                    fingerprint = secret_fingerprint(value)
                    identity = (relative.as_posix(), line_number, fingerprint)
                    if identity in observed:
                        continue
                    observed.add(identity)
                    if _secret_allowlisted(
                        path=relative.as_posix(),
                        line=line_number,
                        fingerprint=fingerprint,
                        allowlist=allowlist,
                        now=now,
                    ):
                        continue
                    findings.append(
                        _finding(
                            finding_id=f"SECRET-{len(findings) + 1:04d}",
                            category="SECRET",
                            severity="CRITICAL",
                            rule_id="SECRET_CREDENTIAL_PATTERN",
                            path=relative.as_posix(),
                            line=line_number,
                            message="Credential-shaped value detected (value redacted).",
                            subject_sha=subject_sha,
                            evidence={
                                "fingerprint": fingerprint,
                                "path": relative.as_posix(),
                                "line": line_number,
                            },
                        )
                    )
    return tuple(findings)


def _allowlist_expiry_findings(
    allowlist: Sequence[SecretAllowlistEntry],
    *,
    subject_sha: str,
    initial_time: datetime,
    final_time: datetime,
) -> tuple[NormalizedSecurityFinding, ...]:
    expired = tuple(
        entry for entry in allowlist if initial_time <= _time(entry.expires_at) < final_time
    )
    return tuple(
        _finding(
            finding_id=f"SECRET-ALLOWLIST-EXPIRED-{index:04d}",
            category="SECRET",
            severity="CRITICAL",
            rule_id="SECRET_ALLOWLIST_EXPIRED_DURING_SCAN",
            path=entry.path,
            line=entry.line,
            message="A synthetic-secret allowlist entry expired during scanning.",
            subject_sha=subject_sha,
            evidence={
                "approved_by": entry.approved_by,
                "expires_at": entry.expires_at,
                "fingerprint": entry.fingerprint,
                "path": entry.path,
                "line": entry.line,
            },
        )
        for index, entry in enumerate(expired, start=1)
    )


def scan_repository_secrets(
    root: Path,
    *,
    candidate_sha: str,
    exclusions: Sequence[str] = tuple(sorted(_PERMITTED_EXCLUSIONS)),
    allowlist: Sequence[SecretAllowlistEntry] = (),
    trusted_clock: TrustedClock = _utc_now,
) -> tuple[NormalizedSecurityFinding, ...]:
    """Run the no-ignore repository secret gate against an exact candidate SHA."""

    if not _SHA.fullmatch(candidate_sha):
        raise ValueError("secret scan candidate SHA is malformed")
    if not root.is_dir():
        raise ValueError("secret scan repository root is unavailable")
    _validate_scan_controls(exclusions, allowlist)
    now = trusted_clock()
    if now.tzinfo is None:
        raise ValueError("trusted secret scan clock must carry a timezone")
    findings = _scan_secrets(
        root,
        subject_sha=candidate_sha,
        exclusions=exclusions,
        allowlist=allowlist,
        now=now,
    )
    final_time = trusted_clock()
    if final_time.tzinfo is None:
        raise ValueError("trusted secret scan clock must carry a timezone")
    return (
        *findings,
        *_allowlist_expiry_findings(
            allowlist,
            subject_sha=candidate_sha,
            initial_time=now,
            final_time=final_time,
        ),
    )


def _scan_sast(root: Path, subject_sha: str) -> tuple[NormalizedSecurityFinding, ...]:
    normalized: list[NormalizedSecurityFinding] = []
    for item in scan_tree(root):
        path = Path(item.file)
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            relative = path.as_posix()
        severity = getattr(item.severity, "value", str(item.severity)).upper()
        normalized.append(
            _finding(
                finding_id=f"SAST-{len(normalized) + 1:04d}",
                category="SAST",
                severity=severity,
                rule_id=item.rule,
                path=relative,
                line=item.line,
                message=item.message,
                subject_sha=subject_sha,
                evidence={"rule": item.rule, "path": relative, "line": item.line},
            )
        )
    return tuple(normalized)


def _advisory_failure(
    subject_sha: str, source: str, rule_id: str, message: str
) -> NormalizedSecurityFinding:
    return _finding(
        finding_id=f"ADVISORY-{source or 'missing'}-{rule_id}",
        category="ADVISORY",
        severity="HIGH",
        rule_id=rule_id,
        path="",
        line=0,
        message=message,
        subject_sha=subject_sha,
        evidence={"source": source, "rule": rule_id},
    )


def _evaluate_advisories(
    subject: SecurityProfileInput,
    policy: SecurityGatePolicy,
    *,
    authenticator: AdvisoryAuthenticator | None,
    trusted_clock: TrustedClock,
) -> tuple[tuple[NormalizedSecurityFinding, ...], tuple[str, ...]]:
    findings: list[NormalizedSecurityFinding] = []
    admitted_digests: list[str] = []
    by_source = {snapshot.source: snapshot for snapshot in subject.advisory_snapshots}
    if len(by_source) != len(subject.advisory_snapshots):
        findings.append(
            _advisory_failure(
                subject.candidate_sha,
                "duplicate",
                "ADVISORY_SOURCE_DUPLICATED",
                "Advisory source inventory is duplicated.",
            )
        )
    freshness_windows: list[tuple[str, datetime, datetime]] = []
    for source, authority in policy.trusted_advisory_sources.items():
        snapshot = by_source.get(source)
        valid = False
        if snapshot is not None:
            try:
                generated = _time(snapshot.generated_at)
                fetched = _time(snapshot.fetched_at)
                evaluated = _time(snapshot.evaluated_at)
                expires = _time(snapshot.expires_at)
                initial_now = trusted_clock()
                valid = bool(
                    initial_now.tzinfo is not None
                    and snapshot.subject_sha == subject.candidate_sha
                    and snapshot.authority_digest == authority
                    and _DIGEST.fullmatch(snapshot.snapshot_digest)
                    and _DIGEST.fullmatch(snapshot.authentication_evidence_digest)
                    and generated <= fetched <= evaluated <= initial_now <= expires
                    and initial_now - fetched
                    <= timedelta(seconds=policy.advisory_max_age_seconds[source])
                    and authenticator is not None
                    and authenticator(
                        source,
                        authority,
                        advisory_authentication_payload(snapshot),
                        snapshot.authentication_evidence_digest,
                    )
                )
            except Exception:
                valid = False
            if valid:
                freshness_windows.append((source, fetched, expires))
                admitted_digests.append(snapshot.snapshot_digest)
                for item in snapshot.findings:
                    if item.subject_sha != subject.candidate_sha or not _DIGEST.fullmatch(
                        item.evidence_digest
                    ):
                        findings.append(
                            _advisory_failure(
                                subject.candidate_sha,
                                source,
                                "ADVISORY_FINDING_SUBJECT_INVALID",
                                "Advisory finding is not bound to the exact candidate.",
                            )
                        )
                    else:
                        findings.append(item)
        if not valid:
            findings.append(
                _advisory_failure(
                    subject.candidate_sha,
                    source,
                    "ADVISORY_UNAVAILABLE_OR_UNAUTHENTICATED",
                    "Advisory intelligence is missing, invalid, stale, or unauthenticated.",
                )
            )
    try:
        live_now = trusted_clock()
        if live_now.tzinfo is None:
            raise ValueError("trusted clock is timezone-naive")
    except Exception:
        live_now = None
        findings.append(
            _advisory_failure(
                subject.candidate_sha,
                "clock",
                "ADVISORY_TRUSTED_CLOCK_UNAVAILABLE",
                "Trusted advisory decision clock is unavailable.",
            )
        )
    if live_now is not None:
        for source, fetched, expires in freshness_windows:
            if not (
                fetched <= live_now <= expires
                and live_now - fetched <= timedelta(seconds=policy.advisory_max_age_seconds[source])
            ):
                findings.append(
                    _advisory_failure(
                        subject.candidate_sha,
                        source,
                        "ADVISORY_STALE_AFTER_AUTHENTICATION",
                        "Advisory intelligence became stale during authentication.",
                    )
                )
    for unknown in set(by_source) - set(policy.trusted_advisory_sources):
        findings.append(
            _advisory_failure(
                subject.candidate_sha,
                unknown,
                "ADVISORY_SOURCE_UNTRUSTED",
                "Advisory source is not governed by the security policy.",
            )
        )
    return tuple(findings), tuple(sorted(admitted_digests))


def _evaluate_dependencies(subject: SecurityProfileInput) -> tuple[NormalizedSecurityFinding, ...]:
    findings: list[NormalizedSecurityFinding] = []
    if not subject.dependency_inventory:
        return (
            _finding(
                finding_id="DEPENDENCY-INVENTORY-MISSING",
                category="LICENSE_PINNING",
                severity="HIGH",
                rule_id="DEPENDENCY_INVENTORY_MISSING",
                path="",
                line=0,
                message="Dependency inventory is missing.",
                subject_sha=subject.candidate_sha,
                evidence={"candidate_sha": subject.candidate_sha},
            ),
        )
    for name, version, license_name in subject.dependency_inventory:
        if not name or not _EXACT_VERSION.fullmatch(version):
            findings.append(
                _finding(
                    finding_id=f"PIN-{name or 'unknown'}",
                    category="LICENSE_PINNING",
                    severity="HIGH",
                    rule_id="DEPENDENCY_NOT_EXACTLY_PINNED",
                    path="",
                    line=0,
                    message="Dependency version is not exactly pinned.",
                    subject_sha=subject.candidate_sha,
                    evidence={"name": name, "version": version},
                )
            )
        if license_name not in subject.allowed_licenses:
            findings.append(
                _finding(
                    finding_id=f"LICENSE-{name or 'unknown'}",
                    category="LICENSE_PINNING",
                    severity="HIGH",
                    rule_id="DEPENDENCY_LICENSE_NOT_ALLOWED",
                    path="",
                    line=0,
                    message="Dependency license is not on the admitted allowlist.",
                    subject_sha=subject.candidate_sha,
                    evidence={"name": name, "license": license_name},
                )
            )
    return tuple(findings)


def build_deterministic_sbom(
    candidate_sha: str,
    policy_digest: str,
    inventory: Sequence[tuple[str, str, str]],
) -> dict[str, Any]:
    packages = [
        {"license": license_name, "name": name, "version": version}
        for name, version, license_name in sorted(inventory)
    ]
    payload: dict[str, Any] = {
        "candidate_sha": candidate_sha,
        "format": "pmpe-sbom/v1",
        "packages": packages,
        "policy_digest": policy_digest,
    }
    return {**payload, "sbom_digest": canonical_digest(payload)}


def _evaluate_privacy(subject: SecurityProfileInput) -> tuple[NormalizedSecurityFinding, ...]:
    intent = subject.privacy_intent
    evidence = subject.privacy_evidence
    evidence_payload = asdict(evidence) if evidence is not None else {}
    claimed_evidence_digest = str(evidence_payload.pop("evidence_digest", ""))
    valid = bool(
        intent is not None
        and evidence is not None
        and intent.classification
        and intent.retention_days >= 0
        and intent.classification == evidence.classification
        and intent.retention_days == evidence.retention_days
        and (not intent.deletion_required or evidence.deletion_test_passed)
        and intent.residency == evidence.residency
        and set(evidence.emitted_telemetry) <= set(intent.telemetry_allowlist)
        and claimed_evidence_digest == canonical_digest(evidence_payload)
    )
    if valid:
        return ()
    return (
        _finding(
            finding_id="PRIVACY-EVIDENCE-INVALID",
            category="PRIVACY",
            severity="HIGH",
            rule_id="PRIVACY_INTENT_NOT_PROVEN",
            path="",
            line=0,
            message=(
                "Privacy classification, retention, deletion, residency, or telemetry is unproven."
            ),
            subject_sha=subject.candidate_sha,
            evidence={
                "intent_present": intent is not None,
                "evidence_present": evidence is not None,
            },
        ),
    )


def _evaluate_architecture(subject: SecurityProfileInput) -> tuple[NormalizedSecurityFinding, ...]:
    observation = subject.architecture
    evidence_payload = asdict(observation) if observation is not None else {}
    claimed_evidence_digest = str(evidence_payload.pop("evidence_digest", ""))
    valid = bool(
        observation is not None
        and _DIGEST.fullmatch(observation.architecture_pack_digest)
        and observation.boundary_policy_version == "architecture-boundary/v1"
        and _DIGEST.fullmatch(observation.boundary_policy_digest)
        and claimed_evidence_digest == canonical_digest(evidence_payload)
        and set(observation.observed_edges) <= set(observation.allowed_edges)
    )
    if valid:
        return ()
    return (
        _finding(
            finding_id="ARCHITECTURE-BOUNDARY-INVALID",
            category="ARCHITECTURE_BOUNDARY",
            severity="HIGH",
            rule_id="ARCHITECTURE_BOUNDARY_DRIFT",
            path="",
            line=0,
            message="Architecture boundary policy or observed edge is invalid.",
            subject_sha=subject.candidate_sha,
            evidence={"observation_present": observation is not None},
        ),
    )


def _waiver_valid(
    finding: NormalizedSecurityFinding,
    waiver: WaiverRecord,
    *,
    subject: SecurityProfileInput,
    policy: SecurityGatePolicy,
    authenticator: WaiverAuthenticator | None,
    trusted_clock: TrustedClock,
) -> bool:
    authority = policy.trusted_waiver_authorities.get(waiver.approved_by, "")
    if finding.severity.upper() not in {"MEDIUM", "LOW"}:
        return False
    try:
        initial_time = trusted_clock()
        expires_at = _time(waiver.expires_at)
        initially_valid = bool(
            initial_time.tzinfo is not None
            and waiver.finding_digest == finding.digest
            and waiver.severity.upper() == finding.severity.upper()
            and waiver.candidate_sha == subject.candidate_sha
            and waiver.policy_digest == policy.policy_digest
            and _DIGEST.fullmatch(waiver.scope_digest)
            and authority
            and waiver.authority_digest == authority
            and initial_time <= expires_at
            and _DIGEST.fullmatch(waiver.authentication_evidence_digest)
            and authenticator is not None
            and authenticator(
                waiver.approved_by,
                authority,
                waiver_authentication_payload(waiver),
                waiver.authentication_evidence_digest,
            )
        )
        final_time = trusted_clock()
        return bool(initially_valid and final_time.tzinfo is not None and final_time <= expires_at)
    except Exception:
        return False


def _profile_for_finding(finding: NormalizedSecurityFinding) -> str:
    return {
        "SECRET": "secret",
        "SAST": "sast",
        "SCA": "sca",
        "ADVISORY": "sca",
        "LICENSE_PINNING": "license_pinning",
        "PRIVACY": "privacy",
        "ARCHITECTURE_BOUNDARY": "architecture_boundary",
    }.get(finding.category, "sca")


def evaluate_security_profile(
    subject: SecurityProfileInput,
    policy: SecurityGatePolicy,
    *,
    advisory_authenticator: AdvisoryAuthenticator | None,
    waiver_authenticator: WaiverAuthenticator | None,
    trusted_clock: TrustedClock = _utc_now,
) -> SecurityProfileReport:
    validate_gate_policy(policy)
    if not _SHA.fullmatch(subject.candidate_sha):
        raise ValueError("security profile candidate SHA is malformed")
    if not subject.repository_root.is_dir():
        raise ValueError("security profile repository root is unavailable")
    try:
        decision_time = trusted_clock()
        if decision_time.tzinfo is None:
            raise ValueError("trusted decision time must carry a timezone")
    except Exception as exc:
        raise ValueError("trusted security decision clock is unavailable") from exc

    findings: list[NormalizedSecurityFinding] = []
    findings.extend(
        _scan_secrets(
            subject.repository_root,
            subject_sha=subject.candidate_sha,
            exclusions=policy.scan_exclusions,
            allowlist=policy.secret_allowlist,
            now=decision_time,
        )
    )
    post_secret_time = trusted_clock()
    if post_secret_time.tzinfo is None:
        raise ValueError("trusted security decision clock is unavailable")
    findings.extend(
        _allowlist_expiry_findings(
            policy.secret_allowlist,
            subject_sha=subject.candidate_sha,
            initial_time=decision_time,
            final_time=post_secret_time,
        )
    )
    findings.extend(_scan_sast(subject.repository_root, subject.candidate_sha))
    advisory_findings, admitted_advisories = _evaluate_advisories(
        subject,
        policy,
        authenticator=advisory_authenticator,
        trusted_clock=trusted_clock,
    )
    findings.extend(advisory_findings)
    findings.extend(_evaluate_dependencies(subject))
    findings.extend(_evaluate_privacy(subject))
    findings.extend(_evaluate_architecture(subject))

    blocking: list[str] = []
    blocked_profiles: set[str] = set()
    waivers_by_finding = {item.finding_digest: item for item in subject.waivers}
    for finding in findings:
        waived = False
        candidate_waiver = waivers_by_finding.get(finding.digest)
        if candidate_waiver is not None:
            waived = _waiver_valid(
                finding,
                candidate_waiver,
                subject=subject,
                policy=policy,
                authenticator=waiver_authenticator,
                trusted_clock=trusted_clock,
            )
        if not waived:
            blocking.append(finding.digest)
            blocked_profiles.add(_profile_for_finding(finding))

    sbom = build_deterministic_sbom(
        subject.candidate_sha, policy.policy_digest, subject.dependency_inventory
    )
    ordered_findings = tuple(
        sorted(findings, key=lambda item: (item.category, item.path, item.line, item.finding_id))
    )
    disposition = GateDisposition.BLOCKED if blocking else GateDisposition.PASS
    shell = SecurityProfileReport(
        candidate_sha=subject.candidate_sha,
        policy_digest=policy.policy_digest,
        disposition=disposition,
        executed_profiles=tuple(policy.required_profiles),
        blocked_profiles=tuple(sorted(blocked_profiles)),
        findings=ordered_findings,
        blocking_finding_digests=tuple(sorted(set(blocking))),
        tool_identities=tuple(sorted(policy.tools, key=lambda item: item.name)),
        advisory_snapshot_digests=admitted_advisories,
        sbom=sbom,
        report_digest="",
    )
    return replace(shell, report_digest=canonical_digest(shell.without_digest()))


def report_evidence_item(
    report: SecurityProfileReport,
    *,
    policy: SecurityGatePolicy,
    subject_digest: str,
    producer: EvidenceProducer,
    tool: EvidenceToolIdentity,
    environment: EnvironmentFingerprint,
    observed_at: str,
    expires_at: str,
    authentication_evidence_digest: str,
    committed_script_digest: str,
) -> EvidenceItem:
    """Represent a verified profile as candidate-review EvidenceBundle input.

    The caller remains responsible for authenticating the returned item against the
    governing EvidenceBundle policy. This function only performs deterministic
    subject/result/count/output binding and refuses a tampered profile report.
    """

    validate_gate_policy(policy)
    if report.policy_digest != policy.policy_digest:
        raise ValueError("security report and evidence policy digests differ")
    if report.executed_profiles != policy.required_profiles:
        raise ValueError("security report did not execute the required policy profiles")
    if report.tool_identities != tuple(sorted(policy.tools, key=lambda item: item.name)):
        raise ValueError("security report tool identities differ from policy")
    if not _DIGEST.fullmatch(subject_digest):
        raise ValueError("evidence subject digest is malformed")
    if report.report_digest != canonical_digest(report.without_digest()):
        raise ValueError("security profile report digest is invalid")
    if not _DIGEST.fullmatch(authentication_evidence_digest):
        raise ValueError("evidence authentication digest is malformed")
    if not _DIGEST.fullmatch(committed_script_digest):
        raise ValueError("committed security script digest is malformed")
    _time(observed_at)
    _time(expires_at)
    executed = len(report.executed_profiles)
    failed = len(report.blocked_profiles)
    passed = executed - failed
    return EvidenceItem(
        evidence_id=f"security-profile:{report.candidate_sha}:{report.report_digest}",
        evidence_class="required_checks",
        stage="candidate_review",
        subject_digest=subject_digest,
        result="PASS" if report.passed else "FAIL",
        producer=producer,
        tool=tool,
        environment=environment,
        invocation=("pmpe", "security-profile", "verify", report.candidate_sha),
        output_digest=report.report_digest,
        observed_at=observed_at,
        retention_class="release+incident",
        authentication_evidence_digest=authentication_evidence_digest,
        attestation_format="DSSE-v1",
        committed_script_digest=committed_script_digest,
        expires_at=expires_at,
        payload_ref=f"security-profile:{report.report_digest}",
        executed_count=executed,
        passed_count=passed,
        failed_count=failed,
        skipped_count=0,
    )
