"""GitHub Portfolio Auditor — a Production Engineering OS use case.

Deterministic, fixture-first repository auditing built entirely on existing
OS mechanisms: ProductDecisionContract (digest-locked via ContractStore),
the evidence ledger, candidate freeze, read-only review guards, and the
drift/trajectory evals. No model SDK calls, no schedulers, no imports from
the archived loop-engineering prototype.
"""

from pmpe.portfolio.contract import AuditorBundle, load_auditor_bundle
from pmpe.portfolio.datasource import (
    FixtureRepositorySource,
    LiveAccessUnavailable,
    LiveRepositorySource,
    RepositorySource,
)
from pmpe.portfolio.inspection import (
    ClaimGrade,
    DeepInspection,
    inspect_repository,
    inspect_selected,
)
from pmpe.portfolio.models import (
    AISlopVerdict,
    BusinessAccuracyVerdict,
    EvidenceRef,
    Finding,
    RecommendationVerdict,
    Severity,
    SlopPolicy,
)
from pmpe.portfolio.policy import AuditorPolicy, load_policy
from pmpe.portfolio.remediation import (
    MergeDecision,
    RemediationPR,
    SandboxRepo,
    apply_merge,
    decide_merge,
    generate_remediation_prs,
)
from pmpe.portfolio.reporting import (
    BacklogItem,
    RepoReport,
    build_backlog,
    build_repo_report,
    recommend,
    render_dashboard,
    render_scorecard,
)
from pmpe.portfolio.scanner import RepoScan, scan_portfolio, scan_repository
from pmpe.portfolio.selection import (
    RepoRisk,
    SelectionReport,
    Strategy,
    load_strategy,
    rank_risks,
    select_for_deep_scan,
)
from pmpe.portfolio.slop import (
    SlopAssessment,
    StabilityReport,
    classify_slop,
    verify_stability,
)

__all__ = [
    "AISlopVerdict",
    "AuditorBundle",
    "AuditorPolicy",
    "BacklogItem",
    "BusinessAccuracyVerdict",
    "ClaimGrade",
    "DeepInspection",
    "EvidenceRef",
    "Finding",
    "FixtureRepositorySource",
    "LiveAccessUnavailable",
    "LiveRepositorySource",
    "MergeDecision",
    "RecommendationVerdict",
    "RemediationPR",
    "RepoReport",
    "RepoRisk",
    "RepoScan",
    "RepositorySource",
    "SandboxRepo",
    "SelectionReport",
    "Severity",
    "SlopAssessment",
    "StabilityReport",
    "SlopPolicy",
    "Strategy",
    "load_auditor_bundle",
    "load_policy",
    "inspect_repository",
    "inspect_selected",
    "load_strategy",
    "rank_risks",
    "recommend",
    "render_dashboard",
    "render_scorecard",
    "scan_portfolio",
    "scan_repository",
    "apply_merge",
    "build_backlog",
    "build_repo_report",
    "classify_slop",
    "decide_merge",
    "generate_remediation_prs",
    "select_for_deep_scan",
    "verify_stability",
]
