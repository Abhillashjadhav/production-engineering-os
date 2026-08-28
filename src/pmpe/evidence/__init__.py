"""Versioned adapters and gates for plan-bound execution evidence.

Exports are lazy so importing ``pmpe.evidence.ledger`` does not initialize
unrelated platform-specific gates.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORT_MODULES = {
    "EvidenceAdapterRegistry": "pmpe.evidence.adapters",
    "PytestJsonReportAdapter": "pmpe.evidence.adapters",
    "Tap13Adapter": "pmpe.evidence.adapters",
    "default_adapter_registry": "pmpe.evidence.adapters",
    "MeaningfulRedGate": "pmpe.evidence.gate",
    "ORACLE_ARTIFACT_KIND": "pmpe.evidence.models",
    "EvidenceDecision": "pmpe.evidence.models",
    "EvidenceError": "pmpe.evidence.models",
    "EvidenceExpectation": "pmpe.evidence.models",
    "EvidenceSubmission": "pmpe.evidence.models",
    "NodeEvidence": "pmpe.evidence.models",
    "NodeExpectation": "pmpe.evidence.models",
    "evidence_plan_digest": "pmpe.evidence.models",
    "oracle_artifact_digest": "pmpe.evidence.models",
    "oracle_subject_bindings": "pmpe.evidence.models",
}

__all__ = list(_EXPORT_MODULES)


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(name)
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value
