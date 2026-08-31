"""Persistent, resumable workflow state.

state.json is rewritten atomically after every transition so legacy fixture state
remains loadable after a crash. This type is a read-only compatibility projection
in shipped code; only the explicit test harness replays incomplete steps.
"""

from __future__ import annotations

import fcntl
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
    _run_dir_identity: tuple[int, int] | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        try:
            current = self.run_dir.stat()
        except FileNotFoundError:
            return
        self._run_dir_identity = (current.st_dev, current.st_ino)

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
        if self._run_dir_identity is None:
            self.run_dir.mkdir(parents=True, exist_ok=True)
            current = self.run_dir.stat()
            self._run_dir_identity = (current.st_dev, current.st_ino)
        try:
            lock = (self.run_dir / "state.lock").open("a+")
        except FileNotFoundError as exc:
            raise ValueError("run-state directory is missing") from exc
        with lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                try:
                    current = self.run_dir.stat()
                except FileNotFoundError as exc:
                    raise ValueError("run-state directory is missing") from exc
                if (current.st_dev, current.st_ino) != self._run_dir_identity:
                    raise ValueError("run-state directory was replaced")
                atomic_write_json(self.run_dir / "state.json", payload)
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    @classmethod
    def load(cls, run_dir: Path) -> RunState:
        run_dir = Path(run_dir)
        initial = run_dir.stat()
        try:
            lock = (run_dir / "state.lock").open("a+")
        except FileNotFoundError as exc:
            raise ValueError("run-state directory is missing") from exc
        with lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            current = run_dir.stat()
            if (current.st_dev, current.st_ino) != (initial.st_dev, initial.st_ino):
                raise ValueError("run-state directory was replaced")
            loaded_identity = (current.st_dev, current.st_ino)
            payload = json.loads((run_dir / "state.json").read_text())
        has_retention_days = "retention_days" in payload
        has_retention_policy = "retention_policy_digest" in payload
        if has_retention_days != has_retention_policy:
            raise ValueError("run-state retention binding is incomplete")
        retention_days = validate_retention_days(
            payload.get("retention_days", DEFAULT_RETENTION_DAYS)
        )
        persisted_policy = payload.get("retention_policy_digest")
        if persisted_policy is not None and persisted_policy != retention_policy_digest(
            retention_days
        ):
            raise ValueError("retention policy changed after run-state admission")
        outcome = payload.get("outcome", "")
        completed_at = payload.get("completed_at", "")
        if (
            has_retention_days
            and outcome
            and payload.get("retention_record_digest")
            != run_state_retention_digest(
                run_id=payload["run_id"],
                spec_digest=payload["spec_digest"],
                created_at=payload.get("created_at", ""),
                outcome=outcome,
                completed_at=completed_at,
                retention_days=retention_days,
            )
        ):
            raise ValueError("terminal retention record changed after run-state admission")
        state = cls(
            run_id=payload["run_id"],
            run_dir=run_dir,
            spec_digest=payload["spec_digest"],
            spec_file=payload.get("spec_file", ""),
            created_at=payload.get("created_at", ""),
            retention_days=retention_days,
            completed_at=completed_at,
            outcome=outcome,
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
        state._run_dir_identity = loaded_identity
        return state
