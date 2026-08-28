"""SYS-05: deterministic engineering planning with dependency graph."""

from __future__ import annotations

from typing import Any

import pytest

from pmpe.domain.models import MvpSpec
from pmpe.ingestion.normalizer import normalize_spec
from pmpe.planning.planner import EngineeringPlanner


@pytest.fixture()
def spec(golden_spec_dict: dict[str, Any]) -> MvpSpec:
    return normalize_spec(golden_spec_dict)


@pytest.fixture()
def planner() -> EngineeringPlanner:
    return EngineeringPlanner()


def test_every_functional_requirement_is_covered_by_a_task(
    planner: EngineeringPlanner, spec: MvpSpec
) -> None:
    plan = planner.plan(spec)
    covered = {rid for task in plan.tasks for rid in task.requirement_ids}
    assert {fr.id for fr in spec.functional_requirements} <= covered


def test_implementation_order_respects_dependencies(
    planner: EngineeringPlanner, spec: MvpSpec
) -> None:
    plan = planner.plan(spec)
    position = {tid: i for i, tid in enumerate(plan.order)}
    for task in plan.tasks:
        for dep in task.depends_on:
            assert position[dep] < position[task.id], f"{dep} must precede {task.id}"


def test_order_covers_every_task_exactly_once(planner: EngineeringPlanner, spec: MvpSpec) -> None:
    plan = planner.plan(spec)
    assert sorted(plan.order) == sorted(t.id for t in plan.tasks)


def test_components_identified_for_reference_stack(
    planner: EngineeringPlanner, spec: MvpSpec
) -> None:
    plan = planner.plan(spec)
    assert {"storage", "auth", "api"} <= set(plan.components)


def test_tasks_have_relative_complexity(planner: EngineeringPlanner, spec: MvpSpec) -> None:
    plan = planner.plan(spec)
    assert all(t.complexity in {"S", "M", "L"} for t in plan.tasks)


def test_plan_identifies_risks(planner: EngineeringPlanner, spec: MvpSpec) -> None:
    plan = planner.plan(spec)
    assert plan.risks, "spec declares risks; the plan must carry them"


def test_planning_is_deterministic(planner: EngineeringPlanner, spec: MvpSpec) -> None:
    a = planner.plan(spec)
    b = planner.plan(spec)
    assert a == b


def test_dependency_graph_is_acyclic(planner: EngineeringPlanner, spec: MvpSpec) -> None:
    plan = planner.plan(spec)
    seen: set[str] = set()
    for tid in plan.order:
        deps = plan.graph.get(tid, [])
        assert set(deps) <= seen, f"cycle or forward reference at {tid}"
        seen.add(tid)
