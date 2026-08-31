"""SYS-14: deterministic, resumable workflow state."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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
        "deploy",
        "verify",
        "report",
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


def test_load_rejects_retention_changed_after_admission(tmp_path: Path) -> None:
    state = RunState.new(run_id="r1", run_dir=tmp_path, spec_digest="abc")
    state.save()
    state_path = tmp_path / "state.json"
    payload = json.loads(state_path.read_text())
    payload["retention_days"] = 365
    state_path.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="retention policy changed"):
        RunState.load(tmp_path)


def test_load_rejects_one_missing_modern_retention_field(tmp_path: Path) -> None:
    state = RunState.new(run_id="r1", run_dir=tmp_path, spec_digest="abc")
    state.save()
    state_path = tmp_path / "state.json"
    payload = json.loads(state_path.read_text())
    payload.pop("retention_policy_digest")
    payload["retention_days"] = 365
    state_path.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="retention binding is incomplete"):
        RunState.load(tmp_path)


def test_loaded_state_rejects_save_after_retention_rename(tmp_path: Path) -> None:
    state = RunState.new(run_id="r1", run_dir=tmp_path, spec_digest="abc")
    state.save()
    loaded = RunState.load(tmp_path)
    tombstone = tmp_path.with_name(".retention-delete-run-state")
    tmp_path.rename(tombstone)

    loaded.mark("ingest", StepStatus.RUNNING)
    with pytest.raises(ValueError, match="directory is missing"):
        loaded.save()

    assert not tmp_path.exists()
    assert tombstone.exists()


def test_load_keeps_the_locked_identity_if_retention_renames_during_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = RunState.new(run_id="r1", run_dir=tmp_path, spec_digest="abc")
    state.save()
    tombstone = tmp_path.with_name(".retention-delete-load-race")
    original_post_init = RunState.__post_init__

    def rename_during_construction(loaded: RunState) -> None:
        tmp_path.rename(tombstone)
        original_post_init(loaded)

    monkeypatch.setattr(RunState, "__post_init__", rename_during_construction)
    loaded = RunState.load(tmp_path)

    with pytest.raises(ValueError, match="directory is missing"):
        loaded.save()
    assert not tmp_path.exists()


def test_state_file_is_always_valid_json(tmp_path: Path) -> None:
    state = RunState.new(run_id="r1", run_dir=tmp_path, spec_digest="abc")
    state.save()
    parsed = json.loads((tmp_path / "state.json").read_text())
    assert parsed["run_id"] == "r1"
    assert parsed["retention_days"] == 30
    assert parsed["retention_policy_digest"].startswith("sha256:")
    assert parsed["retention_record_digest"] == ""


def test_terminal_state_persists_authenticated_retention_subject(tmp_path: Path) -> None:
    state = RunState.new(
        run_id="r1",
        run_dir=tmp_path,
        spec_digest="abc",
        retention_days=7,
    )
    state.outcome = "success"
    state.save()

    parsed = json.loads((tmp_path / "state.json").read_text())
    assert parsed["retention_days"] == 7
    assert parsed["completed_at"]
    assert parsed["retention_record_digest"].startswith("sha256:")


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
