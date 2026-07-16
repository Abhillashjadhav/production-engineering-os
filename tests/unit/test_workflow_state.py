"""SYS-14: deterministic, resumable workflow state."""

from __future__ import annotations

import json
from pathlib import Path

from pmpe.domain.models import StepStatus
from pmpe.orchestration.state import STEP_ORDER, RunState


def test_step_order_is_the_documented_lifecycle() -> None:
    assert STEP_ORDER == (
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
    )


def test_new_state_has_all_steps_pending(tmp_path: Path) -> None:
    state = RunState.new(run_id="r1", run_dir=tmp_path, spec_digest="abc")
    assert [s for s in STEP_ORDER if state.status_of(s) is StepStatus.PENDING] == list(STEP_ORDER)


def test_next_step_is_first_incomplete(tmp_path: Path) -> None:
    state = RunState.new(run_id="r1", run_dir=tmp_path, spec_digest="abc")
    assert state.next_step() == "ingest"
    state.mark("ingest", StepStatus.DONE)
    state.mark("validate", StepStatus.DONE)
    assert state.next_step() == "plan"


def test_save_load_roundtrip(tmp_path: Path) -> None:
    state = RunState.new(run_id="r1", run_dir=tmp_path, spec_digest="abc")
    state.mark("ingest", StepStatus.DONE)
    state.mark("validate", StepStatus.BLOCKED, detail="ESC-001")
    state.save()
    loaded = RunState.load(tmp_path)
    assert loaded.status_of("ingest") is StepStatus.DONE
    assert loaded.status_of("validate") is StepStatus.BLOCKED
    assert loaded.run_id == "r1"
    assert loaded.spec_digest == "abc"


def test_state_file_is_always_valid_json(tmp_path: Path) -> None:
    state = RunState.new(run_id="r1", run_dir=tmp_path, spec_digest="abc")
    state.save()
    parsed = json.loads((tmp_path / "state.json").read_text())
    assert parsed["run_id"] == "r1"


def test_blocked_and_failed_stop_progression(tmp_path: Path) -> None:
    state = RunState.new(run_id="r1", run_dir=tmp_path, spec_digest="abc")
    state.mark("ingest", StepStatus.DONE)
    state.mark("validate", StepStatus.BLOCKED, detail="ESC-001")
    assert state.next_step() == "validate"
    state.mark("validate", StepStatus.FAILED, detail="boom")
    assert state.next_step() == "validate"


def test_done_steps_record_timestamps(tmp_path: Path) -> None:
    state = RunState.new(run_id="r1", run_dir=tmp_path, spec_digest="abc")
    state.mark("ingest", StepStatus.RUNNING)
    state.mark("ingest", StepStatus.DONE)
    step = state.steps["ingest"]
    assert step.started_at is not None
    assert step.finished_at is not None
