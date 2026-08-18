"""Versioned adapters and gates for plan-bound execution evidence."""

from pmpe.evidence.adapters import (
    EvidenceAdapterRegistry,
    PytestJsonReportAdapter,
    Tap13Adapter,
    default_adapter_registry,
)
from pmpe.evidence.gate import MeaningfulRedGate
from pmpe.evidence.models import (
    EvidenceDecision,
    EvidenceError,
    EvidenceExpectation,
    EvidenceSubmission,
    NodeEvidence,
    NodeExpectation,
    evidence_plan_digest,
)

__all__ = [
    "EvidenceAdapterRegistry",
    "EvidenceDecision",
    "EvidenceError",
    "EvidenceExpectation",
    "EvidenceSubmission",
    "evidence_plan_digest",
    "MeaningfulRedGate",
    "NodeEvidence",
    "NodeExpectation",
    "PytestJsonReportAdapter",
    "Tap13Adapter",
    "default_adapter_registry",
]
