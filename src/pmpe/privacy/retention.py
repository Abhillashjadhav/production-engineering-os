"""Bounded retention enforcement for explicitly selected data roots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path


@dataclass(frozen=True)
class RetentionResult:
    deleted: tuple[str, ...]
    retained: tuple[str, ...]


class RetentionController:
    def __init__(self, *, retention_days: int) -> None:
        if retention_days < 0:
            raise ValueError("retention days cannot be negative")
        self.retention_days = retention_days

    def purge(self, root: Path, *, now: datetime) -> RetentionResult:
        root = root.resolve()
        if not root.is_dir():
            raise ValueError("retention root is unavailable")
        if now.tzinfo is None:
            raise ValueError("retention clock must carry a timezone")
        cutoff = now.astimezone(UTC) - timedelta(days=self.retention_days)
        deleted: list[str] = []
        retained: list[str] = []
        for path in sorted(root.rglob("*")):
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            modified = datetime.fromtimestamp(path.stat(follow_symlinks=False).st_mtime, UTC)
            if modified <= cutoff:
                path.unlink()
                deleted.append(relative)
            else:
                retained.append(relative)
        return RetentionResult(deleted=tuple(deleted), retained=tuple(retained))
