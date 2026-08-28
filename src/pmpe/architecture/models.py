"""Immutable, digest-bound architecture compilation artifacts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, cast

from pmpe.contracts.canonical import canonical_digest, canonical_json_bytes

ARCHITECTURE_PACK_VERSION = "1.0.0"
ARCHITECTURE_PLANES = (
    "CONTROL",
    "EXECUTION",
    "EVIDENCE",
    "SECURITY",
    "DEPLOYMENT",
    "OBSERVABILITY",
)


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(child) for key, child in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(child) for child in value)
    return value


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(child) for child in value]
    return value


class ArchitectureDisposition(StrEnum):
    ADMITTED = "ADMITTED"
    PRODUCT_INPUT_REQUIRED = "PRODUCT_INPUT_REQUIRED"
    ERROR = "ERROR"


@dataclass(frozen=True)
class ArchitectureDiagnostic:
    rule_id: str
    disposition: ArchitectureDisposition
    field_path: str
    owner: str
    explanation: str
    next_action: str

    def as_dict(self) -> dict[str, str]:
        result = asdict(self)
        result["disposition"] = self.disposition.value
        return cast(dict[str, str], result)


@dataclass(frozen=True)
class ArchitecturePack:
    schema_version: str
    compiler_version: str
    pack_id: str
    contract_digest: str
    repository_snapshot_digest: str
    repository_commit: str
    governance_observation_digest: str
    disposition: str
    repository_boundary_evidence: tuple[Mapping[str, Any], ...]
    components: tuple[Mapping[str, Any], ...]
    data_architecture: tuple[Mapping[str, Any], ...]
    api_architecture: tuple[Mapping[str, Any], ...]
    integration_architecture: tuple[Mapping[str, Any], ...]
    security_boundaries: tuple[Mapping[str, Any], ...]
    data_flows: tuple[Mapping[str, Any], ...]
    deployment: Mapping[str, Any]
    observability: Mapping[str, Any]
    rollback: Mapping[str, Any]
    adrs: tuple[Mapping[str, Any], ...]
    threat_model: Mapping[str, Any]
    approval_requests: tuple[Mapping[str, Any], ...]
    pack_digest: str
    artifact_kind: str = "ARCHITECTURE_PACK"

    def __post_init__(self) -> None:
        for name in (
            "components",
            "repository_boundary_evidence",
            "data_architecture",
            "api_architecture",
            "integration_architecture",
            "security_boundaries",
            "data_flows",
            "adrs",
            "approval_requests",
        ):
            object.__setattr__(self, name, _freeze(getattr(self, name)))
        for name in ("deployment", "observability", "rollback", "threat_model"):
            object.__setattr__(self, name, _freeze(getattr(self, name)))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ArchitecturePack:
        return cls(
            schema_version=str(value["schema_version"]),
            compiler_version=str(value["compiler_version"]),
            pack_id=str(value["pack_id"]),
            contract_digest=str(value["contract_digest"]),
            repository_snapshot_digest=str(value["repository_snapshot_digest"]),
            repository_commit=str(value["repository_commit"]),
            governance_observation_digest=str(value["governance_observation_digest"]),
            disposition=str(value["disposition"]),
            repository_boundary_evidence=tuple(value["repository_boundary_evidence"]),
            components=tuple(value["components"]),
            data_architecture=tuple(value["data_architecture"]),
            api_architecture=tuple(value["api_architecture"]),
            integration_architecture=tuple(value["integration_architecture"]),
            security_boundaries=tuple(value["security_boundaries"]),
            data_flows=tuple(value["data_flows"]),
            deployment=value["deployment"],
            observability=value["observability"],
            rollback=value["rollback"],
            adrs=tuple(value["adrs"]),
            threat_model=value["threat_model"],
            approval_requests=tuple(value["approval_requests"]),
            pack_digest=str(value["pack_digest"]),
            artifact_kind=str(value.get("artifact_kind", "ARCHITECTURE_PACK")),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "adrs": _plain(self.adrs),
            "api_architecture": _plain(self.api_architecture),
            "approval_requests": _plain(self.approval_requests),
            "artifact_kind": self.artifact_kind,
            "compiler_version": self.compiler_version,
            "components": _plain(self.components),
            "contract_digest": self.contract_digest,
            "data_architecture": _plain(self.data_architecture),
            "data_flows": _plain(self.data_flows),
            "deployment": _plain(self.deployment),
            "disposition": self.disposition,
            "governance_observation_digest": self.governance_observation_digest,
            "integration_architecture": _plain(self.integration_architecture),
            "observability": _plain(self.observability),
            "pack_digest": self.pack_digest,
            "pack_id": self.pack_id,
            "repository_commit": self.repository_commit,
            "repository_boundary_evidence": _plain(self.repository_boundary_evidence),
            "repository_snapshot_digest": self.repository_snapshot_digest,
            "rollback": _plain(self.rollback),
            "schema_version": self.schema_version,
            "security_boundaries": _plain(self.security_boundaries),
            "threat_model": _plain(self.threat_model),
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.as_dict())

    def digest_is_valid(self) -> bool:
        payload = self.as_dict()
        claimed = str(payload.pop("pack_digest", ""))
        return bool(claimed) and claimed == canonical_digest(payload)

    def boundary_contract(self) -> dict[str, Any]:
        """Return the narrow, digest-bound boundary input for later enforcement."""

        if not self.digest_is_valid() or self.disposition != ArchitectureDisposition.ADMITTED:
            raise ValueError("only a digest-valid admitted ArchitecturePack defines boundaries")
        return {
            "architecture_pack_digest": self.pack_digest,
            "components": [
                {
                    "component_id": item["id"],
                    "repository_boundaries": list(item["repository_boundaries"]),
                }
                for item in self.components
            ],
            "data_flows": _plain(self.data_flows),
            "security_boundaries": _plain(self.security_boundaries),
        }


@dataclass(frozen=True)
class ArchitectureCompilationResult:
    compiler_version: str
    disposition: ArchitectureDisposition
    input_digest: str
    diagnostics: tuple[ArchitectureDiagnostic, ...]
    pack: ArchitecturePack | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "compiler_version": self.compiler_version,
            "diagnostics": [item.as_dict() for item in self.diagnostics],
            "disposition": self.disposition.value,
            "input_digest": self.input_digest,
            "pack": self.pack.as_dict() if self.pack else None,
        }
