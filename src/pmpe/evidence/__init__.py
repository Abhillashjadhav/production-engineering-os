"""Versioned adapters and gates for plan-bound execution evidence."""

from pmpe.evidence.adapters import (
    EvidenceAdapterRegistry,
    PytestJsonReportAdapter,
    Tap13Adapter,
    default_adapter_registry,
)
from pmpe.evidence.gate import MeaningfulRedGate
from pmpe.evidence.models import (
    ORACLE_ARTIFACT_KIND,
    EvidenceDecision,
    EvidenceError,
    EvidenceExpectation,
    EvidenceSubmission,
    NodeEvidence,
    NodeExpectation,
    evidence_plan_digest,
    oracle_artifact_digest,
    oracle_subject_bindings,
)

__all__ = [
    "EvidenceAdapterRegistry",
    "EvidenceDecision",
    "EvidenceError",
    "EvidenceExpectation",
    "EvidenceSubmission",
    "evidence_plan_digest",
    "oracle_artifact_digest",
    "oracle_subject_bindings",
    "MeaningfulRedGate",
    "NodeEvidence",
    "NodeExpectation",
    "ORACLE_ARTIFACT_KIND",
    "PytestJsonReportAdapter",
    "Tap13Adapter",
    "default_adapter_registry",
]
