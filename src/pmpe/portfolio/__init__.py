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
    "BusinessAccuracyVerdict",
    "ClaimGrade",
    "DeepInspection",
    "EvidenceRef",
    "Finding",
    "FixtureRepositorySource",
    "LiveAccessUnavailable",
    "LiveRepositorySource",
    "RecommendationVerdict",
    "RepoRisk",
    "RepoScan",
    "RepositorySource",
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
    "scan_portfolio",
    "scan_repository",
    "classify_slop",
    "select_for_deep_scan",
    "verify_stability",
]
