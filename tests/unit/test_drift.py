"""Drift measurement: baseline-vs-current comparison across the five categories,
HOLD on any new hard-gate failure, planted drift fixtures detected."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from pmpe.evals.calibration import agreement_report, queue_uncalibrated
from pmpe.evals.drift import compare

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "evals" / "fixtures" / "drift"


def _baseline() -> dict[str, Any]:
    return json.loads((REPO_ROOT / "evals" / "baselines" / "synthetic-baseline.json").read_text())


def _thresholds() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load((REPO_ROOT / "evals" / "thresholds.yaml").read_text())
    return loaded


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


def test_thresholds_are_labeled_provisional() -> None:
    thresholds = _thresholds()
    assert thresholds["provisional"] is True
    assert "not production-calibrated" in thresholds["note"]


def test_baseline_is_labeled_synthetic() -> None:
    assert _baseline()["synthetic"] is True


def test_identical_results_produce_no_drift() -> None:
    report = compare(_baseline(), _baseline(), _thresholds())
    assert report.status == "OK"
    assert report.items == []


def test_new_hard_gate_failure_always_holds() -> None:
    report = compare(_baseline(), _fixture("current_hard_gate_failure.json"), _thresholds())
    assert report.status == "HOLD"
    assert any(i.hold and i.category == "agent_behaviour" for i in report.items)


def test_pass_rate_regression_is_detected() -> None:
    report = compare(_baseline(), _fixture("current_pass_rate_drop.json"), _thresholds())
    assert any(i.category == "agent_behaviour" for i in report.items)


def test_trajectory_violation_holds() -> None:
    report = compare(_baseline(), _fixture("current_trajectory_violation.json"), _thresholds())
    assert report.status == "HOLD"
    assert any(i.category == "trajectory" for i in report.items)


def test_coverage_gap_is_detected() -> None:
    report = compare(_baseline(), _fixture("current_coverage_gap.json"), _thresholds())
    assert any(i.category == "eval_coverage" for i in report.items)


def test_judge_disagreement_is_detected_with_direction() -> None:
    report = compare(_baseline(), _fixture("current_judge_drift.json"), _thresholds())
    judge_items = [i for i in report.items if i.category == "judge"]
    assert judge_items
    assert "judge-higher" in judge_items[0].description or "judge-lower" in (
        judge_items[0].description
    )


def test_engineering_output_growth_is_detected() -> None:
    report = compare(_baseline(), _fixture("current_output_growth.json"), _thresholds())
    assert any(i.category == "engineering_output" for i in report.items)


# --- judge calibration -----------------------------------------------------------------


def test_agreement_report_computes_rate_and_direction() -> None:
    pairs = [
        {"case_id": "G-1", "judge": "pass", "human": "pass"},
        {"case_id": "G-2", "judge": "pass", "human": "fail"},
        {"case_id": "G-3", "judge": "fail", "human": "fail"},
        {"case_id": "G-4", "judge": "pass", "human": "fail"},
    ]
    report = agreement_report(pairs)
    assert report["agreement_rate"] == 0.5
    assert report["judge_higher"] == 2
    assert report["judge_lower"] == 0


def test_uncalibrated_verdicts_queue_for_human_labels(tmp_path: Path) -> None:
    queue_path = tmp_path / "human_calibration_queue.jsonl"
    queued = queue_uncalibrated([{"case_id": "G-9", "judge": "pass", "human": None}], queue_path)
    assert queued == 1
    lines = queue_path.read_text().strip().splitlines()
    assert json.loads(lines[0])["case_id"] == "G-9"
