"""Deep repository inspection (M4): findings, claim grades, dimension scores.

Everything here is a deterministic pure function of the repository snapshot
and the digest-bound policy — mechanical proxies over observable signals,
no model output, no network. Three locked rules:

- Honesty of grades (PD-PA-03, AC-PA-004): V1 judges business claims from
  repository evidence only. The mechanical grader therefore never emits
  PROVEN (that demands evidence kinds like deployment proof or evaluation
  reports) and never emits CONTRADICTED (absence is not falsehood); an
  unsupported claim grades NOT_PROVEN or INSUFFICIENT_EVIDENCE, and a
  LIKELY grade must carry the policy corroboration floor of independent
  evidence origins.
- Findings carry all seven contract-required fields, validate against the
  finding schema, and never contain a secret value (evidence binds file
  content by sha256 digest, never by excerpt).
- Integrity: the inspection binds the snapshot content digest and re-reads
  the source at the end — a snapshot that mutates mid-inspection fails
  the run loudly rather than producing evidence about unknown content.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from pmpe.contracts.digest import canonical_digest
from pmpe.domain.errors import PmpeError
from pmpe.portfolio.datasource import RepositorySource
from pmpe.portfolio.models import (
    BusinessAccuracyVerdict,
    EvidenceRef,
    Finding,
    Severity,
    must_surface,
)
from pmpe.portfolio.policy import AuditorPolicy
from pmpe.portfolio.scanner import MechanicalClaim, RepoScan

INSPECTOR_VERSION = "pa-inspector-1"

#: Claim categories that V1 mechanical inspection cannot evaluate at all
#: from repository content (external adoption, benchmarks, scale claims).
_UNEVALUABLE_CATEGORIES = frozenset({"metric", "scale", "adoption"})


def _sha(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _snapshot_digest(meta: dict[str, Any], tree: list[str], files: dict[str, str]) -> str:
    return canonical_digest({"metadata": meta, "tree": sorted(tree), "files": files})


@dataclass(frozen=True)
class ClaimGrade:
    """One graded business claim with its reasoning and supporting evidence."""

    claim: MechanicalClaim
    verdict: BusinessAccuracyVerdict
    reasoning: str
    supporting_evidence: tuple[EvidenceRef, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim": self.claim.to_dict(),
            "verdict": self.verdict.value,
            "reasoning": self.reasoning,
            "supporting_evidence": [e.to_dict() for e in self.supporting_evidence],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ClaimGrade:
        return cls(
            claim=MechanicalClaim.from_dict(d["claim"]),
            verdict=BusinessAccuracyVerdict(d["verdict"]),
            reasoning=str(d["reasoning"]),
            supporting_evidence=tuple(
                EvidenceRef.from_dict(e) for e in d.get("supporting_evidence", [])
            ),
        )


@dataclass
class DeepInspection:
    """The complete deep-inspection result for one repository."""

    repository: str
    snapshot_digest: str
    findings: list[Finding]
    claim_grades: list[ClaimGrade]
    dimension_scores: dict[str, int]
    must_surface_finding_ids: tuple[str, ...]
    inspector_version: str = INSPECTOR_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "snapshot_digest": self.snapshot_digest,
            "findings": [f.to_dict() for f in self.findings],
            "claim_grades": [g.to_dict() for g in self.claim_grades],
            "dimension_scores": dict(sorted(self.dimension_scores.items())),
            "must_surface_finding_ids": list(self.must_surface_finding_ids),
            "inspector_version": self.inspector_version,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DeepInspection:
        return cls(
            repository=str(d["repository"]),
            snapshot_digest=str(d["snapshot_digest"]),
            findings=[Finding.from_dict(f) for f in d.get("findings", [])],
            claim_grades=[ClaimGrade.from_dict(g) for g in d.get("claim_grades", [])],
            dimension_scores={str(k): int(v) for k, v in d["dimension_scores"].items()},
            must_surface_finding_ids=tuple(str(x) for x in d.get("must_surface_finding_ids", [])),
            inspector_version=str(d.get("inspector_version", INSPECTOR_VERSION)),
        )


# --- findings ---------------------------------------------------------------


def _secret_findings(repo: str, scan: RepoScan, files: dict[str, str]) -> list[Finding]:
    by_path: dict[str, list[int]] = {}
    for hit in scan.security.secret_hits:
        by_path.setdefault(hit.path, []).append(hit.line)
    findings = []
    for idx, (path, lines) in enumerate(sorted(by_path.items()), start=1):
        evidence = [
            EvidenceRef(
                evidence_id=f"EV-secret-{idx}-file",
                kind="repo_file_line",
                origin="source_code",
                reference=f"{path}#L{','.join(str(ln) for ln in sorted(lines))}",
                content_digest=_sha(files.get(path, "")),
            ),
            EvidenceRef(
                evidence_id=f"EV-secret-{idx}-scan",
                kind="executed_command",
                origin="secret_scanner",
                reference=f"scanner:{scan.scanner_version}:detect_secrets:{path}",
                content_digest=_sha(
                    ";".join(
                        f"{h.rule}@{h.line}" for h in scan.security.secret_hits if h.path == path
                    )
                ),
            ),
        ]
        findings.append(
            Finding(
                finding_id=f"PA-{scan.name}-SEC-{idx:03d}",
                repository=repo,
                dimension="security_dependency_integrity",
                summary=f"secret-shaped credential committed in {path}",
                evidence=evidence,
                confidence=95,
                severity=Severity.BLOCKING,
                affected_capability="security_dependency_integrity",
                reasoning=(
                    f"{len(lines)} secret-shaped value(s) detected in {path} "
                    "(values redacted; rule/path/line recorded). A committed "
                    "credential is an incident regardless of validity: it must "
                    "be rotated and purged from history."
                ),
                remediation_recommendation=(
                    f"Rotate the credential(s), remove them from {path}, purge "
                    "the value from git history, and load secrets from the "
                    "environment or a secret manager."
                ),
            )
        )
    return findings


def _claim_gap_finding(repo: str, scan: RepoScan) -> list[Finding]:
    if not scan.mechanical_claims or scan.tests_ci.has_tests or scan.tests_ci.has_ci:
        return []
    claims = scan.mechanical_claims
    evidence = [
        EvidenceRef(
            evidence_id="EV-claimgap-readme",
            kind="repo_file_line",
            origin="readme",
            reference=";".join(c.location for c in claims[:5]),
            content_digest=_sha("|".join(c.text for c in claims)),
        ),
        EvidenceRef(
            evidence_id="EV-claimgap-signals",
            kind="executed_command",
            origin="scan_signals",
            reference=f"scanner:{scan.scanner_version}:tests_ci_signals",
            content_digest=_sha(str(scan.tests_ci.to_dict())),
        ),
    ]
    return [
        Finding(
            finding_id=f"PA-{scan.name}-GAP-001",
            repository=repo,
            dimension="claim_to_evidence_integrity",
            summary=f"{len(claims)} marketing claim(s) with no tests or CI behind them",
            evidence=evidence,
            confidence=90,
            severity=Severity.HIGH,
            affected_capability="claim_to_evidence_integrity",
            reasoning=(
                "The README makes strong claims while the repository contains "
                "no test files and no CI workflow — nothing in the repository "
                "substantiates the claims."
            ),
            remediation_recommendation=(
                "Either add executable evidence (tests, CI, benchmarks) for "
                "each claim or rewrite the README to state only what the "
                "repository demonstrates."
            ),
        )
    ]


def _dependency_finding(repo: str, scan: RepoScan) -> list[Finding]:
    if not scan.security.dependency_manifests or scan.security.has_lockfile:
        return []
    evidence = [
        EvidenceRef(
            evidence_id="EV-deps-manifests",
            kind="repo_file_line",
            origin="source_code",
            reference=";".join(scan.security.dependency_manifests),
            content_digest=_sha(",".join(scan.security.dependency_manifests)),
        ),
        EvidenceRef(
            evidence_id="EV-deps-signals",
            kind="executed_command",
            origin="scan_signals",
            reference=f"scanner:{scan.scanner_version}:security_signals",
            content_digest=_sha(str(scan.security.to_dict())),
        ),
    ]
    return [
        Finding(
            finding_id=f"PA-{scan.name}-DEP-001",
            repository=repo,
            dimension="security_dependency_integrity",
            summary="dependency manifests without any lockfile",
            evidence=evidence,
            confidence=85,
            severity=Severity.MEDIUM,
            affected_capability="security_dependency_integrity",
            reasoning=(
                "Dependencies are declared but not locked, so builds are not "
                "reproducible and dependency drift is invisible."
            ),
            remediation_recommendation="Commit a lockfile for the declared manifests.",
        )
    ]


# --- claim grading ----------------------------------------------------------


def _support_evidence(scan: RepoScan, files: dict[str, str]) -> list[EvidenceRef]:
    """Independent-origin evidence that operational claims can lean on."""
    evidence: list[EvidenceRef] = []
    tests = [p for p in files if p.startswith(("tests/", "test/"))]
    if scan.tests_ci.has_tests:
        evidence.append(
            EvidenceRef(
                evidence_id="EV-support-tests",
                kind="test",
                origin="test_layout",
                reference=";".join(tests[:5]) or "tests/",
                content_digest=_sha(str(scan.tests_ci.test_file_count)),
            )
        )
    if scan.tests_ci.has_ci:
        evidence.append(
            EvidenceRef(
                evidence_id="EV-support-ci",
                kind="ci_workflow",
                origin="ci_config",
                reference=";".join(scan.tests_ci.ci_files),
                content_digest=_sha(",".join(scan.tests_ci.ci_files)),
            )
        )
    if scan.security.has_lockfile:
        evidence.append(
            EvidenceRef(
                evidence_id="EV-support-lockfile",
                kind="repo_file_line",
                origin="dependency_lockfile",
                reference=";".join(scan.security.lockfile_kinds),
                content_digest=_sha(",".join(scan.security.lockfile_kinds)),
            )
        )
    return evidence


def _grade_claims(scan: RepoScan, files: dict[str, str], policy: AuditorPolicy) -> list[ClaimGrade]:
    support = _support_evidence(scan, files)
    support_origins = {e.origin for e in support}
    grades: list[ClaimGrade] = []
    for claim in scan.mechanical_claims:
        if claim.category in _UNEVALUABLE_CATEGORIES:
            grades.append(
                ClaimGrade(
                    claim=claim,
                    verdict=BusinessAccuracyVerdict.INSUFFICIENT_EVIDENCE,
                    reasoning=(
                        f"a {claim.category} claim cannot be evaluated from "
                        "repository evidence alone (PD-PA-03); no external "
                        "measurement exists in V1, and absence of proof is "
                        "not falsehood"
                    ),
                )
            )
            continue
        if len(support_origins) >= policy.evidence.min_origins_normal:
            grades.append(
                ClaimGrade(
                    claim=claim,
                    verdict=BusinessAccuracyVerdict.LIKELY,
                    reasoning=(
                        "operational discipline is observable from "
                        f"{len(support_origins)} independent origins "
                        f"({', '.join(sorted(support_origins))}); LIKELY is the "
                        "ceiling for repository evidence — PROVEN would demand "
                        "deployment or evaluation artifacts"
                    ),
                    supporting_evidence=tuple(support),
                )
            )
        else:
            grades.append(
                ClaimGrade(
                    claim=claim,
                    verdict=BusinessAccuracyVerdict.NOT_PROVEN,
                    reasoning=(
                        "the repository offers fewer than "
                        f"{policy.evidence.min_origins_normal} independent "
                        "evidence origins for this claim (found: "
                        f"{', '.join(sorted(support_origins)) or 'none'})"
                    ),
                )
            )
    return grades


# --- dimension scores -------------------------------------------------------


def _clamp(value: float) -> int:
    return max(0, min(100, int(round(value))))


def _dimension_scores(
    scan: RepoScan, grades: list[ClaimGrade], policy: AuditorPolicy
) -> dict[str, int]:
    s = scan
    has_secrets = bool(s.security.secret_hits)
    tests_ci = _clamp(20 + 40 * s.tests_ci.has_tests + 40 * s.tests_ci.has_ci)
    security = 100.0
    if has_secrets:
        security = 10.0
    else:
        if s.security.dependency_manifests and not s.security.has_lockfile:
            security -= 25
        if s.security.pinned_dependencies is False:
            security -= 15
        if not s.security.has_security_md:
            security -= 10
    cleanliness = _clamp(
        25 * bool(s.docs.license_name)
        + 20 * s.docs.has_contributing
        + 15 * s.docs.has_changelog
        + 25 * s.readme.has_readme
        + 15 * (s.docs.doc_file_count >= 3)
    )
    usability = _clamp(
        25 * s.readme.has_install_section
        + 25 * s.readme.has_usage_section
        + 10 * (s.readme.code_fence_count >= 1)
        + 25 * (s.packaging.has_pyproject_or_setup or s.packaging.has_package_json)
        + 15 * bool(s.packaging.entrypoints)
    )
    architecture = _clamp(
        20 * s.docs.has_docs_dir
        + 20 * (s.readme.heading_count >= 3)
        + 20 * (s.packaging.has_pyproject_or_setup or s.packaging.has_package_json)
        + 20 * (len(s.languages) > 0)
        + 20 * (not s.freshness.archived)
    )
    reuse = _clamp(
        30 * (s.packaging.has_pyproject_or_setup or s.packaging.has_package_json)
        + 20 * bool(s.packaging.install_commands)
        + 20 * bool(s.packaging.entrypoints)
        + 10 * s.packaging.has_dockerfile
        + 20 * bool(s.docs.license_name)
    )
    technical = _clamp(
        30
        + 20 * s.tests_ci.has_tests
        + 15 * s.tests_ci.has_ci
        + 10 * s.security.has_lockfile
        + 10 * (s.security.pinned_dependencies is True)
        + 15 * ((s.freshness.days_since_pushed or 0) <= 180)
        - 40 * has_secrets
    )
    if grades:
        likely = sum(1 for g in grades if g.verdict is BusinessAccuracyVerdict.LIKELY)
        business = _clamp(100 * likely / len(grades))
        integrity = _clamp(100 - 15 * (len(grades) - likely))
    else:
        business = 100
        integrity = 100
    authority = _clamp((tests_ci + security + cleanliness + usability) / 4)
    return {
        "technical_health": technical,
        "architecture_quality": architecture,
        "tests_ci_evaluations": tests_ci,
        "security_dependency_integrity": _clamp(security),
        "reusability_deployability": reuse,
        "repository_cleanliness": cleanliness,
        "product_usability_packaging": usability,
        "business_product_accuracy": business,
        "claim_to_evidence_integrity": integrity,
        "authority_readiness": authority,
    }


# --- top level --------------------------------------------------------------


def inspect_repository(
    source: RepositorySource, scan: RepoScan, *, policy: AuditorPolicy
) -> DeepInspection:
    """Deep-inspect one repository from its snapshot (read-only, deterministic)."""
    owner, name = scan.owner, scan.name
    repo = f"{owner}/{name}"
    meta = source.metadata(owner, name)
    tree = source.tree(owner, name)
    files = source.files(owner, name)
    digest_before = _snapshot_digest(meta, tree, files)

    findings = (
        _secret_findings(repo, scan, files)
        + _claim_gap_finding(repo, scan)
        + _dependency_finding(repo, scan)
    )
    grades = _grade_claims(scan, files, policy)
    scores = _dimension_scores(scan, grades, policy)
    surfaced = tuple(
        f.finding_id
        for f in findings
        if must_surface(f, high_confidence_floor=policy.scoring.high_confidence_floor)
    )

    digest_after = _snapshot_digest(
        source.metadata(owner, name), source.tree(owner, name), source.files(owner, name)
    )
    if digest_after != digest_before:
        raise PmpeError(
            f"snapshot for {repo} mutated during inspection "
            f"({digest_before} -> {digest_after}) — results discarded; evidence "
            "must bind exactly one snapshot state"
        )

    return DeepInspection(
        repository=repo,
        snapshot_digest=digest_before,
        findings=findings,
        claim_grades=grades,
        dimension_scores=scores,
        must_surface_finding_ids=surfaced,
    )


def inspect_selected(
    source: RepositorySource,
    scans: list[RepoScan],
    selected: list[str],
    *,
    policy: AuditorPolicy,
) -> list[DeepInspection]:
    """Deep-inspect exactly the selected repositories, in selection order."""
    by_name = {f"{s.owner}/{s.name}": s for s in scans}
    missing = [name for name in selected if name not in by_name]
    if missing:
        raise PmpeError("selection names repositories with no broad scan: " + ", ".join(missing))
    return [inspect_repository(source, by_name[name], policy=policy) for name in selected]
