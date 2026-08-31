"""Bounded retention enforcement for explicitly selected data roots."""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import uuid
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pmpe.domain.serialize import atomic_write_json

_TOMBSTONE_PREFIX = ".retention-delete-"
DEFAULT_RETENTION_DAYS = 30
MAX_RETENTION_DAYS = 365_000
_RUN_STATE_TERMINAL_OUTCOMES = frozenset({"blocked", "failed", "no_merge", "success"})
_RUN_STATE_RETENTION_FIELDS = frozenset(
    {
        "completed_at",
        "retention_days",
        "retention_policy_digest",
        "retention_record_digest",
    }
)


def _canonical_digest(value: object) -> str:
    # Import lazily: telemetry imports retention during contracts package startup.
    from pmpe.contracts.digest import canonical_digest

    return canonical_digest(value)


def validate_retention_run_directory(run_dir: Path) -> Path:
    """Reserve the controller's tombstone namespace from active run creation."""

    path = Path(run_dir)
    if path.name.startswith(_TOMBSTONE_PREFIX):
        raise ValueError("run directory uses the reserved retention tombstone prefix")
    return path


@dataclass(frozen=True)
class RetentionResult:
    deleted: tuple[str, ...]
    retained: tuple[str, ...]


@dataclass(frozen=True)
class _AuthenticatedRetention:
    retention_days: int
    completed_at: datetime


def validate_retention_days(retention_days: int) -> int:
    """Validate one immutable, run-bound retention policy."""

    if isinstance(retention_days, bool) or not isinstance(retention_days, int):
        raise ValueError("retention days must be an integer")
    if retention_days < 0:
        raise ValueError("retention days cannot be negative")
    if retention_days > MAX_RETENTION_DAYS:
        raise ValueError(f"retention days cannot exceed {MAX_RETENTION_DAYS}")
    return retention_days


def retention_policy_digest(retention_days: int) -> str:
    """Bind one validated retention duration into durable evidence."""

    return _canonical_digest({"retention_days": validate_retention_days(retention_days)})


def terminal_retention_digest(retention_days: int, *, stage: str) -> str:
    """Bind a terminal state and its immutable retention duration together."""

    return _canonical_digest(
        {
            "retention_days": validate_retention_days(retention_days),
            "stage": stage,
        }
    )


def run_state_retention_digest(
    *,
    run_id: str,
    spec_digest: str,
    created_at: str,
    outcome: str,
    completed_at: str,
    retention_days: int,
) -> str:
    """Authenticate the immutable retention subject of one legacy run state."""

    return _canonical_digest(
        {
            "completed_at": completed_at,
            "created_at": created_at,
            "outcome": outcome,
            "retention_days": validate_retention_days(retention_days),
            "run_id": run_id,
            "schema_version": "run-state-retention/v1",
            "spec_digest": spec_digest,
        }
    )


def purge_retained_runs(
    root: Path,
    *,
    trusted_clock: Callable[[], datetime] | None = None,
    exclude_run_dir: Path | None = None,
) -> RetentionResult:
    """Run one scheduler-safe retention sweep without creating another run."""

    clock = trusted_clock or (lambda: datetime.now(UTC))
    return RetentionController().purge(
        root,
        now=clock(),
        exclude_run_dir=exclude_run_dir,
    )


class RetentionController:
    """Delete terminal runs according to each run's own persisted policy."""

    def purge(
        self,
        root: Path,
        *,
        now: datetime,
        exclude_run_dir: Path | None = None,
    ) -> RetentionResult:
        root = root.resolve()
        if not root.is_dir():
            raise ValueError("retention root is unavailable")
        if now.tzinfo is None:
            raise ValueError("retention clock must carry a timezone")
        excluded: Path | None = None
        if exclude_run_dir is not None:
            excluded = Path(exclude_run_dir).resolve()
            if excluded.parent != root:
                raise ValueError("excluded retention run must be a direct child of the root")
        root_lock_path = root / ".retention.lock"
        with root_lock_path.open("a+") as root_lock:
            fcntl.flock(root_lock.fileno(), fcntl.LOCK_EX)
            try:
                return self._purge_locked(
                    root,
                    now=now.astimezone(UTC),
                    excluded=excluded,
                )
            finally:
                fcntl.flock(root_lock.fileno(), fcntl.LOCK_UN)

    def _purge_locked(
        self,
        root: Path,
        *,
        now: datetime,
        excluded: Path | None,
    ) -> RetentionResult:
        deleted: list[str] = []
        retained: list[str] = []
        for run_dir in sorted(root.iterdir()):
            if run_dir.is_symlink() or not run_dir.is_dir():
                continue
            if excluded is not None and run_dir.resolve() == excluded:
                retained.append(run_dir.name)
                continue
            if run_dir.name.startswith(_TOMBSTONE_PREFIX):
                with suppress(FileNotFoundError):
                    shutil.rmtree(run_dir)
                continue
            marker = self._completion_marker(run_dir)
            if marker is None:
                retained.append(run_dir.name)
                continue
            marker_path, policy_path, lock_path = marker
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            tombstone: Path | None = None
            with lock_path.open("a+") as lock:
                try:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    retained.append(run_dir.name)
                    continue
                try:
                    retention = self._authenticated_retention(
                        marker_path,
                        policy_path,
                    )
                    if retention is None or retention.completed_at > now - timedelta(
                        days=retention.retention_days
                    ):
                        retained.append(run_dir.name)
                        continue
                    tombstone = root / (f"{_TOMBSTONE_PREFIX}{run_dir.name}-{uuid.uuid4().hex}")
                    os.replace(run_dir, tombstone)
                finally:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            assert tombstone is not None
            with suppress(FileNotFoundError):
                shutil.rmtree(tombstone)
            deleted.append(run_dir.name)
        return RetentionResult(deleted=tuple(deleted), retained=tuple(retained))

    @staticmethod
    def _completion_marker(run_dir: Path) -> tuple[Path, Path, Path] | None:
        lifecycle = run_dir / "lifecycle-events.jsonl"
        if lifecycle.is_file():
            return (
                lifecycle,
                run_dir / "lifecycle-metadata.json",
                run_dir / "lifecycle.lock",
            )
        engineering = run_dir / "run-state.json"
        if engineering.is_file():
            return engineering, engineering, run_dir / "ledger.lock"
        legacy = run_dir / "state.json"
        if legacy.is_file():
            return legacy, legacy, run_dir / "state.lock"
        return None

    @classmethod
    def _authenticated_retention(
        cls,
        marker_path: Path,
        policy_path: Path,
    ) -> _AuthenticatedRetention | None:
        if marker_path.name == "lifecycle-events.jsonl":
            return cls._authenticated_lifecycle_retention(marker_path, policy_path)
        if marker_path.name == "run-state.json":
            return cls._authenticated_engineering_retention(marker_path)
        return cls._authenticated_run_state_retention(marker_path)

    @classmethod
    def _authenticated_run_state_retention(cls, state_path: Path) -> _AuthenticatedRetention | None:
        state = cls._read_record(state_path)
        state = cls._migrate_legacy_run_state_retention(state_path, state)
        retention_days = cls._validated_retention_days(state)
        run_id = state.get("run_id")
        spec_digest = state.get("spec_digest")
        created_at = state.get("created_at")
        outcome = state.get("outcome")
        completed_at_value = state.get("completed_at")
        if (
            not state
            or "retention_days" not in state
            or retention_days is None
            or not isinstance(run_id, str)
            or not run_id
            or not isinstance(spec_digest, str)
            or not spec_digest
            or not isinstance(created_at, str)
            or not created_at
            or outcome not in _RUN_STATE_TERMINAL_OUTCOMES
            or not isinstance(completed_at_value, str)
            or not completed_at_value
            or state.get("retention_policy_digest") != retention_policy_digest(retention_days)
            or state.get("retention_record_digest")
            != run_state_retention_digest(
                run_id=run_id,
                spec_digest=spec_digest,
                created_at=created_at,
                outcome=outcome,
                completed_at=completed_at_value,
                retention_days=retention_days,
            )
        ):
            return None
        completed_at = cls._authenticated_timestamp(completed_at_value)
        if completed_at is None:
            return None
        return _AuthenticatedRetention(retention_days, completed_at)

    @classmethod
    def _migrate_legacy_run_state_retention(
        cls,
        state_path: Path,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        """Durably bind the historical default to a valid pre-retention terminal state."""

        if not state or any(field in state for field in _RUN_STATE_RETENTION_FIELDS):
            return state
        completed_at = cls._legacy_run_state_completion(state)
        run_id = state.get("run_id")
        spec_digest = state.get("spec_digest")
        created_at = state.get("created_at")
        outcome = state.get("outcome")
        if (
            completed_at is None
            or not isinstance(run_id, str)
            or not run_id
            or not isinstance(spec_digest, str)
            or not spec_digest
            or not isinstance(created_at, str)
            or not created_at
            or outcome not in _RUN_STATE_TERMINAL_OUTCOMES
        ):
            return state
        retention_days = DEFAULT_RETENTION_DAYS
        migrated = {
            **state,
            "retention_days": retention_days,
            "retention_policy_digest": retention_policy_digest(retention_days),
            "completed_at": completed_at,
            "retention_record_digest": run_state_retention_digest(
                run_id=run_id,
                spec_digest=spec_digest,
                created_at=created_at,
                outcome=outcome,
                completed_at=completed_at,
                retention_days=retention_days,
            ),
        }
        atomic_write_json(state_path, migrated)
        return migrated

    @classmethod
    def _legacy_run_state_completion(cls, state: dict[str, Any]) -> str | None:
        created_at = cls._authenticated_timestamp(state.get("created_at"))
        outcome = state.get("outcome")
        steps = state.get("steps")
        if (
            created_at is None
            or outcome not in _RUN_STATE_TERMINAL_OUTCOMES
            or not isinstance(steps, dict)
            or not steps
        ):
            return None
        terminal_statuses = {"blocked", "done", "failed", "skipped"}
        statuses: list[str] = []
        finished_at: list[datetime] = []
        for step in steps.values():
            if not isinstance(step, dict) or not isinstance(step.get("status"), str):
                return None
            status = step["status"]
            statuses.append(status)
            if status == "running":
                return None
            if status not in terminal_statuses:
                continue
            completed = cls._authenticated_timestamp(step.get("finished_at"))
            if completed is None:
                return None
            finished_at.append(completed)
        if (
            not finished_at
            or outcome == "blocked"
            and "blocked" not in statuses
            or outcome == "failed"
            and "failed" not in statuses
            or outcome in {"no_merge", "success"}
            and any(status not in terminal_statuses for status in statuses)
        ):
            return None
        completion = max(finished_at)
        if completion < created_at:
            return None
        return completion.isoformat()

    @classmethod
    def _authenticated_lifecycle_retention(
        cls,
        ledger_path: Path,
        metadata_path: Path,
    ) -> _AuthenticatedRetention | None:
        metadata = cls._read_record(metadata_path)
        events = cls._read_records(ledger_path)
        if not metadata or not events:
            return None
        previous = ""
        for sequence, event in enumerate(events, start=1):
            supplied = event.get("event_digest")
            body = {key: value for key, value in event.items() if key != "event_digest"}
            if (
                event.get("sequence") != sequence
                or event.get("previous_digest") != previous
                or not isinstance(supplied, str)
                or _canonical_digest(body) != supplied
            ):
                return None
            previous = supplied
        initial = events[0]
        completion = next(
            (
                event
                for event in reversed(events)
                if event.get("kind") == "COMPLETION_CLAIMED"
                and event.get("outcome") == "APPLIED"
                and event.get("target") == "COMPLETED"
            ),
            None,
        )
        if completion is None:
            return None
        completion_index = events.index(completion)
        if any(
            event.get("kind") != "TRANSITION" or event.get("outcome") != "DENIED"
            for event in events[completion_index + 1 :]
        ):
            return None
        evidence_refs = initial.get("evidence_refs")
        if (
            initial.get("kind") != "STATE_CREATED"
            or not isinstance(evidence_refs, dict)
            or evidence_refs.get("metadata_digest") != _canonical_digest(metadata)
        ):
            return None
        retention_days = cls._validated_retention_days(metadata)
        completed_at = cls._authenticated_timestamp(completion.get("observed_at"))
        if retention_days is None or completed_at is None:
            return None
        return _AuthenticatedRetention(retention_days, completed_at)

    @classmethod
    def _authenticated_engineering_retention(
        cls, state_path: Path
    ) -> _AuthenticatedRetention | None:
        state = cls._read_record(state_path)
        events = cls._read_records(state_path.parent / "ledger.jsonl")
        if not state or not events or state.get("stage") != "complete":
            return None
        retention_days = cls._validated_retention_days(state)
        run_id = state.get("run_id")
        if retention_days is None or not isinstance(run_id, str) or not run_id:
            return None
        expected_fields = {
            "action",
            "agent",
            "cost",
            "detail",
            "escalation",
            "event_id",
            "idempotency_key",
            "input_digests",
            "next_state",
            "output_digests",
            "run_id",
            "stage",
            "tool",
            "ts",
            "verdict",
        }
        for event in events:
            if set(event) != expected_fields or event.get("run_id") != run_id:
                return None
            identity = {key: event[key] for key in expected_fields if key not in {"event_id", "ts"}}
            digest_subject = (
                identity if event.get("idempotency_key") else {**identity, "ts": event.get("ts")}
            )
            if event.get("event_id") != _canonical_digest(digest_subject):
                return None
        first = events[0]
        first_outputs = first.get("output_digests")
        modern_policy_binding = bool(
            first.get("stage") == "contract_lock"
            and first.get("action") == "lock"
            and isinstance(first_outputs, dict)
            and first_outputs.get("retention_policy") == retention_policy_digest(retention_days)
        )
        legacy_bindings = [
            event
            for event in events
            if event.get("stage") == "contract_lock"
            and event.get("action") == "bind_legacy_retention_policy"
        ]
        completion_bindings = [
            event
            for event in events
            if event.get("stage") == "release_report"
            and event.get("action") == "bind_legacy_retention_completion"
        ]
        release_reports = [
            event
            for event in events
            if event.get("stage") == "release_report"
            and event.get("action") == "report"
            and not event.get("idempotency_key")
        ]
        if len(release_reports) != 1:
            return None
        report = release_reports[0]
        report_outputs = report.get("output_digests")
        if not isinstance(report_outputs, dict):
            return None

        if modern_policy_binding:
            if (
                legacy_bindings
                or completion_bindings
                or report is not events[-1]
                or report_outputs.get("terminal_retention")
                != terminal_retention_digest(retention_days, stage="complete")
            ):
                return None
            completed_at = cls._authenticated_timestamp(report.get("ts"))
            if completed_at is None:
                return None
            return _AuthenticatedRetention(retention_days, completed_at)

        contract = state.get("contract")
        if (
            len(legacy_bindings) != 1
            or len(completion_bindings) != 1
            or not isinstance(contract, dict)
            or not isinstance(first_outputs, dict)
            or first.get("stage") != "contract_lock"
            or first.get("action") != "lock"
            or first_outputs.get("contract") != contract.get("digest")
            or "retention_policy" in first_outputs
            or len(events) < 3
            or events[-3:] != [report, legacy_bindings[0], completion_bindings[0]]
            or "terminal_retention" in report_outputs
        ):
            return None
        binding = legacy_bindings[0]
        completion = completion_bindings[0]
        completion_outputs = completion.get("output_digests")
        if not isinstance(completion_outputs, dict):
            return None
        blank_fields = ("detail", "escalation", "next_state", "tool", "verdict")
        if (
            binding.get("agent") != "pmpe-core"
            or binding.get("input_digests") != {"contract": contract.get("digest")}
            or binding.get("output_digests")
            != {"retention_policy": retention_policy_digest(retention_days)}
            or binding.get("idempotency_key") != "legacy-retention-policy/v1"
            or binding.get("cost") is not None
            or any(binding.get(field) != "" for field in blank_fields)
            or completion.get("agent") != "pmpe-core"
            or completion.get("input_digests") != {"completion_event": report.get("event_id")}
            or completion_outputs.get("terminal_retention")
            != terminal_retention_digest(retention_days, stage="complete")
            or set(completion_outputs) != {"terminal_retention"}
            or completion.get("idempotency_key") != "legacy-retention-completion/v1"
            or completion.get("cost") is not None
            or any(completion.get(field) != "" for field in blank_fields)
        ):
            return None
        completed_at = cls._authenticated_timestamp(report.get("ts"))
        if completed_at is None:
            return None
        return _AuthenticatedRetention(retention_days, completed_at)

    @staticmethod
    def _authenticated_timestamp(value: object) -> datetime | None:
        if not isinstance(value, str) or not value:
            return None
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(normalized)
        except (OverflowError, ValueError):
            return None
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(UTC)

    @staticmethod
    def _validated_retention_days(policy: dict[str, Any]) -> int | None:
        value = policy.get("retention_days", DEFAULT_RETENTION_DAYS)
        try:
            return validate_retention_days(value)
        except ValueError:
            return None

    @staticmethod
    def _read_records(path: Path) -> list[dict[str, Any]]:
        try:
            records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        except (UnicodeDecodeError, json.JSONDecodeError, OSError):
            return []
        return records if all(isinstance(record, dict) for record in records) else []

    @staticmethod
    def _read_record(path: Path) -> dict[str, Any]:
        try:
            if path.name.endswith(".jsonl"):
                records = [
                    json.loads(line) for line in path.read_text().splitlines() if line.strip()
                ]
                record = records[-1]
            else:
                record = json.loads(path.read_text())
        except (IndexError, UnicodeDecodeError, json.JSONDecodeError, OSError):
            return {}
        return record if isinstance(record, dict) else {}
