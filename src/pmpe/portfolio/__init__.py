"""GitHub Portfolio Auditor — a Production Engineering OS use case.

Deterministic, fixture-first repository auditing built entirely on existing
OS mechanisms: ProductDecisionContract (digest-locked via ContractStore),
the evidence ledger, candidate freeze, read-only review guards, and the
drift/trajectory evals. No model SDK calls, no schedulers, no imports from
the archived loop-engineering prototype.
"""

from pmpe.portfolio.contract import AuditorBundle, load_auditor_bundle
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

__all__ = [
    "AISlopVerdict",
    "AuditorBundle",
    "AuditorPolicy",
    "BusinessAccuracyVerdict",
    "EvidenceRef",
    "Finding",
    "RecommendationVerdict",
    "Severity",
    "SlopPolicy",
    "load_auditor_bundle",
    "load_policy",
]
