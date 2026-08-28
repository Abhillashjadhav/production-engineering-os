"""Bounded retention enforcement for explicitly selected data roots."""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_TOMBSTONE_PREFIX = ".retention-delete-"


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


class RetentionController:
    def __init__(self, *, retention_days: int) -> None:
        if retention_days < 0:
            raise ValueError("retention days cannot be negative")
        self.retention_days = retention_days

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
        cutoff = now.astimezone(UTC) - timedelta(days=self.retention_days)
        root_lock_path = root / ".retention.lock"
        with root_lock_path.open("a+") as root_lock:
            fcntl.flock(root_lock.fileno(), fcntl.LOCK_EX)
            try:
                return self._purge_locked(root, cutoff=cutoff, excluded=excluded)
            finally:
                fcntl.flock(root_lock.fileno(), fcntl.LOCK_UN)

    def _purge_locked(
        self,
        root: Path,
        *,
        cutoff: datetime,
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
            marker_path, lock_path, terminal_key, terminal_value = marker
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            tombstone: Path | None = None
            with lock_path.open("a+") as lock:
                try:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    retained.append(run_dir.name)
                    continue
                try:
                    record = self._read_record(marker_path)
                    modified = datetime.fromtimestamp(
                        marker_path.stat(follow_symlinks=False).st_mtime,
                        UTC,
                    )
                    if record.get(terminal_key) != terminal_value or modified > cutoff:
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
    def _completion_marker(run_dir: Path) -> tuple[Path, Path, str, str] | None:
        lifecycle = run_dir / "lifecycle-events.jsonl"
        if lifecycle.is_file():
            return lifecycle, run_dir / "lifecycle.lock", "target", "COMPLETED"
        engineering = run_dir / "run-state.json"
        if engineering.is_file():
            return engineering, run_dir / "ledger.lock", "stage", "complete"
        return None

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
