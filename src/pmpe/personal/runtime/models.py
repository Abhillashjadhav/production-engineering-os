"""Digest-bound model primitives for the governed personal runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pmpe.contracts.canonical import canonical_digest


class RuntimeGovernanceError(ValueError):
    """Raised when a runtime request crosses a governance boundary."""


def require_digest(value: str, *, field: str) -> None:
    if not (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    ):
        raise RuntimeGovernanceError(f"{field} must be a sha256 digest")


def require_identifier(value: str, *, field: str) -> None:
    if not (
        isinstance(value, str)
        and 0 < len(value) <= 128
        and value[0].isalnum()
        and all(character.isalnum() or character in "-_.:" for character in value)
    ):
        raise RuntimeGovernanceError(f"{field} is not a safe identifier")


@dataclass(frozen=True)
class EvidenceSubject:
    """The exact governed truth and artifact to which runtime evidence belongs."""

    contract_digest: str
    task_digest: str
    artifact_digest: str

    def __post_init__(self) -> None:
        require_digest(self.contract_digest, field="contract_digest")
        require_digest(self.task_digest, field="task_digest")
        require_digest(self.artifact_digest, field="artifact_digest")

    def as_dict(self) -> dict[str, str]:
        return {
            "artifact_digest": self.artifact_digest,
            "contract_digest": self.contract_digest,
            "task_digest": self.task_digest,
        }


@dataclass(frozen=True)
class RuntimeEvent:
    """One immutable, hash-chained runtime observation."""

    schema_version: str
    sequence: int
    event_id: str
    event_type: str
    occurred_at: str
    subject: EvidenceSubject
    payload: dict[str, Any]
    previous_event_digest: str | None
    event_digest: str

    def unsigned_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at,
            "payload": self.payload,
            "previous_event_digest": self.previous_event_digest,
            "schema_version": self.schema_version,
            "sequence": self.sequence,
            "subject": self.subject.as_dict(),
        }

    def as_dict(self) -> dict[str, Any]:
        return {**self.unsigned_dict(), "event_digest": self.event_digest}

    def verify(self) -> bool:
        return (
            self.schema_version == "1.0.0"
            and type(self.sequence) is int
            and self.sequence > 0
            and self.event_id == f"EVENT-{self.sequence:06d}"
            and isinstance(self.event_type, str)
            and bool(self.event_type)
            and isinstance(self.occurred_at, str)
            and bool(self.occurred_at)
            and isinstance(self.payload, dict)
            and (
                self.previous_event_digest is None
                or (
                    isinstance(self.previous_event_digest, str)
                    and len(self.previous_event_digest) == 71
                )
            )
            and canonical_digest(self.unsigned_dict()) == self.event_digest
        )


def digest_for(value: Any) -> str:
    """Name the intentional digest operation at runtime call sites."""

    return canonical_digest(value)
