"""The end-to-end proof required by the V1 definition of done.

One golden run must demonstrate all ten lifecycle claims plus a verified local
deployment, hermetically and deterministically.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pmpe.config import PipelineConfig
from pmpe.gitops.local import LocalGitAdapter
from pmpe.orchestration.workflow import WorkflowEngine

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def golden_run(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, object]:
    """One full pipeline run shared by every assertion in this module."""
    runs_dir = tmp_path_factory.mktemp("runs")
    repo_root = Path(__file__).resolve().parents[2]
    config = PipelineConfig(
        runs_dir=runs_dir,
        schema_path=repo_root / "schemas" / "mvp_spec.schema.json",
    )
    engine = WorkflowEngine(config)
    result = engine.run(repo_root / "examples" / "taskflow_mvp_spec.yaml")
    return result.run_dir, result


def _artifact(run_dir: Path, name: str) -> Path:
    path = run_dir / "artifacts" / name
    assert path.exists(), f"missing artifact: {name}"
    return path


def test_1_valid_specification_accepted(golden_run: tuple[Path, object]) -> None:
    run_dir, result = golden_run
    assert result.status == "success"
    report = json.loads(_artifact(run_dir, "validation_report.json").read_text())
    assert report["errors"] == []
    assert report["questions"] == []


def test_2_engineering_plan_created(golden_run: tuple[Path, object]) -> None:
    run_dir, _ = golden_run
    plan = json.loads(_artifact(run_dir, "engineering_plan.json").read_text())
    assert plan["tasks"]
    assert plan["order"]
    assert plan["graph"]


def test_3_architecture_artifacts_generated(golden_run: tuple[Path, object]) -> None:
    run_dir, _ = golden_run
    _artifact(run_dir, "architecture.md")
    adrs = sorted((run_dir / "artifacts" / "adr").glob("ADR-*.md"))
    assert len(adrs) >= 3


def test_4_tests_created_before_implementation(golden_run: tuple[Path, object]) -> None:
    run_dir, _ = golden_run
    # 4a: the red run happened and failed as required
    red = json.loads(_artifact(run_dir, "confirm_red.json").read_text())
    assert red["tests_failed_before_implementation"] is True
    # 4b: the workspace git history shows test commit before any feat commit
    subjects = [c.subject for c in LocalGitAdapter(run_dir / "workspace").log()]
    ordered = list(reversed(subjects))  # oldest first
    first_test = next(i for i, s in enumerate(ordered) if s.startswith("test:"))
    first_feat = next(i for i, s in enumerate(ordered) if s.startswith("feat:"))
    assert first_test < first_feat


def test_5_implementation_produced(golden_run: tuple[Path, object]) -> None:
    run_dir, _ = golden_run
    workspace = run_dir / "workspace"
    assert (workspace / "app" / "api.py").exists()
    assert (workspace / "app" / "storage.py").exists()
    assert (workspace / "app" / "auth.py").exists()


def test_6_quality_checks_ran(golden_run: tuple[Path, object]) -> None:
    run_dir, _ = golden_run
    results = json.loads(_artifact(run_dir, "gate_results.json").read_text())
    names = {r["gate"] for r in results}
    assert {"compile", "unit", "integration", "security"} <= names
    assert all(r["passed"] for r in results if r["required"])


def test_7_review_findings_generated(golden_run: tuple[Path, object]) -> None:
    run_dir, _ = golden_run
    review = json.loads(_artifact(run_dir, "review_report.json").read_text())
    assert "findings" in review
    assert not [f for f in review["findings"] if f["blocking"]]


def test_8_safe_findings_fixed(golden_run: tuple[Path, object]) -> None:
    run_dir, _ = golden_run
    fix = json.loads(_artifact(run_dir, "fix_result.json").read_text())
    assert fix["escalated"] == []
    retest = json.loads(_artifact(run_dir, "gate_results_retest.json").read_text())
    assert all(r["passed"] for r in retest if r["required"])


def test_9_merge_eligibility_determined(golden_run: tuple[Path, object]) -> None:
    run_dir, _ = golden_run
    decision = json.loads(_artifact(run_dir, "merge_decision.json").read_text())
    assert decision["recommendation"] == "MERGE"
    assert decision["reasons"]
    git = LocalGitAdapter(run_dir / "workspace")
    assert git.current_branch() == "main"


def test_10_final_report_generated(golden_run: tuple[Path, object]) -> None:
    run_dir, _ = golden_run
    trace = json.loads(_artifact(run_dir, "traceability.json").read_text())
    assert trace["complete"] is True
    report_md = _artifact(run_dir, "final_report.md").read_text()
    for fr in ("FR-001", "FR-007"):
        assert fr in report_md


def test_deployment_verified(golden_run: tuple[Path, object]) -> None:
    run_dir, _ = golden_run
    deployment = json.loads(_artifact(run_dir, "deployment_result.json").read_text())
    assert deployment["environment"] == "local"
    assert deployment["healthy"] is True
    assert deployment["journey_passed"] is True
    workspace = run_dir / "workspace"
    assert (workspace / "deploy" / "ROLLBACK.md").exists()
    assert (workspace / "deploy" / "Dockerfile").exists()
    assert (workspace / "deploy" / "run.sh").exists()


def test_pr_record_created(golden_run: tuple[Path, object]) -> None:
    run_dir, _ = golden_run
    pr = json.loads(_artifact(run_dir, "pull_request.json").read_text())
    assert pr["title"]
    assert pr["commits"]
    assert pr["diff_stat"]


def test_workflow_state_all_done(golden_run: tuple[Path, object]) -> None:
    run_dir, _ = golden_run
    state = json.loads((run_dir / "state.json").read_text())
    statuses = {name: step["status"] for name, step in state["steps"].items()}
    assert set(statuses.values()) == {"done"}, statuses


def test_telemetry_and_metrics_recorded(golden_run: tuple[Path, object]) -> None:
    run_dir, _ = golden_run
    events = (run_dir / "events.jsonl").read_text().strip().splitlines()
    assert len(events) >= 18  # at least one event per step
    metrics = json.loads(_artifact(run_dir, "metrics.json").read_text())
    for key in (
        "spec_validation_passed",
        "steps_completed_ratio",
        "test_pass_rate",
        "requirements_with_passing_tests_ratio",
        "escalation_count",
        "duration_seconds",
    ):
        assert key in metrics, f"missing leading-metric hook: {key}"
    assert metrics["escalation_count"] == 0


def test_rerun_of_same_spec_is_deterministic(
    golden_run: tuple[Path, object], tmp_path: Path
) -> None:
    run_dir, _ = golden_run
    repo_root = Path(__file__).resolve().parents[2]
    config = PipelineConfig(
        runs_dir=tmp_path / "runs2",
        schema_path=repo_root / "schemas" / "mvp_spec.schema.json",
    )
    result2 = WorkflowEngine(config).run(repo_root / "examples" / "taskflow_mvp_spec.yaml")
    assert result2.status == "success"
    plan_a = json.loads(_artifact(run_dir, "engineering_plan.json").read_text())
    plan_b = json.loads((result2.run_dir / "artifacts" / "engineering_plan.json").read_text())
    assert plan_a == plan_b
