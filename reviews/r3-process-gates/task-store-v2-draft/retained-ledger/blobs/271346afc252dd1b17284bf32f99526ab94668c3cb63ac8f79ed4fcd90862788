"""ProductChangeRequest: how engineering hands a product decision back (PD-03/PD-07).

Engineering never edits the contract and never 'fixes' product behaviour; it
records what it found, the options, the consequences, and a recommended technical
default — the decision owner decides, and an approved decision becomes a NEW
contract version that starts a new run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pmpe.domain.errors import ContractViolation
from pmpe.domain.serialize import atomic_write_json, jsonable
from pmpe.telemetry.events import utc_now

_STATUSES = ("OPEN", "APPROVED", "REJECTED")


@dataclass
class ProductChangeRequest:
    request_id: str
    source_contract_id: str
    source_contract_version: int
    affected_requirement_ids: list[str]
    engineering_finding: str
    reason: str  # why implementation cannot proceed safely
    options: list[str]
    engineering_consequences: str
    recommended_technical_default: str
    decision_owner: str
    status: str = "OPEN"
    resulting_contract_version: int | None = None
    created_at: str = ""
    decided_at: str = ""
    _extra: dict[str, str] = field(default_factory=dict, repr=False)


class ChangeRequestStore:
    def __init__(self, run_dir: Path) -> None:
        self.root = Path(run_dir) / "change_requests"
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, request_id: str) -> Path:
        return self.root / f"{request_id}.json"

    def _next_id(self) -> str:
        highest = 0
        for path in self.root.glob("PCR-*.json"):
            suffix = path.stem.partition("-")[2]
            if suffix.isdigit():
                highest = max(highest, int(suffix))
        return f"PCR-{highest + 1:03d}"

    def create(
        self,
        *,
        source_contract_id: str,
        source_contract_version: int,
        affected_requirement_ids: list[str],
        engineering_finding: str,
        reason: str,
        options: list[str],
        engineering_consequences: str,
        recommended_technical_default: str,
        decision_owner: str,
    ) -> ProductChangeRequest:
        pcr = ProductChangeRequest(
            request_id=self._next_id(),
            source_contract_id=source_contract_id,
            source_contract_version=source_contract_version,
            affected_requirement_ids=affected_requirement_ids,
            engineering_finding=engineering_finding,
            reason=reason,
            options=options,
            engineering_consequences=engineering_consequences,
            recommended_technical_default=recommended_technical_default,
            decision_owner=decision_owner,
            created_at=utc_now(),
        )
        payload = jsonable(pcr)
        payload.pop("_extra", None)
        atomic_write_json(self._path(pcr.request_id), payload)
        return pcr

    def decide(
        self, request_id: str, *, status: str, resulting_contract_version: int | None = None
    ) -> ProductChangeRequest:
        if status not in _STATUSES:
            raise ContractViolation(f"invalid change-request status '{status}'")
        pcr = self.get(request_id)
        pcr.status = status
        pcr.decided_at = utc_now()
        if status == "APPROVED":
            if resulting_contract_version is None:
                raise ContractViolation(
                    "an APPROVED change request must name the resulting contract version"
                )
            pcr.resulting_contract_version = resulting_contract_version
        payload = jsonable(pcr)
        payload.pop("_extra", None)
        atomic_write_json(self._path(request_id), payload)
        return pcr

    def get(self, request_id: str) -> ProductChangeRequest:
        path = self._path(request_id)
        if not path.exists():
            raise ContractViolation(f"unknown change request '{request_id}'")
        return _from_dict(json.loads(path.read_text()))

    def list(self) -> list[ProductChangeRequest]:
        return [_from_dict(json.loads(p.read_text())) for p in sorted(self.root.glob("PCR-*.json"))]


def _from_dict(raw: dict[str, Any]) -> ProductChangeRequest:
    version = raw.get("resulting_contract_version")
    return ProductChangeRequest(
        request_id=str(raw["request_id"]),
        source_contract_id=str(raw["source_contract_id"]),
        source_contract_version=int(raw["source_contract_version"]),
        affected_requirement_ids=list(raw.get("affected_requirement_ids", [])),
        engineering_finding=str(raw["engineering_finding"]),
        reason=str(raw["reason"]),
        options=list(raw.get("options", [])),
        engineering_consequences=str(raw["engineering_consequences"]),
        recommended_technical_default=str(raw["recommended_technical_default"]),
        decision_owner=str(raw["decision_owner"]),
        status=str(raw.get("status", "OPEN")),
        resulting_contract_version=int(version) if version is not None else None,
        created_at=str(raw.get("created_at", "")),
        decided_at=str(raw.get("decided_at", "")),
    )
