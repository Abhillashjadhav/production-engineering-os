"""Structured JSONL event log — the pipeline's explainability record."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pmpe.domain.serialize import jsonable
from pmpe.privacy.retention import RetentionController


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class EventLog:
    """Append-only JSONL log under the run directory.

    Every automated decision emits an event carrying the rule that produced it,
    so any outcome can be explained after the fact.
    """

    def __init__(
        self,
        run_dir: Path,
        *,
        retention_days: int | None = None,
        trusted_clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        run_dir = Path(run_dir)
        if retention_days is not None:
            run_dir.parent.mkdir(parents=True, exist_ok=True)
            RetentionController(retention_days=retention_days).purge(
                run_dir.parent,
                now=trusted_clock(),
            )
        self.path = run_dir / "events.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event_type: str, **fields: Any) -> None:
        record = {"ts": utc_now(), "type": event_type, **jsonable(fields)}
        with self.path.open("a") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        out: list[dict[str, Any]] = []
        for line in self.path.read_text().splitlines():
            if line.strip():
                out.append(json.loads(line))
        return out
