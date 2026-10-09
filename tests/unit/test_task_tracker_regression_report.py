"""The regression report may never read a blocked or failed entry run as PASS."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

MODULE = (
    Path(__file__).resolve().parents[2] / "examples" / "barebones" / "task-tracker-regression.py"
)


@pytest.fixture(scope="module")
def regression():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("task_tracker_regression", MODULE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_all_pass_with_no_findings_is_pass(regression, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "result.json").write_text(
        json.dumps({"criteria": {"AC-001": "PASS", "AC-002": "PASS"}, "findings": []})
    )
    outcome = regression.classify(tmp_path, 0)
    assert outcome["outcome"] == "PASS"
    assert outcome["failed_criteria"] == []


def test_one_failed_criterion_is_fail_even_with_exit_zero(regression, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "result.json").write_text(
        json.dumps({"criteria": {"AC-001": "PASS", "AC-004": "FAIL"}, "findings": [{"x": 1}]})
    )
    outcome = regression.classify(tmp_path, 0)
    assert outcome["outcome"] == "FAIL"
    assert outcome["failed_criteria"] == ["AC-004"]
    assert outcome["finding_count"] == 1


def test_refusal_before_execution_is_blocked_not_pass(regression, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "failure.json").write_text(
        json.dumps({"error": "TamperDetectedError", "detail": "APPROVAL_BOUND_ARTIFACT_CHANGED"})
    )
    outcome = regression.classify(tmp_path, 2)
    assert outcome["outcome"] == "BLOCKED"
    assert outcome["blocker"]["detail"].startswith("APPROVAL_BOUND_ARTIFACT_CHANGED")
    assert outcome["criteria"] == {}


def test_interrupted_run_without_any_record_is_blocked(regression, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    outcome = regression.classify(tmp_path, None)
    assert outcome["outcome"] == "BLOCKED"
    assert outcome["blocker"]["error"] == "NO_RESULT"


def test_compare_reports_outcome_and_criterion_changes(regression) -> None:  # type: ignore[no-untyped-def]
    previous = {"run_at": "t0", "outcome": "PASS", "criteria": {"AC-001": "PASS"}, "blocker": None}
    current = {"outcome": "FAIL", "criteria": {"AC-001": "FAIL"}, "blocker": None}
    delta = regression.compare(previous, current)
    assert delta["outcome_changed"] is True
    assert delta["criteria_changed"] == {"AC-001": {"before": "PASS", "after": "FAIL"}}
    assert regression.compare(None, current)["outcome_changed"] is None
