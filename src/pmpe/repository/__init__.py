"""Deterministic repository intelligence public API."""

from pmpe.repository.adapters import RepositoryAdapter, default_adapters, repository_adapter
from pmpe.repository.governance import (
    GovernanceCollector,
    RecordedObservationIds,
    RecordedRemoteProvider,
    RecordedUtcClock,
    observe_governance,
)
from pmpe.repository.models import AUDIT_CATEGORIES, CommandResult, ScanConfig
from pmpe.repository.scanner import (
    CancellationSignal,
    RepositoryIntelligenceError,
    RepositoryScanner,
    RepositorySecurityError,
    resolve_repository_root,
    scan_repository,
)

__all__ = [
    "AUDIT_CATEGORIES",
    "CancellationSignal",
    "CommandResult",
    "GovernanceCollector",
    "RecordedObservationIds",
    "RecordedRemoteProvider",
    "RecordedUtcClock",
    "RepositoryAdapter",
    "RepositoryIntelligenceError",
    "RepositoryScanner",
    "RepositorySecurityError",
    "ScanConfig",
    "default_adapters",
    "observe_governance",
    "repository_adapter",
    "resolve_repository_root",
    "scan_repository",
]
