"""Metric hooks for the product's North Star, leading metrics, and guardrails.

V1 computes per-run leading metrics from the event log and run artifacts. The
``MetricsRecorder`` protocol is the seam for real analytics sinks in V2; the NSM
itself (production usage without engineer intervention) needs fleet-level usage
data that a single local run cannot observe — the hook records the per-run
contribution (run outcome) so a future aggregator can compute it.
"""

from __future__ import annotations

from typing import Any, Protocol

from pmpe.domain.models import StepStatus


class MetricsRecorder(Protocol):
    def record(self, name: str, value: Any) -> None: ...

    def snapshot(self) -> dict[str, Any]: ...


class LocalMetricsRecorder:
    """In-memory recorder; the orchestrator persists the snapshot as metrics.json."""

    def __init__(self) -> None:
        self._values: dict[str, Any] = {}

    def record(self, name: str, value: Any) -> None:
        self._values[name] = value

    def snapshot(self) -> dict[str, Any]:
        return dict(self._values)


def compute_run_metrics(
    *,
    step_statuses: dict[str, StepStatus],
    validation_passed: bool,
    tests_total: int,
    tests_passed: int,
    requirements_total: int,
    requirements_with_passing_tests: int,
    escalation_count: int,
    blocking_findings: int,
    fixes_applied: int,
    duration_seconds: float,
    outcome: str,
) -> dict[str, Any]:
    """Leading metrics + guardrail hooks for one run.

    See docs/product-requirements-interpretation.md for the metric map.
    """
    total = len(step_statuses)
    done = sum(1 for s in step_statuses.values() if s is StepStatus.DONE)
    return {
        "spec_validation_passed": validation_passed,
        "steps_completed_ratio": round(done / total, 4) if total else 0.0,
        "test_pass_rate": round(tests_passed / tests_total, 4) if tests_total else 0.0,
        "requirements_with_passing_tests_ratio": (
            round(requirements_with_passing_tests / requirements_total, 4)
            if requirements_total
            else 0.0
        ),
        "escalation_count": escalation_count,
        "blocking_findings": blocking_findings,
        "fix_agent_interventions": fixes_applied,
        "duration_seconds": round(duration_seconds, 3),
        "run_outcome": outcome,  # per-run NSM contribution
    }
