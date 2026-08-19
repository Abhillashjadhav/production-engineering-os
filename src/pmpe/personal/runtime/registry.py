"""Thread-safe append-only runtime event and evaluation registry."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from pmpe.contracts.canonical import canonical_json_bytes
from pmpe.personal.runtime.models import (
    EvidenceSubject,
    RuntimeEvent,
    RuntimeGovernanceError,
    digest_for,
)


class RegistryIntegrityError(RuntimeGovernanceError):
    """Raised when the append-only chain is unreadable or has been altered."""


class EventRegistry:
    """Append events as canonical JSONL with a verified digest chain.

    The registry serializes appends from parallel local workers. It cannot prevent an
    operator with filesystem access from replacing the file, so every read verifies the
    full chain and fails closed if history was changed.
    """

    _path_locks_guard = threading.Lock()
    _path_locks: dict[str, threading.RLock] = {}

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        lock_key = str(self.path.resolve())
        with self._path_locks_guard:
            self._lock = self._path_locks.setdefault(lock_key, threading.RLock())

    def read(self) -> tuple[RuntimeEvent, ...]:
        with self._lock:
            if not self.path.exists():
                return ()
            try:
                lines = self.path.read_bytes().splitlines()
            except OSError as exc:
                raise RegistryIntegrityError("runtime registry is unreadable") from exc
            events: list[RuntimeEvent] = []
            previous: str | None = None
            for expected_sequence, line in enumerate(lines, start=1):
                if not line:
                    raise RegistryIntegrityError("runtime registry contains an empty record")
                try:
                    raw = json.loads(line)
                    subject_raw = raw["subject"]
                    event = RuntimeEvent(
                        schema_version=raw["schema_version"],
                        sequence=raw["sequence"],
                        event_id=raw["event_id"],
                        event_type=raw["event_type"],
                        occurred_at=raw["occurred_at"],
                        subject=EvidenceSubject(
                            contract_digest=subject_raw["contract_digest"],
                            task_digest=subject_raw["task_digest"],
                            artifact_digest=subject_raw["artifact_digest"],
                        ),
                        payload=raw["payload"],
                        previous_event_digest=raw["previous_event_digest"],
                        event_digest=raw["event_digest"],
                    )
                except (KeyError, TypeError, json.JSONDecodeError, RuntimeGovernanceError) as exc:
                    raise RegistryIntegrityError(
                        "runtime registry contains a malformed record"
                    ) from exc
                if (
                    event.sequence != expected_sequence
                    or event.previous_event_digest != previous
                    or not event.verify()
                ):
                    raise RegistryIntegrityError("runtime registry digest chain is invalid")
                events.append(event)
                previous = event.event_digest
            return tuple(events)

    def append(
        self,
        *,
        event_type: str,
        occurred_at: str,
        subject: EvidenceSubject,
        payload: dict[str, Any],
    ) -> RuntimeEvent:
        if not event_type or not occurred_at or not isinstance(payload, dict):
            raise RuntimeGovernanceError("event type, time, and object payload are required")
        with self._lock:
            existing = self.read()
            sequence = len(existing) + 1
            previous = existing[-1].event_digest if existing else None
            unsigned: dict[str, Any] = {
                "event_id": f"EVENT-{sequence:06d}",
                "event_type": event_type,
                "occurred_at": occurred_at,
                "payload": payload,
                "previous_event_digest": previous,
                "schema_version": "1.0.0",
                "sequence": sequence,
                "subject": subject.as_dict(),
            }
            event = RuntimeEvent(
                schema_version="1.0.0",
                sequence=sequence,
                event_id=str(unsigned["event_id"]),
                event_type=event_type,
                occurred_at=occurred_at,
                subject=subject,
                payload=payload,
                previous_event_digest=previous,
                event_digest=digest_for(unsigned),
            )
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(self.path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
            try:
                record = canonical_json_bytes(event.as_dict()) + b"\n"
                offset = 0
                while offset < len(record):
                    offset += os.write(descriptor, record[offset:])
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            return event

    def append_evaluation(
        self,
        *,
        occurred_at: str,
        subject: EvidenceSubject,
        case_id: str,
        verdict: str,
        score: float,
        failure_class: str | None = None,
    ) -> RuntimeEvent:
        if verdict not in {"PASS", "FAIL"} or not 0.0 <= score <= 1.0:
            raise RuntimeGovernanceError("evaluation verdict or score is outside policy")
        payload: dict[str, Any] = {
            "case_id": case_id,
            "failure_class": failure_class,
            "score": score,
            "verdict": verdict,
        }
        if verdict == "FAIL" and not failure_class:
            raise RuntimeGovernanceError("failed evaluations require a failure class")
        return self.append(
            event_type="evaluation.recorded",
            occurred_at=occurred_at,
            subject=subject,
            payload=payload,
        )

    def append_once(
        self,
        *,
        event_type: str,
        occurred_at: str,
        subject: EvidenceSubject,
        payload: dict[str, Any],
        uniqueness_event_types: tuple[str, ...],
        uniqueness_field: str,
    ) -> RuntimeEvent:
        """Atomically reserve one payload identity within this registry path."""

        unique_value = payload.get(uniqueness_field)
        if not uniqueness_event_types or not isinstance(unique_value, str) or not unique_value:
            raise RuntimeGovernanceError("append-once uniqueness policy is malformed")
        with self._lock:
            if any(
                event.event_type in uniqueness_event_types
                and event.payload.get(uniqueness_field) == unique_value
                for event in self.read()
            ):
                raise RuntimeGovernanceError(
                    f"{uniqueness_field} has already been durably consumed"
                )
            return self.append(
                event_type=event_type,
                occurred_at=occurred_at,
                subject=subject,
                payload=payload,
            )
