"""Canonical data models for repository intelligence artifacts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from types import MappingProxyType
from typing import Any, cast

from pmpe.contracts.canonical import canonical_digest, canonical_json_bytes

AUDIT_CATEGORIES = (
    "repository_topology",
    "languages_build_ecosystems",
    "architecture_boundaries",
    "apis_data",
    "integrations",
    "tests_quality",
    "delivery_environments",
    "security_privacy",
    "observability_operations",
    "documentation_governance",
    "active_divergent_work",
    "debt_risk",
)


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _plain(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _plain(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


@dataclass(frozen=True)
class ScanConfig:
    """Bounded, deterministic inputs for an exact-commit scan."""

    repository: str
    default_branch: str | None = None
    max_files: int = 20_000
    max_directories: int = 5_000
    max_total_bytes: int = 250_000_000
    max_file_bytes: int = 5_000_000
    max_tree_output_bytes: int = 32_000_000
    max_commands: int = 50_000
    command_timeout_seconds: int = 20
    max_path_depth: int = 64
    include_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str | bytes
    stderr: str | bytes
    timed_out: bool = False


@dataclass(frozen=True)
class EvidenceItem:
    kind: str
    path: str
    file_digest: str
    detector_id: str
    detector_version: str
    location: str = "file"
    confidence: str = "HIGH"
    redaction_status: str = "SANITIZED"


@dataclass(frozen=True)
class InventoryCategory:
    status: str
    items: tuple[EvidenceItem, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class Finding:
    code: str
    category: str
    severity: str
    confidence: str
    explanation: str
    evidence_refs: tuple[str, ...]
    detector_id: str
    detector_version: str
    blocking: bool = False


@dataclass(frozen=True)
class BoundaryCandidate:
    kind: str
    name: str
    evidence_paths: tuple[str, ...]
    confidence: str
    detector_id: str
    detector_version: str


@dataclass(frozen=True)
class AdapterMetadata:
    adapter_id: str
    version: str
    detector_version: str
    file_patterns: tuple[str, ...]
    supported_categories: tuple[str, ...]
    failure_behavior: str = "VISIBLE_PARTIAL_OR_BLOCKED"
    detection_logic: str = "TRACKED_PATH_AND_SAFE_STRUCTURE_ONLY"
    evidence_emitted: str = "DIGEST_BOUND_FILE_EVIDENCE"
    confidence_semantics: str = "HIGH_EXACT_MEDIUM_HEURISTIC_LOW_SIGNAL"


@dataclass(frozen=True)
class CommandProvenance:
    args: tuple[str, ...]
    tool_identity: str
    exit_status: int
    timed_out: bool


@dataclass(frozen=True)
class ToolVersion:
    tool: str
    version: str


@dataclass(frozen=True)
class RepositorySnapshot:
    repository: str
    commit_sha: str
    tree_sha: str
    git_object_format: str
    default_branch: str | None
    default_branch_source: str
    scanner_version: str
    scan_configuration_digest: str
    adapter_set_digest: str
    implementation_digest: str
    tracked_tree_digest: str
    scanned_content_digest: str
    scan_scope: str
    included_paths: tuple[str, ...]
    tooling_digest: str
    tool_versions: tuple[ToolVersion, ...]
    adapters: tuple[AdapterMetadata, ...]
    command_provenance: tuple[CommandProvenance, ...]
    inventory: Mapping[str, InventoryCategory]
    findings: tuple[Finding, ...]
    boundary_candidates: tuple[BoundaryCandidate, ...]
    unsupported_categories: tuple[str, ...]
    disposition: str
    redaction: Mapping[str, Any]
    snapshot_digest: str
    artifact_kind: str = "REPOSITORY_SNAPSHOT"

    def __post_init__(self) -> None:
        object.__setattr__(self, "inventory", _freeze(self.inventory))
        object.__setattr__(self, "redaction", _freeze(self.redaction))

    def as_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], _plain(self))

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.as_dict())

    def digest_is_valid(self) -> bool:
        payload = self.as_dict()
        claimed = str(payload.pop("snapshot_digest", ""))
        return bool(claimed) and claimed == canonical_digest(payload)

    def assessment_reference(self, observation: GovernanceObservation) -> dict[str, str]:
        """Return the narrow evidence seam consumed by later lifecycle work."""

        if not self.digest_is_valid():
            raise ValueError("repository snapshot digest is invalid")
        if not observation.digest_is_valid():
            raise ValueError("governance observation digest is invalid")
        if observation.repository != self.repository:
            raise ValueError("snapshot and governance observation repositories do not match")
        if (
            observation.repository_snapshot_digest != self.snapshot_digest
            or observation.repository_snapshot_commit != self.commit_sha
        ):
            raise ValueError(
                "governance observation is not bound to this exact repository snapshot"
            )
        return {
            "repository_snapshot_digest": self.snapshot_digest,
            "repository_commit": self.commit_sha,
            "governance_observation_id": observation.observation_id,
            "governance_observation_digest": observation.observation_output_digest,
        }


@dataclass(frozen=True)
class LocalState:
    index_dirty: bool
    worktree_dirty: bool
    untracked: bool
    head_sha: str
    git_object_format: str


@dataclass(frozen=True)
class BranchObservation:
    name: str
    sha: str
    ahead: int
    behind: int
    status: str = "OBSERVED"


@dataclass(frozen=True)
class WorktreeObservation:
    path: str
    head_sha: str
    branch: str
    bare: bool
    detached: bool
    locked: bool
    locked_reason: str | None
    prunable: bool
    prunable_reason: str | None


@dataclass(frozen=True)
class RemoteBranchObservation:
    name: str
    sha: str


@dataclass(frozen=True)
class PullRequestObservation:
    number: int
    draft: bool
    head: str
    updated_at: str
    mergeability: str
    stale: bool


@dataclass(frozen=True)
class IssueObservation:
    number: int
    state: str


@dataclass(frozen=True)
class QueryProvenance:
    surface: str
    query: str
    cursor: str | None
    page: int | None
    has_next_page: bool
    result_count: int | None


@dataclass(frozen=True)
class UnknownFact:
    fact: str
    status: str
    reason: str


@dataclass(frozen=True)
class GovernanceObservation:
    observation_id: str
    observed_at: str
    repository: str
    ref: str
    repository_snapshot_digest: str | None
    repository_snapshot_commit: str | None
    local_state: LocalState
    local_branches: tuple[BranchObservation, ...]
    worktrees: tuple[WorktreeObservation, ...]
    command_provenance: tuple[CommandProvenance, ...]
    remote_branches: tuple[RemoteBranchObservation, ...]
    pull_requests: tuple[PullRequestObservation, ...]
    issues: tuple[IssueObservation, ...]
    governance: Mapping[str, Any]
    query_provenance: tuple[QueryProvenance, ...]
    remote_observed_at: str | None
    remote_query_coverage: tuple[str, ...]
    unknowns: tuple[UnknownFact, ...]
    collector_version: str
    collector_implementation_digest: str
    tool_identity: str
    api_query_version: str
    observation_input_digest: str
    observation_output_digest: str
    disposition: str
    redaction: Mapping[str, Any] = field(default_factory=dict)
    artifact_kind: str = "GOVERNANCE_OBSERVATION"

    def __post_init__(self) -> None:
        object.__setattr__(self, "governance", _freeze(self.governance))
        object.__setattr__(self, "redaction", _freeze(self.redaction))

    def as_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], _plain(self))

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.as_dict())

    def digest_is_valid(self) -> bool:
        payload = self.as_dict()
        claimed = str(payload.pop("observation_output_digest", ""))
        return bool(claimed) and claimed == canonical_digest(payload)
