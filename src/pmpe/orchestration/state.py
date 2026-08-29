"""Persistent, resumable workflow state.

state.json is rewritten atomically after every transition so legacy fixture state
remains loadable after a crash. This type is a read-only compatibility projection
in shipped code; only the explicit test harness replays incomplete steps.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from pmpe.domain.models import StepStatus
from pmpe.domain.serialize import atomic_write_json
from pmpe.privacy.retention import (
    DEFAULT_RETENTION_DAYS,
    retention_policy_digest,
    run_state_retention_digest,
    validate_retention_days,
)
from pmpe.telemetry.events import utc_now

STEP_ORDER: tuple[str, ...] = (
    "ingest",
    "validate",
    "plan",
    "architecture",
    "acceptance",
    "generate_tests",
    "confirm_red",
    "implement",
    "quality_gates",
    "create_pr",
    "review",
    "fix",
    "retest",
    "merge_gate",
    "merge",
    "deploy",
    "verify",
    "report",
)

_COMPLETE = {StepStatus.DONE, StepStatus.SKIPPED}


@dataclass
class StepRecord:
    status: StepStatus = StepStatus.PENDING
    started_at: str | None = None
    finished_at: str | None = None
    detail: str = ""


@dataclass
class RunState:
    run_id: str
    run_dir: Path
    spec_digest: str
    spec_file: str = ""
    created_at: str = ""
    retention_days: int = DEFAULT_RETENTION_DAYS
    completed_at: str = ""
    outcome: str = ""  # "" while running; success | no_merge | blocked | failed
    steps: dict[str, StepRecord] = field(default_factory=dict)

    @classmethod
    def new(
        cls,
        run_id: str,
        run_dir: Path,
        spec_digest: str,
        spec_file: str = "",
        *,
        retention_days: int = DEFAULT_RETENTION_DAYS,
    ) -> RunState:
        return cls(
            run_id=run_id,
            run_dir=Path(run_dir),
            spec_digest=spec_digest,
            spec_file=spec_file,
            created_at=utc_now(),
            retention_days=validate_retention_days(retention_days),
            steps={name: StepRecord() for name in STEP_ORDER},
        )

    def status_of(self, step: str) -> StepStatus:
        return self.steps[step].status

    def next_step(self) -> str | None:
        for name in STEP_ORDER:
            if self.steps[name].status not in _COMPLETE:
                return name
        return None

    def mark(self, step: str, status: StepStatus, detail: str = "") -> None:
        record = self.steps[step]
        record.status = status
        if detail:
            record.detail = detail
        if status is StepStatus.RUNNING and record.started_at is None:
            record.started_at = utc_now()
        if status in (
            StepStatus.DONE,
            StepStatus.FAILED,
            StepStatus.BLOCKED,
            StepStatus.SKIPPED,
        ):
            if record.started_at is None:
                record.started_at = utc_now()
            record.finished_at = utc_now()

    def save(self) -> None:
        retention_days = validate_retention_days(self.retention_days)
        if self.outcome and not self.completed_at:
            self.completed_at = utc_now()
        if not self.outcome and self.completed_at:
            raise ValueError("an active run cannot carry a completion timestamp")
        retention_record = (
            run_state_retention_digest(
                run_id=self.run_id,
                spec_digest=self.spec_digest,
                created_at=self.created_at,
                outcome=self.outcome,
                completed_at=self.completed_at,
                retention_days=retention_days,
            )
            if self.outcome
            else ""
        )
        payload = {
            "run_id": self.run_id,
            "spec_digest": self.spec_digest,
            "spec_file": self.spec_file,
            "created_at": self.created_at,
            "retention_days": retention_days,
            "retention_policy_digest": retention_policy_digest(retention_days),
            "completed_at": self.completed_at,
            "retention_record_digest": retention_record,
            "outcome": self.outcome,
            "steps": {
                name: {
                    "status": rec.status.value,
                    "started_at": rec.started_at,
                    "finished_at": rec.finished_at,
                    "detail": rec.detail,
                }
                for name, rec in self.steps.items()
            },
        }
        atomic_write_json(self.run_dir / "state.json", payload)

    @classmethod
    def load(cls, run_dir: Path) -> RunState:
        payload = json.loads((Path(run_dir) / "state.json").read_text())
        state = cls(
            run_id=payload["run_id"],
            run_dir=Path(run_dir),
            spec_digest=payload["spec_digest"],
            spec_file=payload.get("spec_file", ""),
            created_at=payload.get("created_at", ""),
            retention_days=validate_retention_days(
                payload.get("retention_days", DEFAULT_RETENTION_DAYS)
            ),
            completed_at=payload.get("completed_at", ""),
            outcome=payload.get("outcome", ""),
        )
        state.steps = {
            name: StepRecord(
                status=StepStatus(raw["status"]),
                started_at=raw.get("started_at"),
                finished_at=raw.get("finished_at"),
                detail=raw.get("detail", ""),
            )
            for name, raw in payload["steps"].items()
        }
        # tolerate states written by older step lists: missing steps are pending
        for name in STEP_ORDER:
            state.steps.setdefault(name, StepRecord())
        return state
