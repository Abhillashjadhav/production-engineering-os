"""Failure paths: every gate must catch its planted failure; recovery must work."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from pmpe.config import PipelineConfig
from pmpe.domain.errors import SpecError
from tests.conftest import mutate_contradictory, mutate_production_target
from tests.legacy_v1.workflow import WorkflowEngine

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "schemas" / "mvp_spec.schema.json"


def _engine(runs_dir: Path, **overrides: object) -> WorkflowEngine:
    return WorkflowEngine(PipelineConfig(runs_dir=runs_dir, schema_path=SCHEMA, **overrides))  # type: ignore[arg-type]


def test_contradictory_spec_blocks_at_validation(
    make_spec_file: Callable[..., Path], pipeline_workdir: Path
) -> None:
    spec_path = make_spec_file(mutate_contradictory)
    result = _engine(pipeline_workdir).run(spec_path)
    assert result.status == "blocked"
    escalations = list((result.run_dir / "escalations").glob("ESC-*.json"))
    assert escalations, "a contradiction must produce a human escalation"
    esc = json.loads(escalations[0].read_text())
    assert esc["risk"] == "high"
    assert esc["step"] == "validate"
    # nothing downstream ran
    state = json.loads((result.run_dir / "state.json").read_text())
    assert state["steps"]["plan"]["status"] == "pending"


def test_structural_spec_defect_fails_instead_of_blocking(
    make_spec_file: Callable[..., Path], pipeline_workdir: Path
) -> None:
    """Broken references are not approvable: an approved run would crash in codegen,
    so the pipeline must fail fast with a spec-fix message, not offer an escalation."""
    from tests.conftest import mutate_missing_entity

    spec_path = make_spec_file(mutate_missing_entity)
    with pytest.raises(Exception, match="not approvable"):
        _engine(pipeline_workdir).run(spec_path)
    run_dir = next(pipeline_workdir.glob("run-*"))
    assert (
        not list((run_dir / "escalations").glob("ESC-*.json"))
        if (run_dir / "escalations").is_dir()
        else True
    )
    state = json.loads((run_dir / "state.json").read_text())
    assert state["steps"]["validate"]["status"] == "failed"


def test_malformed_spec_is_rejected_at_ingest(fixtures_dir: Path, pipeline_workdir: Path) -> None:
    with pytest.raises(SpecError) as excinfo:
        _engine(pipeline_workdir).run(fixtures_dir / "malformed_spec.yaml")
    assert "product_name" in str(excinfo.value)


def test_production_target_blocks_then_approval_resumes_to_success(
    make_spec_file: Callable[..., Path], pipeline_workdir: Path
) -> None:
    spec_path = make_spec_file(mutate_production_target)
    engine = _engine(pipeline_workdir)
    result = engine.run(spec_path)
    assert result.status == "blocked"

    escalations = list((result.run_dir / "escalations").glob("ESC-*.json"))
    assert len(escalations) == 1
    esc_id = json.loads(escalations[0].read_text())["id"]

    engine.approve(result.run_id, esc_id, approver="abhillash", reason="local fallback accepted")
    resumed = engine.resume(result.run_id)
    assert resumed.status == "success"

    # the approval is part of the audit trail and the final report
    report = (result.run_dir / "artifacts" / "final_report.md").read_text()
    assert esc_id in report
    assert "abhillash" in report


def test_rejected_escalation_fails_the_run(
    make_spec_file: Callable[..., Path], pipeline_workdir: Path
) -> None:
    spec_path = make_spec_file(mutate_production_target)
    engine = _engine(pipeline_workdir)
    result = engine.run(spec_path)
    assert result.status == "blocked"
    esc_id = json.loads(next((result.run_dir / "escalations").glob("ESC-*.json")).read_text())["id"]
    engine.approve(result.run_id, esc_id, approver="abhillash", reason="no", approved=False)
    resumed = engine.resume(result.run_id)
    assert resumed.status == "failed"


def test_planted_vulnerability_yields_no_merge_and_no_deploy(
    golden_spec_path: Path, pipeline_workdir: Path
) -> None:
    engine = _engine(
        pipeline_workdir,
        chaos_inject_files={"app/danger.py": "def run(x):\n    return eval(x)\n"},
    )
    result = engine.run(golden_spec_path)
    assert result.status == "no_merge"

    decision = json.loads((result.run_dir / "artifacts" / "merge_decision.json").read_text())
    assert decision["recommendation"] == "NO_MERGE"

    state = json.loads((result.run_dir / "state.json").read_text())
    assert state["steps"]["merge"]["status"] == "skipped"
    assert state["steps"]["deploy"]["status"] == "skipped"
    assert state["steps"]["report"]["status"] == "done"  # the report still lands

    # an unresolvable blocking finding is escalated to a human
    escalations = list((result.run_dir / "escalations").glob("ESC-*.json"))
    assert escalations


def test_crash_recovery_resumes_without_reexecuting_done_steps(
    golden_spec_path: Path, pipeline_workdir: Path
) -> None:
    crashing = _engine(pipeline_workdir, chaos_fail_at_step="quality_gates")
    result = crashing.run(golden_spec_path)
    assert result.status == "failed"

    state_before = json.loads((result.run_dir / "state.json").read_text())
    assert state_before["steps"]["implement"]["status"] == "done"
    implement_started = state_before["steps"]["implement"]["started_at"]

    healthy = _engine(pipeline_workdir)
    resumed = healthy.resume(result.run_id)
    assert resumed.status == "success"

    state_after = json.loads((result.run_dir / "state.json").read_text())
    assert state_after["steps"]["implement"]["started_at"] == implement_started
    assert state_after["steps"]["quality_gates"]["status"] == "done"
