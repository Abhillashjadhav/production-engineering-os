from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pmpe.audit.evidence import (
    EnvironmentFingerprint,
    EvidenceProducer,
)
from pmpe.audit.evidence import (
    ToolIdentity as EvidenceToolIdentity,
)
from pmpe.contracts.digest import canonical_digest
from pmpe.quality.security_profiles import (
    AdvisorySnapshot,
    ArchitectureBoundaryObservation,
    GateDisposition,
    NormalizedSecurityFinding,
    PrivacyEvidence,
    PrivacyIntent,
    SecretAllowlistEntry,
    SecurityGatePolicy,
    SecurityProfileInput,
    ToolIdentity,
    WaiverRecord,
    advisory_authentication_payload,
    build_deterministic_sbom,
    evaluate_security_profile,
    report_evidence_item,
    scan_repository_secrets,
    secret_fingerprint,
    validate_gate_policy,
    waiver_authentication_payload,
)

SHA = "c" * 40
D = "sha256:" + "a" * 64
E = "sha256:" + "b" * 64
NOW = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)


def proof(kind: str, identity: str, authority: str, payload: object) -> str:
    return canonical_digest(
        {
            "test_trust_root": "outside-security-profile",
            "kind": kind,
            "identity": identity,
            "authority": authority,
            "payload": payload,
        }
    )


def authenticate(kind: str):  # type: ignore[no-untyped-def]
    def verifier(identity: str, authority: str, payload: object, evidence: str) -> bool:
        return evidence == proof(kind, identity, authority, payload)

    return verifier


def tool(name: str) -> ToolIdentity:
    return ToolIdentity(name=name, version="1.2.3", ruleset_digest=D)


def policy(**changes: object) -> SecurityGatePolicy:
    base = SecurityGatePolicy(
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
        tools=tuple(
            tool(name)
            for name in (
                "secret-scanner",
                "bandit",
                "pip-audit",
                "license-scanner",
                "sbom-builder",
                "privacy-verifier",
                "boundary-verifier",
            )
        ),
        trusted_advisory_sources={"pypi-advisory-db": D},
        advisory_max_age_seconds={"pypi-advisory-db": 3600},
        trusted_waiver_authorities={"security-owner": D},
        scan_exclusions=(".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache"),
        secret_allowlist=(),
    )
    unsigned = replace(base, **changes)
    payload = unsigned.as_dict()
    payload.pop("policy_digest")
    return replace(unsigned, policy_digest=canonical_digest(payload))


def advisory(*, findings: tuple[NormalizedSecurityFinding, ...] = ()) -> AdvisorySnapshot:
    shell = AdvisorySnapshot(
        source="pypi-advisory-db",
        subject_sha=SHA,
        snapshot_digest=D,
        generated_at="2030-01-01T11:30:00Z",
        fetched_at="2030-01-01T11:40:00Z",
        evaluated_at="2030-01-01T11:50:00Z",
        expires_at="2030-01-01T12:30:00Z",
        authority_digest=D,
        authentication_evidence_digest="",
        findings=findings,
    )
    return replace(
        shell,
        authentication_evidence_digest=proof(
            "advisory",
            shell.source,
            shell.authority_digest,
            advisory_authentication_payload(shell),
        ),
    )


def privacy_intent() -> PrivacyIntent:
    return PrivacyIntent(
        classification="INTERNAL",
        retention_days=30,
        deletion_required=True,
        residency="IN",
        telemetry_allowlist=("run_id", "latency_ms", "outcome"),
    )


def privacy_evidence() -> PrivacyEvidence:
    shell = PrivacyEvidence(
        classification="INTERNAL",
        retention_days=30,
        deletion_test_passed=True,
        residency="IN",
        emitted_telemetry=("run_id", "latency_ms", "outcome"),
        evidence_digest="",
    )
    payload = asdict(shell)
    payload.pop("evidence_digest")
    return replace(shell, evidence_digest=canonical_digest(payload))


def architecture_observation() -> ArchitectureBoundaryObservation:
    shell = ArchitectureBoundaryObservation(
        architecture_pack_digest=D,
        boundary_policy_version="architecture-boundary/v1",
        boundary_policy_digest=D,
        allowed_edges=(("api", "storage"),),
        observed_edges=(("api", "storage"),),
        evidence_digest="",
    )
    payload = asdict(shell)
    payload.pop("evidence_digest")
    return replace(shell, evidence_digest=canonical_digest(payload))


def profile_input(root: Path, **changes: object) -> SecurityProfileInput:
    base = SecurityProfileInput(
        candidate_sha=SHA,
        repository_root=root,
        dependency_inventory=(
            ("jsonschema", "4.25.1", "MIT"),
            ("rfc8785", "0.1.4", "Apache-2.0"),
        ),
        allowed_licenses=("MIT", "Apache-2.0", "BSD-3-Clause"),
        advisory_snapshots=(advisory(),),
        privacy_intent=privacy_intent(),
        privacy_evidence=privacy_evidence(),
        architecture=architecture_observation(),
        waivers=(),
    )
    return replace(base, **changes)


def evaluate(root: Path, *, gate_policy: SecurityGatePolicy | None = None, **changes: object):
    return evaluate_security_profile(
        profile_input(root, **changes),
        gate_policy or policy(),
        advisory_authenticator=authenticate("advisory"),
        waiver_authenticator=authenticate("waiver"),
        trusted_clock=lambda: NOW,
    )


def test_policy_requires_exact_tool_versions_and_every_required_profile() -> None:
    validate_gate_policy(policy())
    ranged = policy(tools=(replace(tool("secret-scanner"), version=">=1.2"),))
    with pytest.raises(ValueError, match="exact tool version"):
        validate_gate_policy(ranged)
    missing = policy(required_profiles=("secret",))
    with pytest.raises(ValueError, match="required profile"):
        validate_gate_policy(missing)


@pytest.mark.parametrize(
    "relative",
    (
        "src/app.py",
        "tests/fixture.txt",
        "evals/case.json",
        "state/run.json",
        ".ignored/run-artifact.txt",
        "requirements.lock",
    ),
)
def test_no_ignore_secret_gate_scans_source_tests_evals_state_ignored_and_lockfiles(
    tmp_path: Path, relative: str
) -> None:
    target = tmp_path / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("service_token = " + "ghp_" + "A" * 36 + "\n")
    (tmp_path / ".gitignore").write_text(".ignored/\nstate/\n")

    report = evaluate(tmp_path)

    assert report.disposition is GateDisposition.BLOCKED
    finding = next(item for item in report.findings if item.category == "SECRET")
    assert finding.path == relative
    assert "ghp_" not in finding.message
    assert "AAAA" not in report.canonical_bytes().decode()


def test_standalone_repository_secret_gate_is_exact_sha_bound(tmp_path: Path) -> None:
    target = tmp_path / "ignored" / "run.json"
    target.parent.mkdir()
    target.write_text("api_key='" + "AKIA" + "A" * 16 + "'\n")

    findings = scan_repository_secrets(tmp_path, candidate_sha=SHA, trusted_clock=lambda: NOW)

    assert len(findings) == 1
    assert findings[0].subject_sha == SHA
    assert findings[0].path == "ignored/run.json"


def test_no_ignore_secret_gate_scans_symlink_payload_without_following_it(tmp_path: Path) -> None:
    target = "ghp_" + "D" * 36
    (tmp_path / "credential-link").symlink_to(target)

    findings = scan_repository_secrets(tmp_path, candidate_sha=SHA, trusted_clock=lambda: NOW)

    assert len(findings) == 1
    assert findings[0].path == "credential-link"


def test_scan_exclusions_cannot_hide_lockfiles_or_broad_product_trees() -> None:
    with pytest.raises(ValueError, match="broad scan exclusion"):
        validate_gate_policy(policy(scan_exclusions=("tests",)))
    with pytest.raises(ValueError, match="lockfile"):
        validate_gate_policy(policy(scan_exclusions=("requirements.lock",)))


def test_synthetic_secret_allowlist_is_exact_reviewed_and_mutation_safe(tmp_path: Path) -> None:
    target = tmp_path / "tests" / "fixtures" / "synthetic-token.txt"
    target.parent.mkdir(parents=True)
    value = "ghp_" + "B" * 36
    target.write_text(f"token={value}\n")
    allow = SecretAllowlistEntry(
        path="tests/fixtures/synthetic-token.txt",
        line=1,
        fingerprint=secret_fingerprint(value),
        justification="Synthetic scanner fixture for issue #70.",
        approved_by="security-owner",
        expires_at="2030-01-02T00:00:00Z",
    )

    assert evaluate(tmp_path, gate_policy=policy(secret_allowlist=(allow,))).passed
    target.write_text("token=" + "ghp_" + "C" * 36 + "\n")
    assert evaluate(tmp_path, gate_policy=policy(secret_allowlist=(allow,))).blocked
    with pytest.raises(ValueError, match="exact file"):
        validate_gate_policy(policy(secret_allowlist=(replace(allow, path="tests/fixtures"),)))


@pytest.mark.parametrize(
    "change",
    (
        {"authentication_evidence_digest": E},
        {"source": "unknown-source"},
        {"generated_at": "not-a-time"},
        {"fetched_at": "2030-01-01T11:00:00Z"},
        {"evaluated_at": "2030-01-01T13:00:00Z"},
        {"expires_at": "2030-01-01T11:59:59Z"},
    ),
)
def test_advisory_snapshot_requires_source_authenticity_order_and_freshness(
    tmp_path: Path, change: dict[str, object]
) -> None:
    invalid = replace(advisory(), **change)
    report = evaluate(tmp_path, advisory_snapshots=(invalid,))
    assert report.blocked
    assert any(item.category == "ADVISORY" for item in report.findings)


def test_advisory_expiry_is_rechecked_after_authentication(tmp_path: Path) -> None:
    expires = NOW + timedelta(seconds=1)
    shell = replace(
        advisory(),
        expires_at=expires.isoformat().replace("+00:00", "Z"),
        authentication_evidence_digest="",
    )
    snapshot = replace(
        shell,
        authentication_evidence_digest=proof(
            "advisory", shell.source, shell.authority_digest, advisory_authentication_payload(shell)
        ),
    )

    class Clock:
        current = NOW

        @classmethod
        def now(cls) -> datetime:
            return cls.current

    def expiring_authenticator(
        identity: str, authority: str, payload: object, evidence: str
    ) -> bool:
        valid = authenticate("advisory")(identity, authority, payload, evidence)
        Clock.current = expires + timedelta(seconds=1)
        return valid

    report = evaluate_security_profile(
        profile_input(tmp_path, advisory_snapshots=(snapshot,)),
        policy(),
        advisory_authenticator=expiring_authenticator,
        waiver_authenticator=authenticate("waiver"),
        trusted_clock=Clock.now,
    )
    assert report.blocked
    assert any("stale" in item.rule_id.lower() for item in report.findings)


def security_finding(severity: str) -> NormalizedSecurityFinding:
    return NormalizedSecurityFinding(
        finding_id=f"SCA-{severity}",
        category="SCA",
        severity=severity,
        rule_id="PYSEC-0001",
        path="requirements.lock",
        line=1,
        message="Known dependency issue (value redacted).",
        subject_sha=SHA,
        evidence_digest=D,
    )


def waiver(finding: NormalizedSecurityFinding, severity: str = "MEDIUM") -> WaiverRecord:
    shell = WaiverRecord(
        finding_digest=finding.digest,
        severity=severity,
        candidate_sha=SHA,
        policy_digest=policy().policy_digest,
        scope_digest=D,
        approved_by="security-owner",
        expires_at="2030-01-01T13:00:00Z",
        authority_digest=D,
        authentication_evidence_digest="",
    )
    return replace(
        shell,
        authentication_evidence_digest=proof(
            "waiver",
            shell.approved_by,
            shell.authority_digest,
            waiver_authentication_payload(shell),
        ),
    )


@pytest.mark.parametrize("severity", ("CRITICAL", "HIGH"))
def test_critical_and_high_findings_are_never_waivable(tmp_path: Path, severity: str) -> None:
    finding = security_finding(severity)
    report = evaluate(
        tmp_path,
        advisory_snapshots=(advisory(findings=(finding,)),),
        waivers=(waiver(finding, severity),),
    )
    assert report.blocked
    assert finding.digest in report.blocking_finding_digests


def test_medium_waiver_requires_exact_scope_policy_expiry_and_authentication(
    tmp_path: Path,
) -> None:
    finding = security_finding("MEDIUM")
    valid = waiver(finding)
    assert evaluate(
        tmp_path,
        advisory_snapshots=(advisory(findings=(finding,)),),
        waivers=(valid,),
    ).passed
    for invalid in (
        replace(valid, candidate_sha="d" * 40),
        replace(valid, policy_digest=E),
        replace(valid, expires_at="2030-01-01T11:59:59Z"),
        replace(valid, authentication_evidence_digest=E),
    ):
        assert evaluate(
            tmp_path,
            advisory_snapshots=(advisory(findings=(finding,)),),
            waivers=(invalid,),
        ).blocked


@pytest.mark.parametrize(
    "evidence",
    (
        None,
        replace(privacy_evidence(), evidence_digest=E),
        replace(privacy_evidence(), deletion_test_passed=False),
        replace(privacy_evidence(), retention_days=31),
        replace(privacy_evidence(), residency="US"),
        replace(privacy_evidence(), emitted_telemetry=("run_id", "email")),
    ),
)
def test_privacy_intent_requires_exact_retention_deletion_residency_and_telemetry_evidence(
    tmp_path: Path, evidence: PrivacyEvidence | None
) -> None:
    report = evaluate(tmp_path, privacy_evidence=evidence)
    assert report.blocked
    assert any(item.category == "PRIVACY" for item in report.findings)


def test_architecture_boundary_drift_or_policy_change_blocks(tmp_path: Path) -> None:
    assert evaluate(
        tmp_path,
        architecture=replace(architecture_observation(), evidence_digest=E),
    ).blocked
    drift = replace(
        architecture_observation(),
        observed_edges=(("api", "storage"), ("frontend", "database")),
    )
    assert evaluate(tmp_path, architecture=drift).blocked
    changed_policy = replace(
        architecture_observation(),
        boundary_policy_version="architecture-boundary/v2",
        boundary_policy_digest=E,
    )
    assert evaluate(tmp_path, architecture=changed_policy).blocked


def test_sbom_is_deterministic_and_bound_to_candidate_and_policy() -> None:
    inventory = (
        ("z-package", "2.0.0", "MIT"),
        ("a-package", "1.0.0", "Apache-2.0"),
    )
    first = build_deterministic_sbom(SHA, D, inventory)
    second = build_deterministic_sbom(SHA, D, tuple(reversed(inventory)))
    assert first == second
    assert first["packages"][0]["name"] == "a-package"
    assert first["candidate_sha"] == SHA
    assert first["policy_digest"] == D
    assert first["sbom_digest"].startswith("sha256:")


def test_missing_required_gate_is_blocking_not_a_pass(tmp_path: Path) -> None:
    report = evaluate(tmp_path, privacy_evidence=None, architecture=None)
    assert report.blocked
    assert set(report.executed_profiles) == set(policy().required_profiles)
    assert {"privacy", "architecture_boundary"} <= set(report.blocked_profiles)


def test_clean_complete_profile_is_digest_bound_and_serializable(tmp_path: Path) -> None:
    report = evaluate(tmp_path)
    assert report.passed
    assert report.disposition is GateDisposition.PASS
    assert report.candidate_sha == SHA
    assert report.policy_digest == policy().policy_digest
    assert report.report_digest.startswith("sha256:")
    assert canonical_digest(report.without_digest()) == report.report_digest
    assert report.canonical_bytes()


def test_report_becomes_exact_subject_required_check_evidence(tmp_path: Path) -> None:
    report = evaluate(tmp_path)
    item = report_evidence_item(
        report,
        policy=policy(),
        subject_digest=E,
        producer=EvidenceProducer("security-runner", D, "AUTOMATED"),
        tool=EvidenceToolIdentity("security-profile", "1.0.0", D, report.policy_digest),
        environment=EnvironmentFingerprint("linux", "amd64", "python-3.11", D, D, D),
        observed_at="2030-01-01T12:00:00Z",
        expires_at="2030-01-01T12:30:00Z",
        authentication_evidence_digest=D,
        committed_script_digest=D,
    )

    assert item.evidence_class == "required_checks"
    assert item.stage == "candidate_review"
    assert item.subject_digest == E
    assert item.output_digest == report.report_digest
    assert item.result == "PASS"
    assert item.executed_count == len(report.executed_profiles)
    assert item.passed_count == len(report.executed_profiles)
    assert item.payload_ref == f"security-profile:{report.report_digest}"
