"""Deterministic drift reporter: baseline vs current across five categories.

Categories: agent_behaviour, trajectory, eval_coverage, judge, engineering_output.
Policy: any NEW hard-gate failure (absent from the baseline) is a HOLD, always.
Thresholds are configuration; the shipped defaults are provisional and labeled so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pmpe.evals.calibration import agreement_report


@dataclass(frozen=True)
class DriftItem:
    category: str
    description: str
    severity: str  # info | warn | hold
    hold: bool


@dataclass
class DriftReport:
    status: str  # OK | WATCH | HOLD
    items: list[DriftItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "items": [
                {
                    "category": i.category,
                    "description": i.description,
                    "severity": i.severity,
                    "hold": i.hold,
                }
                for i in self.items
            ],
        }


def compare(
    baseline: dict[str, Any], current: dict[str, Any], thresholds: dict[str, Any]
) -> DriftReport:
    items: list[DriftItem] = []
    items += _agent_behaviour(baseline, current, thresholds)
    items += _trajectory(current)
    items += _eval_coverage(baseline, current)
    items += _judge(current, thresholds)
    items += _engineering_output(baseline, current, thresholds)

    if any(i.hold for i in items):
        status = "HOLD"
    elif items:
        status = "WATCH"
    else:
        status = "OK"
    return DriftReport(status=status, items=items)


def _agent_results(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = payload.get("agent_results", {})
    return result


def _agent_behaviour(
    baseline: dict[str, Any], current: dict[str, Any], thresholds: dict[str, Any]
) -> list[DriftItem]:
    items: list[DriftItem] = []
    base, cur = _agent_results(baseline), _agent_results(current)

    baseline_failures = set(base.get("hard_gate_failures", []))
    for failure in cur.get("hard_gate_failures", []):
        if failure not in baseline_failures:
            items.append(
                DriftItem(
                    "agent_behaviour",
                    f"NEW hard-gate failure: {failure}",
                    "hold",
                    hold=True,
                )
            )

    max_drop = float(thresholds.get("pass_rate_drop_max", 0.05))
    base_rates = base.get("pass_rate_by_agent", {})
    for agent, current_rate in cur.get("pass_rate_by_agent", {}).items():
        base_rate = base_rates.get(agent)
        if base_rate is not None and base_rate - float(current_rate) > max_drop:
            items.append(
                DriftItem(
                    "agent_behaviour",
                    f"{agent} pass rate dropped {base_rate:.2f} -> {float(current_rate):.2f}",
                    "warn",
                    hold=False,
                )
            )
    for mistake_kind in ("routing_mistakes", "escalation_mistakes", "tool_permission_violations"):
        for mistake in cur.get(mistake_kind, []):
            items.append(
                DriftItem("agent_behaviour", f"{mistake_kind}: {mistake}", "hold", hold=True)
            )
    return items


def _trajectory(current: dict[str, Any]) -> list[DriftItem]:
    return [
        DriftItem(
            "trajectory",
            f"{v.get('check_id', 'TRAJ-?')}: {v.get('description', v)}",
            "hold",
            hold=True,
        )
        for v in current.get("trajectory_violations", [])
    ]


def _eval_coverage(baseline: dict[str, Any], current: dict[str, Any]) -> list[DriftItem]:
    items: list[DriftItem] = []
    coverage: dict[str, Any] = current.get("coverage", {})
    not_proven = int(coverage.get("not_proven", 0))
    if not_proven:
        items.append(
            DriftItem(
                "eval_coverage",
                f"{not_proven} requirement(s) lack executed coverage",
                "warn",
                hold=False,
            )
        )
    golden = set(baseline.get("coverage", {}).get("golden_cases", []))
    for cluster in coverage.get("failure_clusters", []):
        if cluster not in golden:
            items.append(
                DriftItem(
                    "eval_coverage",
                    f"failure cluster without golden coverage: {cluster}",
                    "warn",
                    hold=False,
                )
            )
    return items


def _judge(current: dict[str, Any], thresholds: dict[str, Any]) -> list[DriftItem]:
    pairs = current.get("judge", {}).get("pairs", [])
    if not pairs:
        return []
    report = agreement_report(pairs)
    minimum = float(thresholds.get("judge_agreement_min", 0.85))
    items: list[DriftItem] = []
    rate = report["agreement_rate"]
    if rate is not None and rate < minimum:
        direction = (
            "judge-higher (more lenient than humans)"
            if report["judge_higher"] >= report["judge_lower"]
            else "judge-lower (harsher than humans)"
        )
        items.append(
            DriftItem(
                "judge",
                f"judge-human agreement {rate:.2f} below {minimum:.2f}; "
                f"dominant direction: {direction}",
                "warn",
                hold=False,
            )
        )
    return items


def _engineering_output(
    baseline: dict[str, Any], current: dict[str, Any], thresholds: dict[str, Any]
) -> list[DriftItem]:
    items: list[DriftItem] = []
    base = baseline.get("engineering_output", {})
    cur = current.get("engineering_output", {})
    limits: dict[str, float] = thresholds.get("output_growth_max_pct", {})
    for metric, limit in limits.items():
        base_value = float(base.get(metric, 0) or 0)
        current_value = float(cur.get(metric, 0) or 0)
        if base_value <= 0:
            continue
        growth_pct = (current_value - base_value) / base_value * 100
        if growth_pct > float(limit):
            items.append(
                DriftItem(
                    "engineering_output",
                    f"{metric} grew {growth_pct:.0f}% (limit {limit:.0f}%): "
                    f"{base_value:g} -> {current_value:g}",
                    "warn",
                    hold=False,
                )
            )
    return items
