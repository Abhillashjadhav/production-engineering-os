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

_TOMBSTONE_PREFIX = ".retention-delete-"
DEFAULT_RETENTION_DAYS = 30


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


def validate_retention_days(retention_days: int) -> int:
    """Validate one immutable, run-bound retention policy."""

    if isinstance(retention_days, bool) or not isinstance(retention_days, int):
        raise ValueError("retention days must be an integer")
    if retention_days < 0:
        raise ValueError("retention days cannot be negative")
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
                    retention_days = self._authenticated_retention_days(
                        marker_path,
                        policy_path,
                    )
                    modified = datetime.fromtimestamp(
                        marker_path.stat(follow_symlinks=False).st_mtime,
                        UTC,
                    )
                    if retention_days is None or modified > now - timedelta(days=retention_days):
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
        return None

    @classmethod
    def _authenticated_retention_days(
        cls,
        marker_path: Path,
        policy_path: Path,
    ) -> int | None:
        if marker_path.name == "lifecycle-events.jsonl":
            return cls._authenticated_lifecycle_retention(marker_path, policy_path)
        return cls._authenticated_engineering_retention(marker_path)

    @classmethod
    def _authenticated_lifecycle_retention(
        cls,
        ledger_path: Path,
        metadata_path: Path,
    ) -> int | None:
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
        evidence_refs = initial.get("evidence_refs")
        if (
            initial.get("kind") != "STATE_CREATED"
            or not isinstance(evidence_refs, dict)
            or evidence_refs.get("metadata_digest") != _canonical_digest(metadata)
            or events[-1].get("target") != "COMPLETED"
        ):
            return None
        return cls._validated_retention_days(metadata)

    @classmethod
    def _authenticated_engineering_retention(cls, state_path: Path) -> int | None:
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
        terminal = events[-1]
        first_outputs = first.get("output_digests")
        terminal_outputs = terminal.get("output_digests")
        if (
            first.get("stage") != "contract_lock"
            or first.get("action") != "lock"
            or not isinstance(first_outputs, dict)
            or first_outputs.get("retention_policy") != retention_policy_digest(retention_days)
            or terminal.get("stage") != "release_report"
            or terminal.get("action") != "report"
            or not isinstance(terminal_outputs, dict)
            or terminal_outputs.get("terminal_retention")
            != terminal_retention_digest(retention_days, stage="complete")
        ):
            return None
        return retention_days

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
