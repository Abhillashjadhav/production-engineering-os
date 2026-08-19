"""Approval-gated calendar adapter with a deterministic local connector."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Protocol

from pmpe.personal.runtime.models import (
    EvidenceSubject,
    RuntimeGovernanceError,
    digest_for,
    require_digest,
    require_identifier,
)
from pmpe.personal.runtime.registry import EventRegistry


class CalendarConnector(Protocol):
    """Provider seam; implementations may read and apply one exact mutation."""

    def snapshot(self) -> tuple[dict[str, Any], ...]: ...

    def apply_update(self, event_id: str, changes: dict[str, Any]) -> None: ...


@dataclass(frozen=True)
class CalendarMutation:
    event_id: str
    changes: dict[str, Any]
    expected_calendar_digest: str
    payload_digest: str

    @classmethod
    def create(
        cls,
        *,
        event_id: str,
        changes: dict[str, Any],
        expected_calendar_digest: str,
    ) -> CalendarMutation:
        require_identifier(event_id, field="event_id")
        if not changes or not set(changes) <= {"start", "end", "title"}:
            raise RuntimeGovernanceError("calendar changes exceed the update allowlist")
        if any(not isinstance(value, str) or not value for value in changes.values()):
            raise RuntimeGovernanceError("calendar changes must be non-empty strings")
        require_digest(expected_calendar_digest, field="expected_calendar_digest")
        payload = {
            "changes": changes,
            "event_id": event_id,
            "expected_calendar_digest": expected_calendar_digest,
        }
        return cls(event_id, deepcopy(changes), expected_calendar_digest, digest_for(payload))

    def approval_payload(self) -> dict[str, Any]:
        return {
            "action_type": "calendar.update",
            "changes": self.changes,
            "event_id": self.event_id,
            "expected_calendar_digest": self.expected_calendar_digest,
            "payload_digest": self.payload_digest,
        }

    def verify(self) -> bool:
        payload = {
            "changes": self.changes,
            "event_id": self.event_id,
            "expected_calendar_digest": self.expected_calendar_digest,
        }
        return digest_for(payload) == self.payload_digest


@dataclass(frozen=True)
class CalendarApproval:
    approval_id: str
    action_type: str
    payload_digest: str
    approver: str
    approved_at: str

    def __post_init__(self) -> None:
        require_identifier(self.approval_id, field="approval_id")
        require_identifier(self.approver, field="approver")
        require_digest(self.payload_digest, field="payload_digest")
        if self.action_type != "calendar.update" or not self.approved_at:
            raise RuntimeGovernanceError("calendar approval is malformed")


class FakeCalendarConnector:
    """In-memory deterministic fake; it performs no external writes."""

    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._events = deepcopy(events)
        self.write_count = 0

    def snapshot(self) -> tuple[dict[str, Any], ...]:
        return tuple(deepcopy(sorted(self._events, key=lambda item: item["event_id"])))

    def apply_update(self, event_id: str, changes: dict[str, Any]) -> None:
        for event in self._events:
            if event.get("event_id") == event_id:
                event.update(deepcopy(changes))
                self.write_count += 1
                return
        raise RuntimeGovernanceError("approved calendar target no longer exists")


class GovernedCalendarAdapter:
    """Read freely, but mutate only the exact approved payload and snapshot."""

    def __init__(self, connector: CalendarConnector, registry: EventRegistry) -> None:
        self.connector = connector
        self.registry = registry

    def _consumed_approval_ids(self) -> set[str]:
        return {
            str(event.payload["approval_id"])
            for event in self.registry.read()
            if event.event_type in {"calendar.update_started", "calendar.update_applied"}
            and isinstance(event.payload.get("approval_id"), str)
        }

    def snapshot(self) -> tuple[tuple[dict[str, Any], ...], str]:
        events = self.connector.snapshot()
        return events, digest_for({"events": list(events)})

    def propose_update(
        self,
        *,
        event_id: str,
        changes: dict[str, Any],
    ) -> CalendarMutation:
        events, snapshot_digest = self.snapshot()
        if event_id not in {str(event.get("event_id")) for event in events}:
            raise RuntimeGovernanceError("calendar proposal target does not exist")
        return CalendarMutation.create(
            event_id=event_id,
            changes=changes,
            expected_calendar_digest=snapshot_digest,
        )

    def apply_approved(
        self,
        mutation: CalendarMutation,
        approval: CalendarApproval,
        *,
        subject: EvidenceSubject,
        occurred_at: str,
    ) -> str:
        _events, current_digest = self.snapshot()
        if approval.approval_id in self._consumed_approval_ids():
            raise RuntimeGovernanceError("calendar approval has already been consumed")
        if not mutation.verify():
            raise RuntimeGovernanceError("calendar mutation changed after approval was prepared")
        if approval.payload_digest != mutation.payload_digest:
            raise RuntimeGovernanceError("calendar approval does not match the exact payload")
        if current_digest != mutation.expected_calendar_digest:
            raise RuntimeGovernanceError("calendar changed after approval payload was prepared")
        self.registry.append(
            event_type="calendar.update_started",
            occurred_at=occurred_at,
            subject=subject,
            payload={
                "approval_id": approval.approval_id,
                "event_id": mutation.event_id,
                "payload_digest": mutation.payload_digest,
                "pre_calendar_digest": current_digest,
            },
        )
        self.connector.apply_update(mutation.event_id, mutation.changes)
        _updated, updated_digest = self.snapshot()
        try:
            self.registry.append(
                event_type="calendar.update_applied",
                occurred_at=occurred_at,
                subject=subject,
                payload={
                    "approval_id": approval.approval_id,
                    "approver": approval.approver,
                    "payload_digest": mutation.payload_digest,
                    "post_calendar_digest": updated_digest,
                },
            )
        except Exception as exc:
            raise RuntimeGovernanceError(
                "calendar mutation is indeterminate after audit completion failed; "
                "reconcile from calendar.update_started"
            ) from exc
        return updated_digest
